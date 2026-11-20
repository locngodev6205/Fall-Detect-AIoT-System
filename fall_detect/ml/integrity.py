"""Build and verify a reproducible, video-grouped PR-04 dataset."""
from collections import Counter
import csv
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import random
import re
import subprocess
from tempfile import TemporaryDirectory

import numpy as np

from .dataset import read_keypoints_csv
from .features import NUM_FEATURES, SPEC, normalize_sequence, resample_keypoints

SPLITS = ('train', 'val', 'test')
RATIOS = (.70, .15, .15)
SHAPE = (SPEC.window_size, NUM_FEATURES)
FALL_WINDOW_RULE = 'onset_and_min_overlap_v1'
ANNOTATION_STATUSES = {'HUMAN_VERIFIED', 'UPSTREAM_VERIFIED'}


@dataclass(frozen=True)
class Source:
    video_id: str
    video: Path
    keypoints: Path
    label: int
    source_dataset: str
    subject_id: str | None = None
    source_group: str | None = None
    event_start: float | None = None
    event_end: float | None = None
    decoded_sha256: str | None = None
    scene_id: str | None = None
    camera_id: str | None = None
    annotation_version: str | None = None
    provenance_status: str | None = None
    source_ref: str | None = None
    expected_video_sha256: str | None = None
    group_status: str | None = None
    group_evidence: str | None = None
    annotation_status: str | None = None
    annotation_source: str | None = None
    reviewer: str | None = None
    cross_source_group: str | None = None
    cross_source_evidence: str | None = None
    fingerprint: bool = False


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def decoded_video_digest(path):
    """Hash the decoded video track. Detects identical frames in another container."""
    result = subprocess.run(
        ['ffmpeg', '-nostdin', '-v', 'error', '-i', str(path), '-map', '0:v:0',
         '-fps_mode', 'passthrough', '-f', 'streamhash', '-hash', 'sha256', '-'],
        capture_output=True, text=True, check=True, timeout=1800,
    )
    match = re.fullmatch(r'0,v,SHA256=([a-f0-9]{64})', result.stdout.strip())
    if not match:
        raise ValueError(f'Could not fingerprint decoded video: {path}')
    return match[1]


def read_sources(path, *, fingerprint=True):
    path = Path(path)
    with path.open(encoding='utf-8-sig', newline='') as stream:
        for row in csv.DictReader(stream):
            video = (path.parent / row['source_file']).resolve()
            keypoints = (path.parent / row['keypoint_csv']).resolve()
            label = {'fall': 1, 'no_fall': 0}.get(row['label'].strip().lower())
            if label is None:
                raise ValueError(f"Invalid label for {row['video_id']}")
            optional = {key: row.get(key, '').strip() or None for key in
                        ('subject_id', 'source_group', 'scene_id', 'camera_id', 'annotation_version',
                         'provenance_status', 'source_ref', 'expected_video_sha256', 'group_status', 'group_evidence',
                         'annotation_status', 'annotation_source', 'reviewer', 'cross_source_group', 'cross_source_evidence')}
            event = {key: float(row[key]) if row.get(key, '').strip() else None
                     for key in ('event_start', 'event_end')}
            yield Source(row['video_id'].strip(), video, keypoints, label, row['source_dataset'].strip(),
                         fingerprint=fingerprint,
                         **optional, **event)


def _group_records(records):
    roots = {r['video_id']: r['video_id'] for r in records}
    identities = {}
    contents = {}

    def root(key):
        while roots[key] != key:
            roots[key] = roots[roots[key]]
            key = roots[key]
        return key

    def join(left, right):
        first, second = sorted((root(left), root(right)))
        roots[second] = first

    for item in records:
        video = item['video_id']
        duplicate = []
        for kind in ('video_sha256', 'decoded_sha256'):
            value = item[kind]
            if value:
                prior = contents.setdefault((kind, value), item)
                if prior['video_id'] != video:
                    if any(item[field] != prior[field] for field in ('label', 'event_start', 'event_end')):
                        raise ValueError(f'Conflicting annotations for duplicate videos: {prior["video_id"]}, {video}')
                    duplicate.append(prior['duplicate_of'] or prior['video_id'])
                    join(video, prior['video_id'])
        item['duplicate_of'] = min(duplicate, default=None)
        for kind in ('subject_id', 'source_group', 'cross_source_group'):
            value = item[kind]
            if value:
                scope = '' if kind == 'cross_source_group' else item['source_dataset']
                prior = identities.setdefault((kind, scope, value), video)
                join(video, prior)
    for item in records:
        item['group_id'] = root(item['video_id'])


