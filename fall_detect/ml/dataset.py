"""Versioned CSV interchange and sliding windows for canonical skeleton training."""
import csv
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path

import numpy as np

from .features import EMPTY, NUM_FEATURES, SHAPE, SPEC, extract_keypoints, normalize_sequence, resample_keypoints, video_frame_timestamp

FIELDS = ('Frame', 'Timestamp', 'Keypoint', 'X', 'Y', 'Confidence')


def write_keypoints_csv(path, timestamps, poses, *, source, fps, image_size, mediapipe_version, source_sha256=None):
    with Path(path).open('x', encoding='utf-8', newline='') as output:
        writer = csv.writer(output)
        writer.writerow(FIELDS)
        for index, (stamp, pose) in enumerate(zip(timestamps, poses, strict=True), 1):
            for name, point in zip(SPEC.keypoints, pose, strict=True):
                writer.writerow((index, stamp, name, *point))
    with Path(path).with_suffix('.schema.json').open('x', encoding='utf-8') as metadata:
        json.dump({'feature_schema_version': SPEC.schema_version, 'source': str(source),
                   'source_sha256': source_sha256, 'native_fps': fps, 'width': image_size[0], 'height': image_size[1],
                   'mediapipe_version': mediapipe_version, 'extractor_version': SPEC.schema_version,
                   'coordinate_space': SPEC.coordinate_space}, metadata, indent=2)


def read_keypoints_csv(path):
    metadata = json.loads(Path(path).with_suffix('.schema.json').read_text(encoding='utf-8'))
    if metadata.get('feature_schema_version') != SPEC.schema_version or metadata.get('coordinate_space') != SPEC.coordinate_space:
        raise ValueError('CSV does not declare the canonical normalized pose schema')
    indices = {name: index for index, name in enumerate(SPEC.keypoints)}
    frames = {}
    used = set()
    with Path(path).open(encoding='utf-8', newline='') as stream:
        for row in csv.DictReader(stream):
            frame = int(row['Frame'])
            stamp = float(row['Timestamp'])
            joint = indices[row['Keypoint']]
            previous_stamp, points = frames.setdefault(frame, (stamp, EMPTY.copy()))
            if stamp != previous_stamp or (frame, joint) in used:
                raise ValueError('Conflicting or duplicate keypoint row')
            used.add((frame, joint))
            points[joint] = [float(row[key]) for key in ('X', 'Y', 'Confidence')]
    ordered = [frames[key] for key in sorted(frames)]
    return np.array([t for t, _ in ordered]), np.array([p for _, p in ordered], dtype=np.float32).reshape((-1, *SHAPE))


def create_windows(path, window_size, stride):
    if window_size < 1 or stride < 1:
        raise ValueError('Window and stride must be positive')
    timestamps, rows = read_keypoints_csv(path)
    sampled = resample_keypoints(timestamps, rows).reshape((-1, NUM_FEATURES))
    valid = normalize_sequence(sampled)[:, 2::3].any(axis=1)
    return [sampled[i:i + window_size].copy() for i in range(0, len(sampled) - window_size + 1, stride)
            if valid[i:i + window_size].all()]


def jitter_coordinates(sequence, rng, *, spatial_jitter=True, confidence_noise=False):
    result = sequence.copy()
    coordinates = result.reshape((-1, *SHAPE))
    present = coordinates[..., 2] > 0
    if spatial_jitter:
        coordinates[..., :2] += rng.normal(0, .01, coordinates[..., :2].shape) * present[..., None]
    if confidence_noise:
        coordinates[..., 2] = np.clip(coordinates[..., 2] + rng.normal(0, .05, present.shape) * present, 0, 1)
    return result


def extract_video(video, output):
    import cv2
    import mediapipe as mp

    camera = cv2.VideoCapture(str(video))
    try:
        fps = camera.get(cv2.CAP_PROP_FPS)
        if not camera.isOpened() or not np.isfinite(fps) or fps <= 0:
            raise ValueError(f'Cannot read video FPS: {video}')
        timestamps, poses = [], []
        with mp.solutions.pose.Pose(model_complexity=0) as pose:
            while True:
                ok, frame = camera.read()
                if not ok:
                    break
                timestamp = video_frame_timestamp(camera.get(cv2.CAP_PROP_POS_MSEC), fps,
                                                  timestamps[-1] if timestamps else None)
                timestamps.append(timestamp)
                size = (frame.shape[1], frame.shape[0])
                results = pose.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                poses.append(extract_keypoints(results.pose_landmarks))
        if not poses:
            raise ValueError(f'Video has no frames: {video}')
        with Path(video).open('rb') as stream:
            source_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
        write_keypoints_csv(output, timestamps, poses, source=video, fps=fps, image_size=size,
                            mediapipe_version=mp.__version__, source_sha256=source_hash)
    finally:
        camera.release()


def generate_sequences(dataset, output, *, window_size, stride):
    output.mkdir(parents=True)
    # Keep the input video identity in filenames for downstream grouped splitting.
    manifest = {'feature_schema_version': SPEC.schema_version,
                'feature_spec': asdict(replace(SPEC, window_size=window_size)), 'sequences': {}}
    for category in ('Fall', 'No_Fall'):
        destination = output / category.lower()
        destination.mkdir()
        for path in sorted((dataset / category / 'Keypoints_CSV_v2').glob('*.csv')):
            metadata = json.loads(path.with_suffix('.schema.json').read_text(encoding='utf-8'))
            source_id = metadata.get('source_sha256') or path.relative_to(dataset).as_posix()
            for index, sequence in enumerate(create_windows(path, window_size, stride)):
                target = destination / f'{path.stem}_seq_{index:04d}.npy'
                np.save(target, sequence, allow_pickle=False)
                manifest['sequences'][target.relative_to(output).as_posix()] = source_id
    (output / 'feature_schema.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')


def extract_dataset(dataset):
    for category in ('Fall', 'No_Fall'):
        source = dataset / category / 'Raw_Video'
        if not source.is_dir():
            raise FileNotFoundError(source)
        destination = dataset / category / 'Keypoints_CSV_v2'
        destination.mkdir(exist_ok=True)
        for video in sorted(source.iterdir()):
            if video.is_file() and video.suffix.lower() in ('.mp4', '.avi', '.mov'):
                output = destination / f'{video.name}_keypoints.csv'
                if output.exists() and output.with_suffix('.schema.json').exists():
                    continue
                extract_video(video, output)


def dataset_cli(operation, window_size=SPEC.window_size):
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--canonical', action='store_true', required=True)
    parser.add_argument('--dataset', type=Path, default=Path('.'))
    if operation == 'sequence':
        parser.add_argument('--output', type=Path, required=True)
        parser.add_argument('--stride', type=int, default=3)
    options = parser.parse_args()
    if operation == 'extract':
        extract_dataset(options.dataset)
    else:
        generate_sequences(options.dataset, options.output, window_size=window_size, stride=options.stride)
