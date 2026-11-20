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


def test_reconnect_keeps_alert_latch_and_clock():
    score = .9
    stream = Stream(lambda _: score)
    def fill(start):
        return [w for i in range(20) for w in stream.push(start+i/10, pose())][-1]
    assert fill(0).events[-1][0] == 'simulated_alert'
    stream.reset('camera_disconnect')
    assert not fill(4).events
    score = .1
    stream.push(6.,pose())
    stream.push(6.1,pose())
    stream.push(6.2,pose())
    score = .9
    stream.push(6.3,pose())
    stream.push(6.4,pose())
    assert stream.push(6.5,pose())[0].events[-1][0] == 'simulated_alert'


def test_invalid_pose_and_model_failure_never_emit_alert():
    count = iter([float('nan'), .9])
    stream = Stream(lambda _: next(count))
    malformed = pose()
    malformed[0,0] = np.inf
    initial = [w for i in range(20) for w in stream.push(i/10, malformed if i==8 else pose())][0]
    assert stream.invalid_poses == 1
    assert (initial.score,initial.events,initial.error) == (None,(),'ValueError')
    for stamp in (2.,2.1):
        assert not stream.push(stamp,pose())
    assert stream.push(2.2,pose())[0].events[-1][0] == 'simulated_alert'
    assert stream.model_errors == 1


def test_model_exception_is_counted_and_pending_confirmation_cleared():
    def fail(_):
        raise RuntimeError('message stays outside telemetry')
    stream = Stream(fail)
    windows = [w for i in range(20) for w in stream.push(i/10,pose())]
    assert windows[0].error == 'RuntimeError' and not windows[0].events


def test_cross_device_score_tolerance_still_rejects_alert_flip():
    from research.parity import compare

    reference = dict(checkpoint_sha256='same', model_errors=0,
                     windows=[dict(start=0., end=1.9, mask=[True]*20,
                                   tensor_sha256='same', score=.500001, events=[])])
    changed = {**reference, 'windows': [{**reference['windows'][0], 'score': .499999}]}
    assert compare(reference, changed)['passed']
    changed['windows'][0]['events'] = [['simulated_alert',1.9]]
    result = compare(reference, changed)
    assert not result['passed']
    assert result['scores_near_threshold'] == result['decision_mismatches'] == 1


def test_disconnect_starts_new_grid_without_double_counting_gap():
    stream = Stream(lambda _: .1)
    stream.push(0.,pose())
    stream.reset('camera_disconnect')
    assert stream.push(5.,pose()) == []
    assert [reason for reason,_ in stream.resets] == ['initial','camera_disconnect']


def test_tensor_compare_accepts_small_cross_cpu_rounding():
    from research.parity import compare
    tensor = np.zeros((20,51),dtype=np.float32)
    expected = dict(start=0.,end=1.9,mask=[True]*20,tensor_sha256='a',
                    score=.49,events=[],tensor=tensor.tolist())
    reference = dict(checkpoint_sha256='same',model_errors=0,windows=[expected])
    tensor[0,0] = 1e-6
    actual = dict(**{**expected, 'tensor_sha256':'b','tensor':tensor.tolist()})
    observed = {**reference,'windows':[actual]}
    assert compare(reference,observed)['passed']
    tensor[0,0] = .01
    actual['tensor'] = tensor.tolist()
    assert compare(reference,observed)['tensor_mismatches'] == 1


def test_missing_checkpoint_fails_before_model_loading(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_model(tmp_path/'missing.pt')