def _split_records(records, seed, context=(), *, min_holdout_groups=1, train_only_sources=()):
    if type(min_holdout_groups) is not int or min_holdout_groups < 1:
        raise ValueError('Minimum holdout groups must be a positive integer')
    _group_records([*records, *context])
    groups = {}
    for item in records:
        counts = groups.setdefault(item['group_id'], np.zeros(2, dtype=np.int64))
        if not item['duplicate_of']:
            counts[item['label']] += 1
    keys = sorted(groups)
    train_only = {item['group_id'] for item in [*records, *context]
                  if item['source_dataset'] in train_only_sources}
    pinned = [index for index, key in enumerate(keys) if key in train_only]
    counts = np.array([groups[key] for key in keys])
    if len(keys) < 3 or (np.count_nonzero(counts, axis=0) < 3).any():
        raise ValueError('Each label needs at least three independent groups to cover train, val and test')
    minimum = np.array([1, min_holdout_groups, min_holdout_groups])[:, None]
    class_groups = counts > 0
    holdout_groups = class_groups.sum(axis=0) - class_groups[pinned].sum(axis=0)
    if ((class_groups.sum(axis=0) < minimum.sum()).any()
            or (holdout_groups < 2 * min_holdout_groups).any()):
        raise ValueError('Too few groups per label for the requested holdout minimum')
    rng = random.Random(seed)
    total = counts.sum(axis=0)
    target = np.asarray(RATIOS)[:, None] * total
    best = None
    total_groups = len(keys)
    for _ in range(4096):
        assignments = rng.choices(range(3), weights=RATIOS, k=total_groups)
        for index in pinned:
            assignments[index] = 0
        observed = np.zeros((3, 2), dtype=np.int64)
        np.add.at(observed, assignments, counts)
        if not observed.all():
            continue
        if min_holdout_groups > 1:
            observed_groups = np.zeros((3, 2), dtype=np.int64)
            np.add.at(observed_groups, assignments, class_groups)
            if (observed_groups < minimum).any():
                continue
        score = float((((observed - target) / total) ** 2).sum())
        candidate = (score, tuple(assignments))
        if best is None or candidate < best:
            best = candidate
    if best is None:
        raise ValueError('Could not find a split with both labels in every partition under group constraints')
    by_group = dict(zip(keys, best[1], strict=True))
    for item in records:
        item['split'] = SPLITS[by_group[item['group_id']]]
    return {r['video_id']: r for r in records}


def _validate_cross_source(item):
    if item['cross_source_group'] and (
        not item['cross_source_evidence'] or item['group_status'] != 'VERIFIED'
    ):
        raise ValueError(f'Verified cross-source group evidence required: {item["video_id"]}')


def _source_record(source):
    if not source.video_id or not source.source_dataset or source.label not in (0, 1):
        raise ValueError(f'Invalid source record: {source.video_id}')
    if source.decoded_sha256 and not re.fullmatch('[a-f0-9]{64}', source.decoded_sha256):
        raise ValueError(f'Invalid decoded SHA-256: {source.video_id}')
    if source.label == 1:
        start, end = source.event_start, source.event_end
        if start is None or end is None or not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end):
            raise ValueError(f'Fall annotation interval is required for {source.video_id}')
    elif source.event_start is not None or source.event_end is not None:
        raise ValueError(f'No Fall source has a Fall annotation: {source.video_id}')
    item = asdict(source)
    _validate_cross_source(item)
    item['video_sha256'] = digest(source.video)
    if source.expected_video_sha256 and source.expected_video_sha256 != item['video_sha256']:
        raise ValueError(f'Video checksum mismatch: {source.video_id}')
    if item.pop('fingerprint'):
        item['decoded_sha256'] = decoded_video_digest(source.video)
    item['source_file'] = str(item.pop('video'))
    item['keypoint_csv'] = str(item.pop('keypoints'))
    return item


def _ordered(sources):
    rows = sorted(sources, key=lambda row: row.video_id)
    if len({r.video_id for r in rows}) != len(rows):
        raise ValueError('Duplicate video ID in source records')
    return rows


