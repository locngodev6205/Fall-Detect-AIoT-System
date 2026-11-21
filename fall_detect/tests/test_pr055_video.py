import json
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest

cv2 = pytest.importorskip('cv2')
sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'scripts/ml'))
import collect_data as tool


def fixture(tmp_path, monkeypatch):
    class Webcam:
        def get(self, prop):
            return 20.
        def read(self):
            return True, np.full((48,64,3),110,dtype=np.uint8)
        def release(self):
            pass

    original = cv2.VideoCapture
    monkeypatch.setattr(cv2,'VideoCapture',lambda path: Webcam() if path == 0 else original(path))
    ticks = iter(np.arange(0,100,.025))
    monkeypatch.setattr(tool.time,'monotonic',lambda: float(next(ticks)))
    args = SimpleNamespace(consent_video=True,subject='fixture',session='session_1',source='fixture',
                           camera_setup='setup',duration=2,camera=0,output=tmp_path,activity='standing',
                           preview=False,split='train',extract_pose=False)
    return args


def test_capture_decode_extract_and_reextract(tmp_path,monkeypatch):
    from contextlib import nullcontext

    detector = SimpleNamespace(process=lambda frame: SimpleNamespace(pose_landmarks=None))
    mock = SimpleNamespace(__version__='fixture', solutions=SimpleNamespace(
        pose=SimpleNamespace(Pose=lambda **_: nullcontext(detector))))
    monkeypatch.setitem(sys.modules, 'mediapipe', mock)
    args=fixture(tmp_path,monkeypatch)
    root=tool.record(args)
    second=tool.record(args)
    assert root != second
    m=tool.validate(root)
    assert m['label']=='UNVERIFIED' and m['frame_count']>20
    v=root/m['video']
    clean=tool.digest(v)
    tool.extract(root)
    tool.extract(root)
    result=tool.validate(root)
    assert result['pose_status']=='COMPLETE'
    assert result['frame_count']==len(tool.rows(root/'pose.jsonl'))
    assert tool.digest(v)==clean
    with pytest.raises(ValueError,match='verified'):
        tool.validate(root,confirmed=True)
    tool.label_trial(root,'NO_FALL')
    assert tool.validate(root)['label']=='NO_FALL'
    with pytest.raises(ValueError,match='usable'):
        tool.validate(root,confirmed=True)


def test_consent_checksum_and_empty_video(tmp_path,monkeypatch):
    args=fixture(tmp_path,monkeypatch)
    args.consent_video=False
    with pytest.raises(ValueError,match='permission'):
        tool.record(args)
    args.consent_video=True
    root=tool.record(args)
    m=tool.validate(root)
    v=root/m['video']
    v.write_bytes(b'')
    with pytest.raises(ValueError,match='checksum'):
        tool.validate(root)
    m['video_sha256']=tool.digest(v)
    tool.write(root/'manifest.json',m)
    with pytest.raises(ValueError,match='cannot be opened'):
        tool.validate(root)


def test_rewrapped_manifest_does_not_hide_timestamp_error(tmp_path,monkeypatch):
    root=tool.record(fixture(tmp_path,monkeypatch))
    m=tool.validate(root)
    frames=tool.rows(root/'frames.jsonl')
    frames[1]['elapsed_s']=frames[0]['elapsed_s']
    p=root/'frames.jsonl'
    p.write_text(''.join(json.dumps(r)+'\n' for r in frames))
    m['frames_sha256']=tool.digest(p)
    tool.write(root/'manifest.json',m)
    with pytest.raises(ValueError,match='timestamps'):
        tool.validate(root)
