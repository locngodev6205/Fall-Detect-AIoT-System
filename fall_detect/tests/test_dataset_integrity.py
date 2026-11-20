import json
from pathlib import Path

import numpy as np
import pytest

from ml.dataset import write_keypoints_csv
from ml.features import SPEC
from ml.integrity import Source, approve_subset, assign_splits, build_dataset, digest, verify_dataset
from ml.training_data import DataLoader


def sources(root):
    rows = []
    for label in (0, 1):
        for index in range(4):
            key = f'{label}-{index}'
            video = root / f'{key}.mp4'
            video.write_bytes(key.encode())
            csv = root / f'{key}.csv'
            times = np.arange(40) / 10
            points = np.ones((40, 17, 3), np.float32)
            points[:, :, 0] = np.arange(17) * .023 + np.arange(40)[:, None] * .0001
            points[:, :, 1] = .05 * index + .03 * label + np.arange(17)**2 * .001
            points[:, 0, 0] += .01 * (index + label * 4)
            write_keypoints_csv(csv, times, points, source=video, fps=10, image_size=(640, 480),
                                mediapipe_version='fixture', source_sha256=digest(video))
            rows.append(Source(key, video, csv, label, 'fixture', subject_id=f'p-{index}',
                               event_start=1.5 if label else None, event_end=2.0 if label else None,
                               provenance_status='VERIFIED', source_ref='fixture record',
                               expected_video_sha256=digest(video), source_group=f'p-{index}',
                               group_status='VERIFIED', group_evidence='fixture grouping',
                               annotation_status='HUMAN_VERIFIED', annotation_source='fixture annotation',
                               reviewer='fixture reviewer'))
    return rows


def test_reproducible_dataset_and_train_only_augmentation(tmp_path):
    rows = sources(tmp_path)
    first = build_dataset(rows, tmp_path / 'v2-a', version='v2', seed=42)
    second = build_dataset(rows[::-1], tmp_path / 'v2-b', version='v2', seed=42)
    assert first['dataset_sha256'] == second['dataset_sha256']
    root = tmp_path / 'v2-a'
    assert verify_dataset(root)['dataset_sha256'] == first['dataset_sha256']
    assert all(row['schema'] == SPEC.schema_version for row in first['windows'])
    train = DataLoader(root, 'train', batch_size=3, augment=True)
    x, y = train[0]
    assert x.shape == (3, 30, 51) and np.isfinite(x).all()
    assert set(y) <= {0, 1}
    assert np.array_equal(x, DataLoader(root, 'train', batch_size=3, augment=True)[0][0])
    for split in ('val', 'test'):
        with pytest.raises(ValueError, match='train'):
            DataLoader(root, split, augment=True)


def test_alias_hash_and_subject_overlap_connect_groups(tmp_path):
    rows = sources(tmp_path)
    alias = tmp_path / 'renamed.mp4'
    alias.write_bytes(rows[0].video.read_bytes())
    row = Source('alias', alias, rows[0].keypoints, 0, 'fixture', subject_id='p-1')
    plan = assign_splits([*rows, row], seed=12)
    assert plan['alias']['group_id'] == plan[rows[0].video_id]['group_id'] == plan[rows[1].video_id]['group_id']
    assert plan['alias']['duplicate_of']


def test_invalid_feature_fails_validation(tmp_path):
    rows = sources(tmp_path)
    root = tmp_path / 'v2'
    manifest = build_dataset(rows, root, version='v2', seed=42)
    path = root / manifest['windows'][0]['path']
    data = np.load(path, allow_pickle=False)
    data[0, 0] = np.inf
    np.save(path, data)
    with pytest.raises(ValueError, match='finite'):
        verify_dataset(root)


def test_impossible_split_and_unannotated_fall_fail(tmp_path):
    rows = sources(tmp_path)
    with pytest.raises(ValueError, match='three'):
        assign_splits(rows[:2], seed=42)
    from dataclasses import replace
    from ml.integrity import preflight_sources
    unannotated = [replace(row, event_start=None) for row in rows]
    _, rejected, _ = preflight_sources(unannotated)
    assert len(rejected) == 4 and all('annotation' in row['detail'] for row in rejected)
    with pytest.raises(ValueError, match='three independent groups'):
        build_dataset(unannotated, tmp_path / 'v2', version='v2', seed=42)


