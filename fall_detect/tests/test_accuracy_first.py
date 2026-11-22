from pathlib import Path
import sys

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/ml"))
from accuracy_ctr_gcn import graph_input
from accuracy_pose import phase_summary


def test_graph_layout_preserves_temporal_joint_and_channel_order():
    data = torch.arange(20*17*3).reshape(1, 20, 51)
    graph = graph_input(data)
    assert graph.shape == (1, 3, 20, 17, 1)
    assert graph[0, 2, 9, 12, 0] == data[0, 9, 38]


def test_phase_pose_counts_and_dropout():
    point = np.zeros((17, 3), dtype=np.float32)
    tracked = point.copy()
    tracked[[5, 6, 11, 12], 2] = .9
    tracked[[5, 6], 0] = .2
    tracked[[11, 12], 0] = .6
    phases = phase_summary(np.array([point, point, tracked, point]))
    assert phases["usable"] == 1
    assert phases["missing_joints"] == 4*17-4
    assert phases["longest_unusable_frames"] == 2
    assert phases["horizontal_proxy_frames"] == 1
    assert phase_summary(np.zeros((0, 17, 3))) is None


def test_targeted_weights_preserve_class_balance_and_never_upweight_a_fall():
    from accuracy_ctr_gcn import recording_weights

    base = recording_weights(["fall", "sit", "sit", "walk"], [1, 0, 0, 0], set())
    changed = recording_weights(["fall", "sit", "sit", "walk"], [1, 0, 0, 0], {"sit", "fall"})
    np.testing.assert_allclose(changed[0], base[0])
    np.testing.assert_allclose(changed[1:].sum(), base[1:].sum())
    np.testing.assert_allclose(changed[1:3].sum(), 2*changed[3])


def test_score_trace_gaps_break_threshold_crossings():
    from accuracy_compare import score_trace

    trace = score_trace({"scores": [(1., .7), (2., None), (3., .8), (4., .9)]})
    assert trace == "0.900@4.00; 1.00–1.00, 3.00–4.00"


def test_comparison_rejects_inconsistent_annotations():
    from accuracy_compare import paired
    import pytest

    a = dict(id="clip", event=(1, 2), action="Fall forward")
    with pytest.raises(ValueError, match="Annotation mismatch"):
        list(paired([a], [dict(a, event=(1, 3))]))


def test_pose_cache_rejects_split_mismatch_and_tampering(tmp_path):
    import json
    import pytest

    from accuracy_pose_cache import PoseCache
    from ml.features import SPEC
    from ml.integrity import digest
    from pr04_experiment import MANIFEST

    path = tmp_path/"clip.npz"
    np.savez_compressed(path, stamps=np.array([1., 1.1]),
                        points=np.zeros((2, 17, 3), dtype=np.float32))
    row = dict(video_id="clip", split="train", scene_id="Walk", event=None)
    entry = dict(id="clip", split="train", action="Walk", event=None, video_sha256="abc",
                 feature_file=path.name, feature_sha256=digest(path))
    manifest = tmp_path/"manifest.json"
    manifest.write_text(json.dumps(dict(cache_version="accuracy-pose-v1", manifest=MANIFEST,
        joint_order=SPEC.keypoints, schema_version=SPEC.schema_version,
        coordinate_space=SPEC.coordinate_space, recordings=[entry])))
    pinned = dict(sources=[dict(video_id="clip", video_sha256="abc")], group_context=[])
    with pytest.raises(ValueError, match="split mismatch"):
        PoseCache(tmp_path, [dict(row, split="val")], pinned)
    cache = PoseCache(tmp_path, [row], pinned)
    stamps, points = cache.load(row)
    assert points.shape == (2, 17, 3) and stamps.tolist() == [1., 1.1]
    path.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        cache.load(row)


def test_episode_preserves_first_alert_and_needs_observed_recovery():
    from accuracy_episode import Episode

    policy = Episode(upright_limit=15)
    assert policy.step(0., .9, None, True)
    for i in range(1, 10):
        assert not policy.step(i*.3, .1, None, False)
    assert not policy.step(3., .8, 75., True)
    for i in range(11, 19):
        assert not policy.step(i*.3, .1, 5., False)
    assert policy.step(5.7, .8, None, True)


def test_episode_missing_score_breaks_upright_recovery():
    from accuracy_episode import Episode

    policy = Episode(upright_limit=15)
    assert policy.step(0., .8, 20., True)
    for i in range(1, 7):
        policy.step(i*.3, .1, 8., False)
    policy.step(2.1, None, None, False)
    assert not policy.step(2.4, .1, 8., False)
    assert not policy.step(2.7, .8, 8., True)


def test_independent_annotations_must_have_one_fall_and_contiguous_clock():
    from accuracy_independent import temporal_interval
    import pytest

    rows = [dict(start=0, end=1, label=4), dict(start=1, end=2, label=1),
            dict(start=2, end=3, label=2)]
    assert temporal_interval(rows, 3., True) == (1., 2.)
    with pytest.raises(ValueError, match="Fall count"):
        temporal_interval(rows, 3., False)
    with pytest.raises(ValueError, match="recording clock"):
        temporal_interval([rows[0], rows[2]], 3., False)


def test_diagnosis_distinguishes_adl_late_and_duplicate():
    from accuracy_stability import interval_flags

    assert interval_flags(None, [1.]) == ["ADL"]
    assert interval_flags((2., 9.), [1., 2.5, 4., 6.]) == ["early", "TP", "duplicate", "late"]


def test_independent_duplicate_check_includes_training_subject_context_only():
    from accuracy_independent import training_fingerprints

    def recording(subject, name, **extra):
        return dict(subject_id=subject, source_dataset="caucafall",
                    video_sha256=name, decoded_sha256=name+"-frames", **extra)

    videos, frames = training_fingerprints(dict(
        sources=[recording("a", "train", split="train"), recording("b", "val", split="val")],
        group_context=[recording("a", "train-extra"), recording("b", "val-extra")],
    ))
    assert videos == {"train", "train-extra"}
    assert frames == {"train-frames", "train-extra-frames"}


def test_multisource_bundle_rejects_subject_group_and_hash_overlap():
    from accuracy_multisource import validate_partition
    import pytest

    train = dict(dataset="caucafall", split="train", subject="1",
                 group_id="ca:one", video_sha256="a", decoded_sha256="A")
    holdout = dict(dataset="caucafall", split="val", subject="2",
                   group_id="ca:two", video_sha256="b", decoded_sha256="B")
    validate_partition([train, holdout, dict(train, dataset="urfd", subject=None)])
    for name in ("subject", "group_id", "video_sha256", "decoded_sha256"):
        with pytest.raises(ValueError, match=name):
            validate_partition([train, dict(holdout, **{name: train[name]})])
