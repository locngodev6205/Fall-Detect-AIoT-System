from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
pytest.importorskip('torch')
from scripts.ml.pr041_ablation import AlertState, eligible, event_outcome, training_examples


def test_alerts_merge_and_early_alert_does_not_count_as_detection():
    scores = [(0.8,.9),(1.2,.9),(1.5,.1),(2.9,.9),(3.1,.9),(3.4,.1),(5.1,.9)]
    outcome = event_outcome((1.,3.),scores)
    assert (outcome['tp'], outcome['early'], outcome['late']) == (1,1,1)
    alone = event_outcome((1.,3.),scores[:2])
    assert (alone['tp'],alone['fn'],alone['covered']) == (0,1,True)
    assert event_outcome((1.,3.),[])['fn'] == 1


def test_gap_and_alert_boundaries():
    assert eligible(np.array([True,False,False,True]),3)
    assert not eligible(np.array([True,False,True,False,True]),3)
    state = AlertState()
    assert state.update(0,.5)
    assert not state.update(3,.8)
    assert not state.update(4,.4)
    assert state.update(5,.8)


def test_matched_train_windows_have_same_recording_and_end_time():
    stamps = np.arange(60)/10
    features = np.arange(60)[:,None]
    recordings = [(dict(event=None,video_id='example',y=0),stamps,features,np.ones(60,bool))]
    long, l_ids, l_y = training_examples(recordings,30,0,True)
    short, s_ids, s_y = training_examples(recordings,20,3,True)
    assert l_ids == s_ids and l_y == s_y
    np.testing.assert_array_equal(long[:,10:],short)


def test_stream_resets_on_timestamp_gap_and_never_scores_before_buffer_fills():
    import torch
    from scripts.ml.pr041_ablation import StreamingGRU

    class Constant(torch.nn.Module):
        def forward(self, batch):
            return torch.ones(len(batch))

    model = StreamingGRU(Constant(), 20, 3)
    pose = np.ones((17, 3), dtype=np.float32)
    pose[:, 1] = np.arange(17)/17
    for i in range(19):
        assert model.push(i/10, pose) == []
    assert model.push(1.9, pose)[0][2]
    assert model.push(2.5, pose) == []
    for i in range(1,19):
        assert model.push(2.5+i/10, pose) == []
    assert model.push(4.4, pose)[0][2]
