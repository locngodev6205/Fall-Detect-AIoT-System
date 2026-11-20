#!/usr/bin/env python3
"""Audit local artifacts and build or verify an isolated versioned dataset."""
import argparse
from collections import Counter, defaultdict
import csv
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'fall_detect'))
from ml.dataset import read_keypoints_csv
from ml.features import SPEC
from ml.integrity import approve_subset, build_dataset, decoded_video_digest, digest, preflight_sources, read_sources, verify_dataset

VIDEO_SUFFIXES = {'.mp4', '.avi', '.mov', '.mkv', '.webm'}
SKIP_DIRS = {'.git', 'node_modules', 'venv', '.venv', '__pycache__', '.secrets'}


def error_report(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    split_counts = Counter()
    names = defaultdict(set)
    prefixes = defaultdict(set)
    for row in rows:
        name, split = row['Tên tệp'], row['Tập dữ liệu']
        split_counts[split + ' / ' + row['Nhãn thực tế']] += 1
        names[name].add(split)
        if '_keypoints_' in name:
            prefixes[name.split('_keypoints_', 1)[0]].add(split)
    return {'rows': len(rows), 'counts': dict(split_counts), 'distinct_windows': len(names),
            'shared_window_names': {name: sorted(splits) for name, splits in names.items() if len(splits) > 1},
            'distinct_filename_prefixes': len(prefixes),
            'shared_prefix_candidates': {name: sorted(splits) for name, splits in prefixes.items() if len(splits) > 1}}


def inventory(root):
    files = []
    duplicates = defaultdict(list)
    for directory, children, names in os.walk(root):
        children[:] = sorted(set(children) - SKIP_DIRS)
        for name in sorted(names):
            path = Path(directory) / name
            suffix = path.suffix.lower()
            if suffix not in VIDEO_SUFFIXES | {'.csv', '.npy'} and not (
                name.endswith('.schema.json') or name in ('manifest.json', 'feature_schema.json')
            ):
                continue
            item = {'path': path.relative_to(root).as_posix(), 'sha256': digest(path), 'kind': suffix}
            duplicates[(suffix, item['sha256'])].append(item['path'])
            try:
                if suffix in VIDEO_SUFFIXES:
                    result = subprocess.run(
                        ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                         'stream=width,height,avg_frame_rate,nb_frames', '-of', 'json', str(path)],
                        check=True, capture_output=True, text=True, timeout=60,
                    )
                    item.update(json.loads(result.stdout)['streams'][0])
                    item['decoded_sha256'] = decoded_video_digest(path)
                    duplicates[('video_decoded', item['decoded_sha256'])].append(item['path'])
                    parts = {part.lower() for part in path.parts}
                    item['label_hint'] = 'no_fall' if 'no_fall' in parts else 'fall' if 'fall' in parts else None
                elif suffix == '.npy':
                    array = np.load(path, mmap_mode='r', allow_pickle=False)
                    item.update(shape=list(array.shape), dtype=str(array.dtype), finite=bool(np.isfinite(array).all()))
                    if array.shape != (SPEC.window_size, 51) or array.dtype != np.float32 or not item['finite']:
                        item['issue'] = 'Expected finite float32 (30, 51)'
                elif path.name == 'error_analysis_report.csv':
                    item['error_report'] = error_report(path)
                elif suffix == '.csv' and path.with_suffix('.schema.json').is_file():
                    timestamps, points = read_keypoints_csv(path)
                    item.update(frames=len(timestamps), missing_keypoints=int((points[..., 2] < SPEC.minimum_visibility).sum()),
                                nonfinite_values=int((~np.isfinite(points)).sum()),
                                invalid_timestamp_steps=int((np.diff(timestamps) <= 0).sum()),
                                nonfinite_timestamps=int((~np.isfinite(timestamps)).sum()),
                                gap_count=int((np.diff(timestamps) > SPEC.max_gap_s).sum()))
                    if item['nonfinite_values'] or item['invalid_timestamp_steps'] or item['nonfinite_timestamps'] or not len(timestamps):
                        item['issue'] = 'Invalid keypoint values or timestamps'
                elif suffix == '.csv':
                    item['issue'] = 'CSV is not a versioned keypoint source'
            except (OSError, ValueError, KeyError, IndexError, subprocess.SubprocessError) as exc:
                item['issue'] = str(exc)
            files.append(item)
    return {'files': files,
            'duplicate_groups': [{'check': kind, 'sha256': checksum, 'paths': paths}
                                 for (kind, checksum), paths in duplicates.items() if len(paths) > 1]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    audit = commands.add_parser('audit')
    audit.add_argument('root', type=Path)
    build = commands.add_parser('build')
    build.add_argument('sources', type=Path)
    build.add_argument('destination', type=Path)
    build.add_argument('--version', required=True)
    build.add_argument('--seed', type=int, required=True)
    build.add_argument('--stride', type=int, default=3)
    build.add_argument('--mode', choices=('official', 'research'), default='official')
    build.add_argument('--preflight-report', type=Path)
    preflight = commands.add_parser('preflight')
    preflight.add_argument('sources', type=Path)
    preflight.add_argument('--mode', choices=('official', 'research'), default='official')
    preflight.add_argument('--stride', type=int, default=3)
    verify = commands.add_parser('verify')
    verify.add_argument('dataset', type=Path)
    verify.add_argument('--verify-sources', action='store_true')
    approve = commands.add_parser('approve-subset')
    approve.add_argument('dataset', type=Path)
    approve.add_argument('--sha256', required=True)
    approve.add_argument('--reviewer', required=True)
    approve.add_argument('--evidence', required=True)
    options = parser.parse_args()
    try:
        if options.command == 'audit':
            output = inventory(options.root.resolve(strict=True))
        elif options.command == 'approve-subset':
            approve_subset(options.dataset, expected_sha256=options.sha256,
                           reviewer=options.reviewer, evidence=options.evidence)
            output = {'scope':'G3_SUBSET','dataset_sha256':options.sha256}
        elif options.command == 'preflight':
            admitted, rejected, _ = preflight_sources(read_sources(options.sources), mode=options.mode, stride=options.stride)
            output = {'mode': options.mode, 'eligible': [row['video_id'] for row in admitted], 'rejected': rejected}
        else:
            if options.command == 'build':
                manifest = build_dataset(read_sources(options.sources), options.destination, version=options.version,
                                         seed=options.seed, stride=options.stride, mode=options.mode,
                                         preflight_report=options.preflight_report)
            else:
                manifest = verify_dataset(options.dataset, verify_sources=options.verify_sources)
            groups = Counter((item['split'], item['label']) for item in manifest['sources'] if not item['duplicate_of'])
            windows = Counter((item['split'], item['label']) for item in manifest['windows'])
            output = {'dataset_sha256': manifest['dataset_sha256'], 'mode': manifest['mode'],
                      'g3_eligible': manifest['g3_eligible'], 'g3_status': manifest['g3_status'], 'preflight': manifest['preflight'],
                      'totals': {split: {label: {'videos': groups[split, index], 'windows': windows[split, index]}
                                         for index, label in enumerate(('no_fall', 'fall'))}
                                 for split in ('train', 'val', 'test')}}
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        parser.exit(1, f'Dataset error: {exc}\n')
    print(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