def test_identical_windows_from_different_videos_cannot_cross_splits(tmp_path):
    rows = sources(tmp_path)
    plan = assign_splits(rows, seed=42)
    left, right = next((a, b) for a in rows for b in rows
                       if a.label == b.label == 0
                       and plan[a.video_id]['split'] != plan[b.video_id]['split'])
    right.keypoints.write_bytes(left.keypoints.read_bytes())
    with pytest.raises(ValueError, match='Cross-split normalized sequence duplicate'):
        build_dataset(rows, tmp_path / 'v2', version='v2', seed=42)
    assert not (tmp_path / 'v2').exists()


def test_decoded_video_fingerprint_joins_different_containers(tmp_path):
    from dataclasses import replace
    rows = sources(tmp_path)
    first = replace(rows[0], decoded_sha256='a' * 64)
    alias_file = tmp_path / 'remux.mkv'
    alias_file.write_bytes(b'bytes with another container')
    alias = replace(first, video_id='remux', video=alias_file, expected_video_sha256=digest(alias_file))
    result = assign_splits([first, *rows[1:], alias], seed=42)
    assert result['remux']['duplicate_of'] == first.video_id
    assert result['remux']['split'] == result[first.video_id]['split']


def test_tampered_assignment_and_test_for_tuning_fail(tmp_path):
    import hashlib
    root = tmp_path / 'v2'
    manifest = build_dataset(sources(tmp_path), root, version='v2', seed=42)
    with pytest.raises(ValueError, match='final_evaluation'):
        DataLoader(root, 'test', purpose='threshold_selection')
    with pytest.raises(ValueError, match='explicit G3 subset approval'):
        DataLoader(root, 'test', purpose='final_evaluation')
    with pytest.raises(ValueError, match='SHA-256'):
        approve_subset(root, expected_sha256='0'*64, reviewer='fixture reviewer', evidence='fixture evidence')
    approve_subset(root, expected_sha256=manifest['dataset_sha256'], reviewer='fixture reviewer', evidence='fixture evidence')
    assert len(DataLoader(root, 'test', purpose='final_evaluation'))
    row = manifest['sources'][0]
    row['split'] = 'val' if row['split'] != 'val' else 'test'
    body = {key: value for key, value in manifest.items() if key != 'dataset_sha256'}
    manifest['dataset_sha256'] = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    (root / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='Cross-split'):
        verify_dataset(root)


def test_out_of_order_keypoint_timestamps_are_rejected(tmp_path):
    rows = sources(tmp_path)
    path = rows[0].keypoints
    path.write_text(path.read_text().replace('2,0.1,', '2,-1,'))
    manifest = build_dataset(rows, tmp_path / 'v2', version='v2', seed=42)
    assert manifest['preflight']['rejected'][0]['reason'] == 'INVALID_KEYPOINTS'
    assert 'strictly increasing' in manifest['preflight']['rejected'][0]['detail']


def test_fall_window_needs_onset_and_sufficient_overlap():
    from ml.integrity import fall_window
    times = np.arange(30) / 10
    assert not fall_window(times, 2.9, 3.5)
    assert not fall_window(times, 2.8, 3.4)
    assert not fall_window(times, -.1, 1)
    assert not fall_window(times, 1, 1.2)
    assert fall_window(times, 2.6, 3.2)
    assert fall_window(times, 1.1, 2.6)
    assert not fall_window(times, 2.31, 3.81)  # just below the 0.6 s cap
    assert fall_window(times, 2.3, 3.8)


def test_official_gate_and_explicit_research_allow_separate_uses(tmp_path):
    from dataclasses import replace
    rows = [replace(row, provenance_status=None) for row in sources(tmp_path)]
    with pytest.raises(ValueError, match='provenance'):
        build_dataset(rows, tmp_path / 'official', version='v2', seed=42)
    research = build_dataset(rows, tmp_path / 'research', version='v2', seed=42, mode='research')
    assert research['test_lock'] == []
    assert research['g3_eligible'] is False
    with pytest.raises(ValueError, match='research'):
        DataLoader(tmp_path / 'research', 'test', purpose='final_evaluation')
    assert len(DataLoader(tmp_path / 'research', 'test', purpose='research_evaluation'))


