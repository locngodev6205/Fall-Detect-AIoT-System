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
