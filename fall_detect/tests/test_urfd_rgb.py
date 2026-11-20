import shutil
import sys
from pathlib import Path
from zipfile import ZipFile

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.ml.urfd_rgb import pack_rgb, read_sync


def test_sync_rejects_repeated_timestamp_and_frame_gap(tmp_path):
    sync = tmp_path / 'sync.csv'
    sync.write_text('1,5,0\n2,38,0\n3,72,0\n')
    assert read_sync(sync) == [0, 33, 67]
    sync.write_text('1,5,0\n2,5,0\n')
    with pytest.raises(ValueError, match='strictly increasing'):
        read_sync(sync)
    sync.write_text('1,5,0\n3,38,0\n')
    with pytest.raises(ValueError, match='contiguous'):
        read_sync(sync)


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='requires FFmpeg')
def test_packing_preserves_frame_count_and_irregular_clock(tmp_path):
    source = tmp_path / 'input.zip'
    sync = tmp_path / 'sync.csv'
    output = tmp_path / 'rgb.mp4'
    sync.write_text('1,10,0\n2,43,0\n3,84,0\n')
    with ZipFile(source, 'w') as archive:
        for i in (1, 2, 3):
            ok, encoded = cv2.imencode('.png', np.full((32, 32, 3), i*10, np.uint8))
            assert ok
            archive.writestr(f'recording/rgb-{i:03}.png', encoded.tobytes())
    assert pack_rgb(source, sync, output) == 3
    with pytest.raises(FileExistsError):
        pack_rgb(source, sync, output)
    cap = cv2.VideoCapture(str(output))
    try:
        for i in (1, 2, 3):
            ok, frame = cap.read()
            assert ok
            np.testing.assert_equal(frame, i*10)
        assert not cap.read()[0]
    finally:
        cap.release()
