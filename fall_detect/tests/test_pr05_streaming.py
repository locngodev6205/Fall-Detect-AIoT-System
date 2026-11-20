from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/ml'))
from research.streaming import EventEngine, Stream, load_model, valid_window


def pose():
    x = np.ones((17,3),dtype=np.float32)
    x[:,1] = np.arange(17)/17
    return x


@pytest.mark.parametrize('lost', [[4],[4,5],[4,5,6],[4,5,6,7],[0],[19],[4,6]])
def test_gap(lost):
    mask = np.ones(20, dtype=bool)
    mask[lost] = False
    assert valid_window(mask) == (lost in ([4],[4,5],[4,5,6]))


def test_stride_warmup_and_reset():
    stream = Stream(lambda _: .8)
    output = [w for i in range(23) for w in stream.push(i/10,pose())]
    assert [w.end for w in output] == [1.9,2.2]
    assert [name for name,_ in output[0].events] == ['candidate','confirmed','simulated_alert']
    assert not output[1].events
    assert stream.push(3.,pose()) == []
    assert stream.resets[-1][0]=='timestamp_gap'
    stream.reset('camera_disconnect')
    assert stream.push(4.,pose()) == []


def test_invalid_timestamp_pose_and_checkpoint(tmp_path):
    stream = Stream(lambda _: 0.)
    for stamp in (float('nan'),float('inf')):
        with pytest.raises(ValueError, match='Timestamps'):
            stream.push(stamp,pose())
    with pytest.raises(ValueError,match='pose shape'):
        stream.push(0,np.zeros(51))
    stream.push(0,pose())
    with pytest.raises(ValueError,match='Timestamps'):
        stream.push(0,pose())
    path = tmp_path/'fake.pt'
    path.write_bytes(b'bogus')
    with pytest.raises(ValueError,match='schema'):
        load_model(path,schema='legacy')
    with pytest.raises(ValueError,match='SHA'):
        load_model(path)


def test_event_cooldown_and_gap_confirmation():
    state = EventEngine()
    assert state.update(0,.5)[-1][0]=='simulated_alert'
    assert not state.update(3,.9)
    state.update(3.1,.1)
    assert state.update(3.2,.7)[-1][0]=='simulated_alert'
    two = EventEngine(confirmations=2)
    assert two.update(0,.6)==(('candidate',0),)
    two.unavailable()
    assert two.update(.6,.6)==(('candidate',.6),)
    assert two.update(.9,.6)[-1][0]=='simulated_alert'


def test_offline_streaming_fixture_and_early_fn():
    pytest.importorskip('torch')
    from pr05_replay import offline, evaluate_alerts

    times = np.arange(60)/10
    poses = np.stack([pose() for _ in times])
    poses[25:28] = 0
    model = lambda window: float(window[:,2::3].mean())
    stream = Stream(model)
    got = [w for t,p in zip(times,poses) for w in stream.push(t,p)]
    expected = list(offline(times,poses,model))
    for (a,b,mask,x,score,events), result in zip(expected,got,strict=True):
        assert (a,b,score,events)==(result.start,result.end,result.score,result.events)
        np.testing.assert_array_equal(mask,result.mask)
        np.testing.assert_array_equal(x,result.inputs)
    report = evaluate_alerts((2.,3.),[1.9],False)
    assert (report['tp'],report['fn'],report['early'])==(0,1,1)
