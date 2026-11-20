import json
from pathlib import Path

import numpy as np
import pytest

from ml.dataset import write_keypoints_csv
from ml.features import SPEC
from ml.integrity import Source, assign_splits, build_dataset, digest, verify_dataset
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
                               event_start=1.5 if label else None, event_end=2.0 if label else None))
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
    with pytest.raises(ValueError, match='annotation'):
        build_dataset([replace(row, event_start=None) for row in rows], tmp_path / 'v2', version='v2', seed=42)


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
    alias = replace(first, video_id='remux', video=alias_file)
    result = assign_splits([first, *rows[1:], alias], seed=42)
    assert result['remux']['duplicate_of'] == first.video_id
    assert result['remux']['split'] == result[first.video_id]['split']


def test_tampered_assignment_and_test_for_tuning_fail(tmp_path):
    import hashlib
    root = tmp_path / 'v2'
    manifest = build_dataset(sources(tmp_path), root, version='v2', seed=42)
    with pytest.raises(ValueError, match='final_evaluation'):
        DataLoader(root, 'test', purpose='threshold_selection')
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
    with pytest.raises(ValueError, match='strictly increasing'):
        build_dataset(rows, tmp_path / 'v2', version='v2', seed=42)
