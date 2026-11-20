#!/usr/bin/env python3
"""Inventory the local Kaggle v1 archive and optionally fingerprint video content."""
import argparse
from collections import Counter, defaultdict
import csv
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'fall_detect'))
from ml.integrity import decoded_video_digest


def inventory(root, manifest, output, decoded_limit):
    entries = {}
    for line in manifest.read_text(encoding='utf-8').splitlines():
        checksum, path = line.split('  ', 1)
        if not re.fullmatch('[a-f0-9]{64}', checksum) or path in entries:
            raise ValueError(f'Invalid or duplicate manifest entry: {path}')
        entries[path] = checksum
    video_paths = sorted(p for p in entries if '/Raw_Video/' in p)
    records = []
    stems = Counter(Path(p).stem.casefold() for p in video_paths)
    byte_counts = Counter(entries[p] for p in video_paths)
    candidates = [p for p in video_paths if re.fullmatch(r'S_F\d+_cam[1-8]', Path(p).stem)]
    decode_paths = set(candidates[:decoded_limit] if decoded_limit is not None else video_paths)
    decoded_groups = defaultdict(list)
    for path in video_paths:
        video = root / path
        if not video.is_file():
            raise FileNotFoundError(video)
        category = Path(path).parts[0]
        stem = Path(path).stem
        legacy_csv = f'{category}/Keypoints_CSV/{stem}_keypoints.csv'
        if legacy_csv not in entries:
            legacy_csv = ''
        scenario = re.fullmatch(r'S_F(\d+)_cam([1-8])', stem)
        content = ''
        decode_status = 'NOT_CHECKED'
        if path in decode_paths:
            try:
                content = decoded_video_digest(video)
                decoded_groups[content].append(path)
                decode_status = 'CHECKED'
            except (OSError, ValueError, subprocess.SubprocessError):
                decode_status = 'ERROR'
        records.append({
            'video_id': f'payutch-v1:{path}', 'source_file': path, 'file_sha256': entries[path],
            'archive_label': category, 'legacy_keypoints': legacy_csv,
            'legacy_csv_sha256': entries.get(legacy_csv, ''),
            'byte_duplicate_count': byte_counts[entries[path]], 'decoded_sha256': content,
            'decode_status': decode_status, 'same_stem_count': stems[stem.casefold()],
            'scenario_candidate': f'mcfd:{int(scenario[1])}' if scenario else '',
            'camera_candidate': scenario[2] if scenario else '',
            'subject_id': '', 'source_group': '', 'lineage_status': 'UNVERIFIED',
            'eligible_for_test': 'false', 'fall_start_time': '', 'fall_end_time': '',
            'annotation_source': '', 'annotation_confidence': '',
            'annotation_status': 'UNVERIFIED' if category == 'Fall' else 'NOT_APPLICABLE',
        })
    for row in records:
        row['decoded_duplicate_count'] = len(decoded_groups[row['decoded_sha256']]) if row['decoded_sha256'] else ''
        if row['byte_duplicate_count'] > 1:
            row['conservative_group'] = 'sha256:' + row['file_sha256']
        elif row['decoded_duplicate_count'] and row['decoded_duplicate_count'] > 1:
            row['conservative_group'] = 'decoded:' + row['decoded_sha256']
        else:
            row['conservative_group'] = ''
    with output.open('x', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    print('videos',len(records),'categories',dict(Counter(r['archive_label'] for r in records)),
          'csv_pairs',sum(bool(r['legacy_keypoints']) for r in records),'byte_groups',sum(n>1 for n in byte_counts.values()),
          'byte_duplicate_members',sum(n for n in byte_counts.values() if n>1),
          'scenario_candidates',len(candidates),'scenario_groups',len({r['scenario_candidate'] for r in records if r['scenario_candidate']}),
          'decoded',sum(r['decode_status']=='CHECKED' for r in records),'decoded_groups',sum(len(g)>1 for g in decoded_groups.values()))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('raw_root', type=Path)
    parser.add_argument('sha256_manifest', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--decoded-limit', type=int, default=None,
                        help='Fingerprint only this many Montréal filename candidates. Default checks every video.')
    args = parser.parse_args()
    if args.decoded_limit is not None and args.decoded_limit < 0:
        parser.error('--decoded-limit must be non-negative')
    inventory(args.raw_root, args.sha256_manifest, args.output, args.decoded_limit)