def assign_splits(sources, *, seed):
    return _split_records([_source_record(row) for row in _ordered(sources)], seed)


def _provenance_errors(item):
    missing = []
    def present(key):
        return isinstance(item.get(key), str) and bool(item[key].strip())
    if (item['provenance_status'] != 'VERIFIED' or not present('source_ref')
            or not present('expected_video_sha256') or item['expected_video_sha256'] != item.get('video_sha256')):
        missing.append('provenance or verified video hash')
    if item['group_status'] != 'VERIFIED' or not present('source_group') or not present('group_evidence'):
        missing.append('source_group or lineage evidence')
    if item['annotation_status'] not in ANNOTATION_STATUSES or not present('annotation_source') or not present('reviewer'):
        missing.append('verified annotation, source or reviewer')
    return missing


def fall_window(timestamps, event_start, event_end):
    """Require onset, >= 0.3 s overlap, and at least three event grid samples.

    Require at least half the annotated duration, capped at 0.6 s. Durations
    shorter than 0.3 s cannot qualify with this conservative label contract.
    """
    times = np.asarray(timestamps)
    eps = 1e-8
    duration = event_end - event_start
    required = max(.3, min(.6, duration / 2))
    overlap = min(float(times[-1]), event_end) - max(float(times[0]), event_start)
    return bool(times[0] <= event_start + eps <= times[-1] + eps
                and overlap >= required - eps
                and np.count_nonzero((times >= event_start - eps) & (times <= event_end + eps)) >= 3)