def test_group_names_are_scoped_and_verified_cross_source_links_merge(tmp_path):
    from dataclasses import replace
    rows = sources(tmp_path)
    first = replace(rows[0], source_group='session-1')
    other = replace(rows[1], source_dataset='another', source_group='session-1')
    plan = assign_splits([first, other, *rows[2:]], seed=4)
    assert plan[first.video_id]['group_id'] != plan[other.video_id]['group_id']
    first = replace(first, cross_source_group='event-uuid', cross_source_evidence='aligned source mapping')
    other = replace(other, cross_source_group='event-uuid', cross_source_evidence='aligned source mapping')
    plan = assign_splits([first, other, *rows[2:]], seed=4)
    assert plan[first.video_id]['group_id'] == plan[other.video_id]['group_id']
    with pytest.raises(ValueError, match='cross-source'):
        assign_splits([replace(first, cross_source_evidence=None), other, *rows[2:]], seed=4)


def test_short_clip_excluded_before_split(tmp_path):
    from ml.integrity import preflight_sources
    rows = sources(tmp_path)
    path = rows[0].keypoints
    lines = path.read_text().splitlines()
    path.write_text('\n'.join(lines[:1+20*17])+'\n')
    eligible, rejected, _ = preflight_sources(rows)
    assert rows[0].video_id not in {item['video_id'] for item in eligible}
    assert rejected[0]['reason'] == 'TOO_SHORT'
    manifest = build_dataset(rows, tmp_path / 'v2', version='v2', seed=42)
    assert manifest['preflight']['rejected'][0]['reason'] == 'TOO_SHORT'


def test_official_rejects_wrong_hash_unverified_group_and_annotation(tmp_path):
    from dataclasses import replace
    from ml.integrity import preflight_sources
    rows = sources(tmp_path)
    variants = [replace(rows[0], expected_video_sha256='a'*64),
                replace(rows[1], group_status='UNVERIFIED'), replace(rows[4], annotation_status='PROPOSAL')]
    eligible, rejected, _ = preflight_sources(variants)
    assert not eligible
    assert {row['reason'] for row in rejected} == {'INVALID_SOURCE', 'UNVERIFIED_PROVENANCE'}
    assert any('checksum mismatch' in row['detail'] for row in rejected)
    assert any('source_group' in row['detail'] for row in rejected)
    assert any('annotation' in row['detail'] for row in rejected)


def test_clip_without_onset_overlap_excluded_before_split(tmp_path):
    from dataclasses import replace
    from ml.integrity import preflight_sources
    rows = sources(tmp_path)
    late = replace(rows[4], event_start=3.7, event_end=3.9)
    eligible, rejected, _ = preflight_sources([late])
    assert not eligible
    assert rejected[0]['reason'] == 'INSUFFICIENT_EVENT_OVERLAP'


def test_excluded_clip_still_connects_proven_source_groups(tmp_path):
    from dataclasses import replace
    rows = sources(tmp_path)
    left, right = rows[0], rows[1]
    linked = replace(left, cross_source_group='verified-event', cross_source_evidence='manual alignment')
    bridge = replace(right, video_id='bridge', cross_source_group='verified-event',
                     cross_source_evidence='manual alignment', keypoints=tmp_path / 'missing.csv')
    manifest = build_dataset([linked, *rows[1:], bridge], tmp_path / 'v2', version='v2', seed=42)
    by_id = {row['video_id']: row for row in manifest['sources']}
    assert by_id[left.video_id]['group_id'] == by_id[right.video_id]['group_id']
    assert manifest['preflight']['rejected'][0]['reason'] == 'INVALID_KEYPOINTS'
    assert verify_dataset(tmp_path / 'v2')['dataset_sha256'] == manifest['dataset_sha256']


def test_research_manifest_cannot_be_promoted_without_provenance(tmp_path):
    from dataclasses import replace
    import hashlib
    rows = [replace(row, annotation_status='PROPOSAL') for row in sources(tmp_path)]
    path = tmp_path / 'research'
    manifest = build_dataset(rows, path, version='test', seed=42, mode='research')
    manifest.update(mode='official', g3_eligible=True, g3_status='REVIEW_REQUIRED')
    manifest['test_lock'] = sorted({row['group_id'] for row in manifest['sources'] if row['split'] == 'test'})
    manifest.pop('dataset_sha256')
    manifest['dataset_sha256'] = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    (path / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='provenance gate'):
        verify_dataset(path)


def test_preflight_report_survives_insufficient_groups(tmp_path):
    rows = sources(tmp_path)
    report = tmp_path / 'review.json'
    with pytest.raises(ValueError, match='three independent groups'):
        build_dataset(rows[:2], tmp_path / 'blocked', version='test', seed=42, preflight_report=report)
    assert json.loads(report.read_text())['eligible'] == 2
    assert not (tmp_path / 'blocked').exists()
