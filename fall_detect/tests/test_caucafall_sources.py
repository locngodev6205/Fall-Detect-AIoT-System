from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.ml.caucafall_sources import annotation_for, pilot_development_sources


def segment(start, end, label, subject='4'):
    return dict(dataset='caucafall', subject=subject, cam='1',
                start=start, end=end, label=label)


def test_fall_uses_transition_and_excludes_fallen_interval():
    rows = [segment(0, 1, 8), segment(1, 2, 1), segment(2, 5, 2)]
    assert annotation_for(rows, 'Fall forward', '4', 4.95, .05) == ('fall', 1, 2)
    with pytest.raises(ValueError, match='Subject or camera'):
        annotation_for(rows, 'Fall forward', '5', 4.95, .05)
    with pytest.raises(ValueError, match='ADL disagrees'):
        annotation_for(rows, 'Kneel', '4', 4.95, .05)


def test_adl_retains_hard_negative_and_rejects_wrong_timeline():
    rows = [segment(0, 2, 0), segment(2, 5, 3)]
    assert annotation_for(rows, 'Sit down', '4', 4.95, .05) == ('no_fall', None, None)
    with pytest.raises(ValueError, match='timeline'):
        annotation_for(rows, 'Sit down', '4', 4, .05)
    with pytest.raises(ValueError, match='gap/overlap'):
        annotation_for([segment(0, 1, 0), segment(2, 5, 3)], 'Kneel', '4', 4.95, .05)


def test_pilot_holdout_and_duplicate_do_not_enter_new_manifest():
    assert pilot_development_sources({'sources': [
        {'split': 'test'},
        {'split': 'train', 'duplicate_of': 'original'},
    ]}) == []
