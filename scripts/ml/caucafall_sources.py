#!/usr/bin/env python3
"""Prepare CAUCAFall v5 AVI recordings with published OmniFall temporal labels."""
import argparse
import csv
import hashlib
import json
import math
import sys
from collections import defaultdict
from pathlib import Path


ANNOTATION_SHA256 = '7283def2b2aa80f4b6004ce59262114ef9e4dca22601f8f0afa37983d1286c9e'
ACTION_STEMS = {
    'Fall backwards': 'FallBackwards',
    'Fall forward': 'FallForward',
    'Fall left': 'FallLeft',
    'Fall right': 'FallRight',
    'Fall sitting': 'FallSitting',
    'Hop': 'Hop',
    'Kneel': 'Kneel',
    'Pick up object': 'Pickupobject',
    'Sit down': 'SitDown',
    'Walk': 'Walk',
}


def annotation_for(rows, action, subject, last_timestamp, frame_period):
    if not rows or any((row['dataset'], row['subject'], row['cam']) !=
                       ('caucafall', subject, '1') for row in rows):
        raise ValueError('Subject or camera disagrees with published annotation')
    spans = sorted((float(row['start']), float(row['end']), int(row['label'])) for row in rows)
    if any(not (math.isfinite(a) and math.isfinite(b) and 0 <= a < b and 0 <= label <= 9)
           for a, b, label in spans):
        raise ValueError('Invalid OmniFall interval')
    if (spans[0][0] > frame_period or abs(spans[-1][1] - last_timestamp) > frame_period + .01
            or any(abs(right[0] - left[1]) > .01 for left, right in zip(spans, spans[1:]))):
        raise ValueError('Published timeline differs from AVI duration or has a gap/overlap')
    falls = [(a, b) for a, b, label in spans if label == 1]
    if action.startswith('Fall '):
        if len(falls) != 1 or falls[0][1] > last_timestamp:
            raise ValueError('Expected one observable, fully bounded Fall transition')
        return 'fall', *falls[0]
    if falls or any(label == 2 for _, _, label in spans):
        raise ValueError('ADL disagrees with OmniFall fall/fallen labels')
    return 'no_fall', None, None


def collect(root, evidence):
    annotations = root / 'caucafall-omnifall.csv'
    if hashlib.sha256(annotations.read_bytes()).hexdigest() != ANNOTATION_SHA256:
        raise ValueError('OmniFall annotation checksum differs from the reviewed copy')
    groups = defaultdict(list)
    with annotations.open(newline='', encoding='utf-8') as stream:
        for row in csv.DictReader(stream):
            groups[Path(row['path']).name.casefold()].append(row)

    sources, rejected = [], []
    entries = json.loads(evidence.read_text(encoding='utf-8'))
    for entry in entries:
        try:
            if 'error' in entry:
                raise ValueError(entry['error'])
            subject, action = str(entry['subject']), entry['action']
            name = ACTION_STEMS[action] + 'S' + subject
            if entry['name'].casefold() != name.casefold():
                raise ValueError('AVI name disagrees with publisher folder and subject')
            avi = root / 'media' / f'{entry["name"]}.avi'
            poses = root / 'pose' / f'{avi.stem}.csv'
            with avi.open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != entry['sha256']:
                    raise ValueError('AVI checksum disagrees with publisher')
            with poses.open(newline='', encoding='utf-8') as stream:
                timestamps = [float(row['Timestamp']) for row in csv.DictReader(stream)]
            meta = json.loads(poses.with_suffix('.schema.json').read_text(encoding='utf-8'))
            if not timestamps:
                raise ValueError('No pose timestamps')
            label, start, end = annotation_for(groups.get(name.casefold(), []), action, subject,
                                               timestamps[-1], 1 / meta['native_fps'])
            sources.append(dict(
                video_id=f'caucafall:{name}', source_file=str(avi), keypoint_csv=str(poses),
                label=label, source_dataset='caucafall', subject_id=subject, source_group=name,
                scene_id=action, camera_id='1', event_start=start, event_end=end,
                annotation_version=f'OmniFall CAUCAFall SHA-256 {ANNOTATION_SHA256}',
                provenance_status='VERIFIED', source_ref=entry['url'],
                expected_video_sha256=entry['sha256'], group_status='VERIFIED',
                group_evidence='CAUCAFall v5 publisher subject/action folder agrees with OmniFall subject/video',
                annotation_status='UPSTREAM_VERIFIED',
                annotation_source='OmniFall temporal segment label 1 and CAUCAFall v5 recording activity',
                reviewer='PR-03 source and timeline consistency checks'))
        except (KeyError, ValueError, OSError) as exc:
            rejected.append({'subject': entry['subject'], 'action': entry['action'], 'reason': str(exc)})
    return sources, rejected



def pilot_development_sources(manifest):
    """Carry forward only unique development recordings from the pilot."""
    keys = ('video_id', 'source_file', 'keypoint_csv', 'source_dataset', 'subject_id',
            'source_group', 'scene_id', 'camera_id', 'event_start', 'event_end',
            'annotation_version', 'provenance_status', 'source_ref', 'expected_video_sha256',
            'group_status', 'group_evidence', 'annotation_status', 'annotation_source',
            'reviewer', 'cross_source_group', 'cross_source_evidence')
    return [dict({key: row[key] for key in keys}, label='fall' if row['label'] else 'no_fall')
            for row in manifest['sources'] if row['split'] in ('train', 'val') and not row['duplicate_of']]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--evidence', type=Path, help='Publisher media provenance JSON')
    parser.add_argument('--pilot', type=Path, help='Verified pilot dataset directory')
    args = parser.parse_args()
    root = args.root.resolve()
    sources, rejected = collect(root, args.evidence or root / 'media-evidence.json')
    if not sources:
        raise ValueError('No sources passed provenance and timeline checks')
    if args.pilot is not None:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'fall_detect'))
        from ml.integrity import verify_dataset
        sources.extend(pilot_development_sources(verify_dataset(args.pilot)))
    fields = list(dict.fromkeys(key for row in sources for key in row))
    with (root / 'sources-official.csv').open('x', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(sources)
    with (root / 'source-exclusions.json').open('x', encoding='utf-8') as stream:
        json.dump(rejected, stream, indent=2)
    print(f'Submitted {len(sources)} recordings, excluded {len(rejected)}')


if __name__ == '__main__':
    main()
