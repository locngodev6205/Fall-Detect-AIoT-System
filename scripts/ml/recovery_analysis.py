#!/usr/bin/env python3
"""Measure source timing and paired pose coverage without assigning labels."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import csv
from fractions import Fraction
import json
import math
from pathlib import Path
import random
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'fall_detect'))
LENGTHS = (10, 20, 30)


def probe(path):
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
         'stream=duration,nb_frames,avg_frame_rate,r_frame_rate,width,height,start_time:stream_side_data=rotation',
         '-of', 'json', str(path)], capture_output=True, text=True, check=True, timeout=25)
    stream = json.loads(result.stdout)['streams'][0]
    fps = float(Fraction(stream['avg_frame_rate']))
    if fps <= 0 or not math.isfinite(fps):
        raise ValueError('invalid average fps')
    frames = int(stream['nb_frames'])
    if frames < 1:
        raise ValueError('invalid frame count')
    duration = float(stream['duration'])
    # Metadata-only screen. Actual presentation timestamps and pose are tested separately.
    span = (frames - 1) / fps
    return {'duration': duration, 'estimated_span': span, 'frame_count': frames, 'fps': fps,
            'nominal_fps': stream['r_frame_rate'], 'start_time': stream.get('start_time'),
            'width': stream['width'], 'height': stream['height'],
            'rotation': (stream.get('side_data_list') or [{}])[0].get('rotation'),
            **{f'eligible_{length}': span + 1e-8 >= (length - 1) / 10 for length in LENGTHS}}


def probe_job(item):
    root, row = item
    try:
        measurements = probe(root / row['source_file'])
    except (ValueError, ZeroDivisionError, KeyError, IndexError, OSError, subprocess.SubprocessError) as error:
        measurements = {'probe_error': f'{type(error).__name__}: {error}'}
    return {'video': row['source_file'], 'label': row['archive_label'],
            'source_candidate': row['scenario_candidate'], **measurements}


def pose_job(item):
    import cv2
    import mediapipe as mp
    import numpy as np
    from ml.features import extract_keypoints, normalize_sequence, resample_keypoints, video_frame_timestamp

    root, row = item
    cv2.setNumThreads(1)
    path = root / row['video']
    times, raw_times, keypoints = [], [], {name: [] for name in ('lite', 'full', 'lite_rot180')}
    cfg = dict(static_image_mode=False, smooth_landmarks=True, min_detection_confidence=.5,
               min_tracking_confidence=.5)
    models = (('lite', 0), ('full', 1))
    if row['source_candidate']:
        models += (('lite_rot180', 0),)
    from contextlib import ExitStack
    camera = cv2.VideoCapture(str(path))
    try:
        if not camera.isOpened():
            raise ValueError(f'Cannot decode {path}')
        with ExitStack() as stack:
            pipelines = {name: stack.enter_context(mp.solutions.pose.Pose(model_complexity=complexity, **cfg))
                         for name, complexity in models}
            while True:
                ok, frame = camera.read()
                if not ok:
                    break
                raw_ms = camera.get(cv2.CAP_PROP_POS_MSEC)
                raw_times.append(raw_ms)
                times.append(video_frame_timestamp(raw_ms, row['fps'], times[-1] if times else None))
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                for name, pipeline in pipelines.items():
                    image = cv2.rotate(rgb, cv2.ROTATE_180) if name == 'lite_rot180' else rgb
                    detected = pipeline.process(image)
                    keypoints[name].append(extract_keypoints(detected.pose_landmarks))
    finally:
        camera.release()
    if not times:
        raise ValueError(f'No decoded frames: {path}')
    info = {}
    for name, rows in keypoints.items():
        if not rows:
            continue
        array = np.asarray(rows)
        sampled = resample_keypoints(times, array)
        valid = normalize_sequence(sampled)[:, 2::3].any(axis=1).astype(int)
        counts = {str(n): int(np.count_nonzero(np.convolve(valid, np.ones(n, dtype=int), 'valid') == n))
                  if len(valid) >= n else 0 for n in LENGTHS}
        signal = np.linalg.norm(np.diff(array[:, [11, 12], :2].mean(axis=1), axis=0), axis=1)
        dt = np.diff(times)
        visible = (array[:, [11, 12], 2] >= .3).all(axis=1)
        usable = visible[:-1] & visible[1:] & (dt <= .25) & np.isfinite(signal)
        peak = None
        if name == 'lite' and row['label'] == 'Fall' and usable.any():
            index = int(np.argmax(np.where(usable, signal / dt, -1)))
            peak = {'start': max(times[0], times[index] - .5), 'end': min(times[-1], times[index + 1] + .5),
                    'status': 'UNVERIFIED_MOTION_PROPOSAL'}
        info[name] = {'missing_frames': int((array[..., 2] == 0).all(axis=1).sum()),
                      'low_visibility_points': int((array[..., 2] < .3).sum()),
                      'nonfinite_values': int((~np.isfinite(array)).sum()),
                      'valid_grid': int(valid.sum()), 'grid_samples': len(valid), 'windows': counts,
                      'motion_proposal': peak}
    return {**row, 'decoded_frames': len(times), 'observed_span': times[-1] - times[0],
            'raw_bad_timestamp_steps': sum(not (math.isfinite(b) and b > a) for a, b in zip(raw_times, raw_times[1:])),
            'pose': info}


def select_sample(rows, review):
    by_path = {r['video']: r for r in rows if 'probe_error' not in r}
    primary = [by_path[path] for path in review if path in by_path]
    candidates = {}
    for row in rows:
        if 'probe_error' in row or row['source_candidate'] or row['fps'] <= 0:
            continue
        n = sum(row[f'eligible_{length}'] for length in LENGTHS)
        candidates.setdefault((row['label'], n), []).append(row)
    rng = random.Random(42)
    return primary + [row for key in sorted(candidates)
                      for row in rng.sample(candidates[key], min(2, len(candidates[key])))]


def review_queue(directory, metadata, measurements):
    from collections import defaultdict

    with (directory / 'source-groups-mcfd-audit.csv').open(newline='') as stream:
        lineage = {row['source_file']: row for row in csv.DictReader(stream)}
    by_clip = {row['video']: row for row in measurements}
    priority, remainder = defaultdict(list), defaultdict(list)
    hashes = set()
    scenarios = set()
    for row in sorted(metadata, key=lambda item: (item['video'] not in by_clip, item['video'])):
        if not row.get('eligible_30'):
            continue
        path = row['video']
        evidence = lineage[path]
        checksum = evidence['file_sha256']
        scenario = row['source_candidate']
        measured = by_clip.get(path)
        count = measured['pose']['lite']['windows']['30'] if measured else None
        if checksum in hashes or scenario in scenarios or (measured and count == 0):
            continue
        if evidence['same_stem_count'] != '1':
            continue
        hashes.add(checksum)
        if scenario:
            scenarios.add(scenario)
        review = {'video_id': evidence['video_id'], 'source_file': path, 'sha256': checksum,
                  'archive_label': row['label'], 'source_candidate': scenario, 'duration_seconds': row['duration'],
                  'fps': row['fps'], 'width': row['width'], 'height': row['height'],
                  'lite_30_windows': count if count is not None else '',
                  'trust_level': 'UNVERIFIED', 'split': '', 'verified_source_group': '',
                  'verified_upstream': '', 'verified_action': '', 'annotation_status': 'PENDING_REVIEW'}
        if measured:
            priority[row['label']].append(review)
        else:
            band = 'under4' if row['duration'] < 4 else '4to5' if row['duration'] < 5 else '5plus'
            resolution = 'square' if row['width']/row['height'] < 1.2 else 'wide'
            remainder[row['label'], band, resolution].append(review)
    rng = random.Random(42)
    for rows in remainder.values():
        rng.shuffle(rows)
    selected = []
    for label in ('Fall', 'No_Fall'):
        pool = [batch for key, batch in sorted(remainder.items()) if key[0] == label]
        chosen = priority[label].copy()
        while len(chosen) < 60 and any(pool):
            for batch in pool:
                if batch and len(chosen) < 60:
                    chosen.append(batch.pop())
        selected.extend(chosen)
    with (directory / 'recovery-review-queue.csv').open('x', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(selected[0]))
        writer.writeheader()
        writer.writerows(selected)
    proposals = {}
    for row in measurements:
        suggestion = row['pose']['lite']['motion_proposal']
        if suggestion:
            checksum = lineage[row['video']]['file_sha256']
            proposals[checksum] = {**suggestion, 'video_sha256': checksum, 'source_file': row['video']}
    with (directory / 'recovery-motion-proposals.json').open('x', encoding='utf-8') as stream:
        json.dump({'schema': 'annha-motion-proposals-v1', 'proposals': list(proposals.values())},
                  stream, indent=2, allow_nan=False)
    print('Review candidates',dict(Counter(item['archive_label'] for item in selected)),
          'pose-tested',sum(item['lite_30_windows'] != '' for item in selected),'proposals',len(proposals))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('mode', choices=('probe', 'pose', 'review'))
    parser.add_argument('--workers', type=int, default=6)
    args = parser.parse_args()
    directory = args.directory
    root = directory / 'raw-payutch-v1'
    probe_file = directory / 'recovery-video-metadata.json'
    pose_file = directory / 'recovery-paired-pose.json'
    if args.mode == 'review':
        queue = directory / 'recovery-review-queue.csv'
        proposals = directory / 'recovery-motion-proposals.json'
        if queue.exists() or proposals.exists():
            raise FileExistsError('Recovery review output already exists')
        review_queue(directory, json.loads(probe_file.read_text()), json.loads(pose_file.read_text()))
        return
    output = probe_file if args.mode == 'probe' else pose_file
    if output.exists():
        raise FileExistsError(output)
    if args.mode == 'probe':
        with (directory / 'source-groups-mcfd-audit.csv').open(newline='') as stream:
            inputs = list(csv.DictReader(stream))
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            result = list(pool.map(probe_job, ((root, item) for item in inputs)))
    else:
        with (directory / 'mcfd-review-queue.csv').open(newline='') as stream:
            review = [r['source_file'] for r in csv.DictReader(stream) if r['review_status'] == 'PENDING_REVIEW']
        inputs = select_sample(json.loads(probe_file.read_text()), review)
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            result = list(pool.map(pose_job, ((root, item) for item in inputs)))
    with output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
    print(f'{args.mode}: {len(result)} videos', output)


if __name__ == '__main__':
    main()
