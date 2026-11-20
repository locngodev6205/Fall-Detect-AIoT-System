import json

import numpy as np
import pytest

from research.diagnostics import Trace, replay
from research.streaming import Stream


def make_trace(directory, include_pose):
    model = lambda _: .8
    stream = Stream(model)
    pose = np.ones((17,3), dtype=np.float32)
    pose[:,1] = np.arange(17)/17
    with Trace(directory, scenario='test', include_pose=include_pose) as trace:
        for i in range(55):
            stamp = i/10
            if i == 26:
                stream.reset('camera_disconnect')
                trace.reset('camera_disconnect')
            sample = None if i in (9,10) else pose
            trace.frame(stream,stamp,sample,bool(sample is not None),stamp,stream.push(stamp,sample))
    return model


def test_pose_trace_replays_scores_and_alert_through_reset(tmp_path):
    directory = tmp_path/'recording'
    model = make_trace(directory, True)
    path = directory/'trace.jsonl'
    assert directory.stat().st_mode & 0o777 == 0o700
    assert path.stat().st_mode & 0o777 == 0o600
    assert replay(path,model)['max_score_delta'] == 0
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert sum(e[0]=='simulated_alert' for r in rows for w in r.get('windows',[]) for e in w['events']) == 1
    with pytest.raises(ValueError,match='Score mismatch'):
        replay(path,lambda _: .81)
    path.write_text(path.read_text()+'\n')
    with pytest.raises(ValueError,match='checksum'):
        replay(path,model)


def test_metrics_only_omits_pose_and_cannot_rescore(tmp_path):
    directory = tmp_path/'metrics-only'
    model = make_trace(directory, False)
    path = directory/'trace.jsonl'
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert not any('pose' in row for row in rows if row['kind']=='frame')
    with pytest.raises(ValueError,match='opt-in'):
        replay(path,model)
