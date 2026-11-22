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
