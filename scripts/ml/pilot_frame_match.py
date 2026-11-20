#!/usr/bin/env python3
"""Measure contiguous frame correspondence for a trimmed clip and upstream video."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np


def frames(path):
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS)
    descriptors, timestamps = [], []
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            value = cv2.resize(gray, (48, 32), interpolation=cv2.INTER_AREA).astype(np.float32).ravel()
            value -= value.mean()
            norm = np.linalg.norm(value)
            descriptors.append(value / max(norm, 1e-8))
            timestamps.append(cap.get(cv2.CAP_PROP_POS_MSEC) / 1000)
    finally:
        cap.release()
    if not descriptors or not np.isfinite(fps) or fps <= 0:
        raise ValueError(f'Could not decode frames and FPS from {path}')
    return np.asarray(descriptors), np.asarray(timestamps), fps


def align(clip, upstream, strides):
    # Cosine error over every frame rewards both a stable background and matching movement.
    error = np.clip(1-clip @ upstream.T, 0, 2)
    n, m = error.shape
    indices = np.arange(n)
    candidates = []
    for stride in strides:
        length = m - (n-1)*stride
        if length <= 0:
            continue
        errors = np.mean(error[indices[:, None], indices[:, None]*stride + np.arange(length)], axis=0)
        for offset in np.argsort(errors)[:min(24, length)]:
            candidates.append((float(errors[offset]), stride, int(offset)))
    if not candidates:
        raise ValueError('No full contiguous mapping fits upstream')
    candidates.sort()
    score, stride, offset = candidates[0]
    # Compare to a distinct temporal mapping, excluding adjacent frames of the same cut.
    alternative = next((item for item in candidates if item[1]!=stride or abs(item[2]-offset)>=4), None)
    mapped = offset+stride*indices
    matched = error[indices, mapped]
    local_offsets = []
    for i, source_index in enumerate(mapped):
        lo, hi = max(0,source_index-4), min(m,source_index+5)
        local_offsets.append(lo+int(np.argmin(error[i,lo:hi]))-int(source_index))
    return {'stride':stride,'offset_zero_based':offset,'mean_cosine_error':score,
            'p95_cosine_error':float(np.quantile(matched,.95)),
            'next_distinct_candidate':alternative,
            'p95_local_best_frame_displacement':float(np.quantile(np.abs(local_offsets),.95)),
            'local_best_frame_displacement_histogram': {str(i):local_offsets.count(i) for i in sorted(set(local_offsets))},
            'top_candidates':candidates[:12]}


def map_segments(mapping, upstream_fps, clip_frame_count, metadata, scenario, camera):
    """Map corrected inclusive frame ranges; never join disjoint transitions."""
    alternative = mapping['next_distinct_candidate']
    error = mapping['mean_cosine_error']
    if (not alternative or error > .002 or alternative[0] < 4 * max(error, 1e-8)
            or mapping['p95_local_best_frame_displacement'] > 1):
        raise ValueError('Frame correspondence too ambiguous to transfer annotation')
    with (metadata / 'camera_delay_corrected.csv').open(newline='', encoding='utf-8') as stream:
        delays = [int(row['delay_frames']) for row in csv.DictReader(stream)
                  if int(row['scenario_id']) == scenario and int(row['camera_id']) == camera]
    if len(delays) != 1:
        raise ValueError('Expected one matching camera calibration')
    offset = mapping['offset_zero_based']
    last = offset + (clip_frame_count - 1) * mapping['stride']
    result = []
    with (metadata / 'segments_corrected.csv').open(newline='', encoding='utf-8') as stream:
        for row in csv.DictReader(stream):
            if int(row['scenario_id']) != scenario:
                continue
            start = int(row['start_frame']) + delays[0]
            end = int(row['end_frame']) + delays[0]
            if end < offset or start > last:
                continue
            result.append({'position_code': int(row['position_code']),
                           'aligned_frames': [int(row['start_frame']), int(row['end_frame'])],
                           'camera_frames': [start, end],
                           'clip_seconds': [(max(start, offset)-offset)/upstream_fps,
                                            (min(end, last)-offset)/upstream_fps],
                           'fully_visible_in_clip': start >= offset and end <= last})
    return {'scenario': scenario, 'camera': camera, 'delay_frames': delays[0],
            'boundary_quantization_seconds': 1 / upstream_fps, 'segments': result}


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('clip',type=Path)
    parser.add_argument('upstream',type=Path)
    parser.add_argument('--metadata',type=Path)
    parser.add_argument('--scenario',type=int)
    parser.add_argument('--camera',type=int)
    args=parser.parse_args()
    if args.metadata and (args.scenario is None or args.camera is None):
        parser.error('--metadata requires --scenario and --camera')
    cv2.setNumThreads(2)
    clip, times, clip_fps = frames(args.clip)
    upstream, _, upstream_fps = frames(args.upstream)
    options=sorted({1, max(1,round(upstream_fps/clip_fps))})
    mapping=align(clip,upstream,options)
    if args.metadata:
        if abs(mapping['stride'] * clip_fps-upstream_fps)>1e-6:
            raise ValueError('Detected frame stride does not agree with the playback time bases')
        mapping['annotation_mapping'] = map_segments(mapping,upstream_fps,len(clip),args.metadata,args.scenario,args.camera)
    print(json.dumps({**mapping,'clip_sha256':sha256(args.clip),'upstream_sha256':sha256(args.upstream),
                      'clip_frames':len(clip),'upstream_frames':len(upstream),
                      'clip_fps':clip_fps,'upstream_fps':upstream_fps,
                      'clip_timestamp_range_s':[float(times[0]),float(times[-1])]},indent=2))


if __name__=='__main__':
    main()
