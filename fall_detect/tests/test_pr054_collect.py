import hashlib
import json

import numpy as np
import pytest

from research.collect import Trial, check_splits, validate
from research.diagnostics import Trace
from research.streaming import Stream


def fixture(root, *, bad_time=False):
    trial = dict(recording='r1',subject='s1',session='sess1',source='src1',camera_setup='cam1',
                 activity='pick-up',split='train',consent=True,retention_days=14)
    stream = Stream(lambda _: .1)
    pose = np.ones((17,3), dtype=np.float32)
    pose[:,1] = np.arange(17)/17
    with Trace(root, scenario='pick-up', include_pose=True) as trace:
        for i in range(25):
            t = i/10
            real = stream.push(t,pose)
            trace.frame(stream, 0 if bad_time and i==3 else t, pose, True,t,real)
    payload=(root/'trace.jsonl').read_bytes()
    d=hashlib.sha256(payload).hexdigest()
    (root/'manifest.json').write_text(json.dumps(dict(version=3,schema='annha-pose-v2',trial=trial,
        trace_sha256=d,device=dict(width=640,height=480,mediapipe='test',throughput_fps=10))))
    return d


def test_quality_gate_and_ground_truth(tmp_path):
    root=tmp_path/'trial'
    sha=fixture(root)
    with pytest.raises(ValueError,match='verified'):
        validate(root,confirmed=True)
    (root/'label.json').write_text(json.dumps(dict(label='NO_FALL',trace_sha256=sha)))
    assert validate(root,confirmed=True)['scored']==2
    with (root/'trace.jsonl').open('a') as out:
        out.write('\n')
    with pytest.raises(ValueError,match='checksum'):
        validate(root)


def test_timestamps_and_consent(tmp_path):
    root=tmp_path/'trial'
    fixture(root,bad_time=True)
    with pytest.raises(ValueError,match='timestamps'):
        validate(root)
    m=json.loads((root/'manifest.json').read_text())['trial']
    m['consent']=False
    with pytest.raises(ValueError,match='consent'):
        Trial(**m).check()


@pytest.mark.parametrize('field',['subject','session','source','camera_setup','recording','pose_identity','trace_sha256'])
def test_reject_overlap_and_duplicates(tmp_path,field):
    root=tmp_path/'trial'
    fixture(root)
    first=validate(root)
    second=dict(first,trial={k:(v+'2' if k in ('recording','subject','session','source','camera_setup') else v)
                              for k,v in first['trial'].items()},pose_identity='second',trace_sha256='second')
    second['trial']['split']='evaluation'
    check_splits([first,second])
    if field in first['trial']:
        second['trial'][field]=first['trial'][field]
    else:
        second[field]=first[field]
    with pytest.raises(ValueError,match='Cross-split|Duplicate'):
        check_splits([first,second])
