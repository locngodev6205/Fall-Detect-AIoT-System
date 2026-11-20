import csv
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.ml.pilot_frame_match import align, map_segments


def test_strided_alignment_separates_offset_from_stride():
    rng = np.random.default_rng(23)
    raw = rng.normal(size=(100, 80))
    raw /= np.linalg.norm(raw, axis=1, keepdims=True)
    clip = raw[11:75:4]
    result = align(clip, raw, (1, 4))
    assert result['stride'] == 4 and result['offset_zero_based'] == 11
    assert result['p95_local_best_frame_displacement'] == 0
    assert result['mean_cosine_error'] < 1e-8


def test_map_segments_does_not_join_two_falls_and_tracks_truncation(tmp_path):
    (tmp_path / 'camera_delay_corrected.csv').write_text('scenario_id,camera_id,delay_frames\n4,6,82\n')
    (tmp_path / 'segments_corrected.csv').write_text(
        'scenario_id,reference_camera,start_frame,end_frame,position_code\n'
        '4,6,230,287,1\n4,6,288,314,2\n4,6,601,638,2\n4,6,639,780,3\n'
    )
    mapping = {'offset_zero_based':320,'stride':4,'mean_cosine_error':.00005,
               'next_distinct_candidate':[.01,4,324],'p95_local_best_frame_displacement':0}
    result = map_segments(mapping,120,120,tmp_path,4,6)
    falls = [r for r in result['segments'] if r['position_code']==2]
    assert len(falls)==2 and all(row['fully_visible_in_clip'] for row in falls)
    assert falls[0]['clip_seconds'] == pytest.approx([50/120,76/120])
    assert falls[1]['clip_seconds'] == pytest.approx([363/120,400/120])
    assert not result['segments'][0]['fully_visible_in_clip']
    assert not result['segments'][-1]['fully_visible_in_clip']
    with pytest.raises(ValueError, match='too ambiguous'):
        map_segments({**mapping,'next_distinct_candidate':[.0001,4,324]},120,120,tmp_path,4,6)