def _manifest_digest(manifest):
    body = {k: v for k, v in manifest.items() if k != 'dataset_sha256'}
    return hashlib.sha256(json.dumps(body, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _feature_spec():
    return json.loads(json.dumps(asdict(SPEC)))


def _read_source(item):
    path = Path(item['keypoint_csv'])
    metadata = json.loads(path.with_suffix('.schema.json').read_text(encoding='utf-8'))
    if metadata.get('source_sha256') != item['video_sha256']:
        raise ValueError(f'CSV/video checksum mismatch: {item["video_id"]}')
    times, points = read_keypoints_csv(path)
    if not len(times) or not np.isfinite(points).all() or ((points[..., 2] < 0) | (points[..., 2] > 1)).any():
        raise ValueError(f'Invalid pose data for {item["video_id"]}')
    raw = resample_keypoints(times, points).reshape(-1, NUM_FEATURES)
    if item['label'] and not (times[0] <= item['event_start'] <= item['event_end'] <= times[-1]):
        raise ValueError(f'Fall annotation outside source timestamp range: {item["video_id"]}')
    item.update(keypoint_sha256=digest(path), sidecar_sha256=digest(path.with_suffix('.schema.json')),
                native_fps=metadata.get('native_fps'), width=metadata.get('width'), height=metadata.get('height'),
                first_timestamp=float(times[0]), last_timestamp=float(times[-1]), frame_count=len(times),
                missing_pose_frames=int((points[..., 2] == 0).all(axis=1).sum()),
                missing_keypoints=int((points[..., 2] < SPEC.minimum_visibility).sum()),
                timestamp_gaps=int((np.diff(times) > SPEC.max_gap_s).sum()))
    return times, raw


def _windows(item, raw, normalized, stride):
    for start in range(0, len(raw) - SPEC.window_size + 1, stride):
        stop = start + SPEC.window_size
        stamps = [item['first_timestamp'] + i / SPEC.sample_rate_hz for i in range(start, stop)]
        if item['label'] and not fall_window(stamps, item['event_start'], item['event_end']):
            continue
        if not normalized[start:stop, 2::3].any(axis=1).all():
            continue
        yield start, stamps, raw[start:stop], normalized[start:stop]


def preflight_sources(sources, *, mode='official', stride=3):
    if mode not in ('official', 'research') or stride < 1:
        raise ValueError('Expected official/research mode and positive stride')
    eligible, rejected, context = [], [], []
    for source in _ordered(sources):
        identity = {'video_id': source.video_id, 'label': source.label}
        try:
            item = _source_record(source)
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            rejected.append({**identity, 'reason': 'INVALID_SOURCE', 'detail': str(exc)})
            continue
        evidence = _provenance_errors(item)
        if mode == 'official' and evidence:
            rejected.append({**identity, 'reason': 'UNVERIFIED_PROVENANCE', 'detail': ', '.join(evidence)})
            continue
        try:
            _, raw = _read_source(item)
        except (ValueError, OSError, KeyError) as exc:
            rejected.append({**identity, 'reason': 'INVALID_KEYPOINTS', 'detail': str(exc)})
            context.append(item)
            continue
        normalized = normalize_sequence(raw)
        if len(raw) < SPEC.window_size:
            reason = 'TOO_SHORT'
        elif not any(normalized[i:i+SPEC.window_size, 2::3].any(axis=1).all()
                     for i in range(0, len(raw)-SPEC.window_size+1, stride)):
            reason = 'NO_CONTIGUOUS_POSE_WINDOW'
        elif next(_windows(item, raw, normalized, stride), None) is None:
            reason = 'INSUFFICIENT_EVENT_OVERLAP'
        else:
            eligible.append(item)
            continue
        rejected.append({**identity, 'reason': reason, 'detail': f'{len(raw)} grid samples at {SPEC.sample_rate_hz} Hz'})
        context.append(item)
    return eligible, rejected, context


def build_dataset(sources, output, *, version, seed, stride=3, mode='official', preflight_report=None,
                  min_holdout_groups=1, train_only_sources=()):
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    if not version.strip() or stride < 1:
        raise ValueError('Version and positive stride are required')
    eligible, rejected, context = preflight_sources(sources, mode=mode, stride=stride)
    preflight = {'eligible': len(eligible), 'rejected': rejected}
    if preflight_report is not None:
        with Path(preflight_report).open('x', encoding='utf-8') as stream:
            json.dump(preflight, stream, indent=2)
    if not eligible:
        detail = '; '.join(dict.fromkeys(r['detail'] for r in rejected))
        raise ValueError(f'No eligible sources after preflight: {detail}')
    train_only_sources = sorted(set(train_only_sources))
    plan = _split_records(eligible, seed, context, min_holdout_groups=min_holdout_groups,
                          train_only_sources=train_only_sources)
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='.annha-dataset-', dir=output.parent) as directory:
        root = Path(directory) / 'dataset'
        root.mkdir()
        windows = []
        for item in plan.values():
            prior = item['keypoint_sha256'], item['sidecar_sha256']
            _, raw = _read_source(item)
            if prior != (item['keypoint_sha256'], item['sidecar_sha256']) or digest(item['source_file']) != item['video_sha256']:
                raise ValueError(f'Source changed after preflight: {item["video_id"]}')
            if item['duplicate_of']:
                item['sequence_count'] = 0
                continue
            normalized = normalize_sequence(raw)
            start_count = len(windows)
            for start, timestamps, array, features in _windows(item, raw, normalized, stride):
                stem = hashlib.sha256(item['video_id'].encode()).hexdigest()
                path = Path('sequences') / item['split'] / f'{stem}-{start:07d}.npy'
                (root / path).parent.mkdir(parents=True, exist_ok=True)
                np.save(root / path, array, allow_pickle=False)
                windows.append({'path': path.as_posix(), 'video_id': item['video_id'], 'group_id': item['group_id'],
                                'label': item['label'], 'split': item['split'], 'frame_timestamps': timestamps,
                                'schema': SPEC.schema_version, 'start_sample': start, 'sha256': digest(root / path),
                                'feature_sha256': hashlib.sha256(features.astype('<f4').tobytes()).hexdigest()})
            item['sequence_count'] = len(windows) - start_count
            if not item['sequence_count']:
                raise ValueError(f'No valid labeled windows for {item["video_id"]}; inspect timestamps and pose coverage')
        manifest = {'dataset_version': version, 'feature_schema_version': SPEC.schema_version, 'feature_spec': _feature_spec(),
                    'seed': seed, 'ratios': dict(zip(SPLITS, RATIOS)), 'stride': stride, 'sources': list(plan.values()),
                    'windows': windows, 'mode': mode, 'g3_eligible': mode == 'official',
                    'g3_status': 'REVIEW_REQUIRED' if mode == 'official' else 'BLOCKED_RESEARCH_ONLY',
                    'fall_window_rule': FALL_WINDOW_RULE, 'preflight': preflight, 'group_context': context,
                    'test_lock': sorted({r['group_id'] for r in plan.values() if r['split'] == 'test'}) if mode == 'official' else []}
        if min_holdout_groups != 1:
            manifest['min_holdout_groups'] = min_holdout_groups
        if train_only_sources:
            manifest['train_only_sources'] = train_only_sources
        manifest['dataset_sha256'] = _manifest_digest(manifest)
        (root / 'manifest.json').write_text(json.dumps(manifest, indent=2, allow_nan=False), encoding='utf-8')
        verify_dataset(root)
        if output.exists() or output.is_symlink():
            raise FileExistsError(output)
        root.rename(output)
    return manifest


def _partition(index, key, split, description):
    if index.setdefault(key, split) != split:
        raise ValueError(f'Cross-split {description}: {key}')


def verify_dataset(root, *, verify_sources=False):
    root = Path(root).resolve()
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    if manifest['feature_schema_version'] != SPEC.schema_version or manifest['feature_spec'] != _feature_spec():
        raise ValueError('Dataset feature schema does not match annha-pose-v2')
    if _manifest_digest(manifest) != manifest['dataset_sha256']:
        raise ValueError('Dataset manifest hash mismatch')
    mode = manifest.get('mode')
    if (mode not in ('official', 'research') or manifest.get('g3_eligible') is not (mode == 'official')
            or manifest.get('g3_status') != ('REVIEW_REQUIRED' if mode == 'official' else 'BLOCKED_RESEARCH_ONLY')
            or manifest.get('fall_window_rule') != FALL_WINDOW_RULE):
        raise ValueError('Missing dataset quality mode or current Fall label rule')
    index = {}
    sources = {}
    for row in manifest['sources']:
        if row['video_id'] in sources:
            raise ValueError(f'Duplicate video ID: {row["video_id"]}')
        sources[row['video_id']] = row
        if row['label'] not in (0, 1) or row['split'] not in SPLITS:
            raise ValueError(f'Invalid label or split for {row["video_id"]}')
        _validate_cross_source(row)
        if mode == 'official' and _provenance_errors(row):
            raise ValueError(f'Official Test provenance gate failed: {row["video_id"]}')
        if verify_sources:
            csv_path = Path(row['keypoint_csv'])
            for path, key in ((row['source_file'], 'video_sha256'), (csv_path, 'keypoint_sha256'),
                              (csv_path.with_suffix('.schema.json'), 'sidecar_sha256')):
                if digest(path) != row[key]:
                    raise ValueError(f'Source checksum mismatch: {path}')
            if row['decoded_sha256'] and decoded_video_digest(row['source_file']) != row['decoded_sha256']:
                raise ValueError(f'Decoded source checksum mismatch: {row["video_id"]}')
        for field in ('video_id', 'video_sha256', 'decoded_sha256', 'group_id', 'cross_source_group'):
            if row[field]:
                _partition(index, (field, row[field]), row['split'], field)
        if row['source_group']:
            _partition(index, ('source_group', row['source_dataset'], row['source_group']), row['split'], 'source_group')
        if row['subject_id']:
            _partition(index, ('subject', row['source_dataset'], row['subject_id']), row['split'], 'subject')
    context = [dict(row) for row in manifest['group_context']]
    context_ids = {row['video_id'] for row in context}
    rejected_rows = manifest['preflight']['rejected']
    rejected_ids = {row['video_id'] for row in rejected_rows}
    if (manifest['preflight']['eligible'] != len(sources) or rejected_ids & sources.keys()
            or len(rejected_ids) != len(rejected_rows)
            or not context_ids <= rejected_ids or len(context_ids) != len(context)):
        raise ValueError('Invalid preflight grouping context')
    for row in context:
        _validate_cross_source(row)
        if mode == 'official' and _provenance_errors(row):
            raise ValueError('Unverified provenance in grouping context')
    replay = _split_records([dict(row) for row in sorted(sources.values(), key=lambda x: x['video_id'])],
                            manifest['seed'], context,
                            min_holdout_groups=manifest.get('min_holdout_groups', 1),
                            train_only_sources=manifest.get('train_only_sources', ()))
    if any(any(replay[key][field] != row[field] for field in ('split', 'group_id', 'duplicate_of'))
           for key, row in sources.items()):
        raise ValueError('Stored split does not reproduce from seed and video groups')
    test_lock = sorted({r['group_id'] for r in sources.values() if r['split'] == 'test'}) if mode == 'official' else []
    if test_lock != manifest['test_lock']:
        raise ValueError('Test group lock mismatch')
    classes = {split: set() for split in SPLITS}
    counts = Counter()
    feature_labels = {}
    paths = set()
    for window in manifest['windows']:
        source = sources[window['video_id']]
        if source['duplicate_of'] or window.get('augmentation') or any(window[k] != source[k] for k in ('group_id', 'label', 'split')):
            raise ValueError('Window does not match original source assignment')
        if window['schema'] != SPEC.schema_version:
            raise ValueError('Window schema mismatch')
        path = (root / window['path']).resolve(strict=True)
        if not path.is_relative_to(root) or path in paths or path.suffix != '.npy':
            raise ValueError(f'Invalid or duplicate window path: {window["path"]}')
        paths.add(path)
        array = np.load(path, allow_pickle=False)
        if array.dtype != np.float32 or array.shape != SHAPE or not np.isfinite(array).all():
            raise ValueError(f'Expected finite float32 {SHAPE}: {window["path"]}')
        features = normalize_sequence(array)
        if not features[:, 2::3].any(axis=1).all():
            raise ValueError('Window contains unusable pose sample')
        feature_hash = hashlib.sha256(features.astype('<f4').tobytes()).hexdigest()
        if digest(path) != window['sha256'] or feature_hash != window['feature_sha256']:
            raise ValueError(f'Window checksum mismatch: {window["path"]}')
        start = window['start_sample']
        timestamps = np.asarray(window['frame_timestamps'], dtype=float)
        if (not isinstance(start, int) or start < 0 or timestamps.shape != (SPEC.window_size,)
                or not np.allclose(timestamps, source['first_timestamp'] + (start + np.arange(SPEC.window_size)) / SPEC.sample_rate_hz,
                                   rtol=0, atol=1e-8)
                or timestamps[-1] > source['last_timestamp'] + 1e-8
                or (source['label'] and not fall_window(timestamps, source['event_start'], source['event_end']))):
            raise ValueError(f'Invalid or unlabeled window timestamps: {window["path"]}')
        if feature_labels.setdefault(feature_hash, window['label']) != window['label']:
            raise ValueError('Identical normalized sequences have conflicting labels')
        _partition(index, ('feature', feature_hash), window['split'], 'normalized sequence duplicate')
        _partition(index, ('array', window['sha256']), window['split'], 'sequence duplicate')
        classes[window['split']].add(window['label'])
        counts[window['video_id']] += 1
    if any(classes[split] != {0, 1} for split in SPLITS):
        raise ValueError('All data splits must have windows from both classes')
    if any(counts[key] != row['sequence_count'] for key, row in sources.items()):
        raise ValueError('Source window count differs from manifest')
    if paths != {p.resolve() for p in root.rglob('*.npy')}:
        raise ValueError('Unlisted NPY files in dataset')
    return manifest


def approve_subset(root, *, expected_sha256, reviewer, evidence):
    """Record an explicit subset approval after checking all source artifacts."""
    if not reviewer.strip() or not evidence.strip():
        raise ValueError('Approval requires reviewer identity and independent evidence')
    root = Path(root)
    manifest = verify_dataset(root, verify_sources=True)
    if not manifest['g3_eligible']:
        raise ValueError('Research-only dataset cannot be approved for official Test')
    if manifest['dataset_sha256'] != expected_sha256:
        raise ValueError('Approval SHA-256 does not match the verified dataset')
    with (root / 'g3-subset-approval.json').open('x', encoding='utf-8') as stream:
        json.dump({'scope':'G3_SUBSET','dataset_sha256':expected_sha256,'test_lock':manifest['test_lock'],
                   'reviewer':reviewer.strip(),'evidence':evidence.strip()},stream,indent=2)


def require_subset_approval(root, manifest):
    path = Path(root) / 'g3-subset-approval.json'
    if not path.is_file():
        raise ValueError('Official Test requires explicit G3 subset approval')
    approval = json.loads(path.read_text(encoding='utf-8'))
    if (approval.get('scope') != 'G3_SUBSET'
            or approval.get('dataset_sha256') != manifest['dataset_sha256']
            or approval.get('test_lock') != manifest['test_lock']
            or not all(isinstance(approval.get(key),str) and approval[key].strip()
                       for key in ('reviewer','evidence'))):
        raise ValueError('G3 subset approval does not match the locked Test manifest')
