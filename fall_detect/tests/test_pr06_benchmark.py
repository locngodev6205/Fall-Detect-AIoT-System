import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/ml"))
from pr06_benchmark import score_result, summarize


def test_missing_predictions_are_reported_separately():
    record = dict(wall_ms=120, label=1)
    rows = [dict(record, **score_result(None, False, 0)),
            dict(record, **score_result(0.7, True, 3)),
            dict(record, label=0, **score_result(0.6, True, 4)),
            dict(record, label=0, **score_result(0.2, False, 4))]
    result = summarize(rows)
    assert result["scored"] == 3
    assert result["no_prediction_fall"] == 1
    assert result["tp"] == result["fp"] == result["tn"] == 1
    assert result["fn"] == 0
    assert result["f2"] == pytest.approx(5/6)


def test_non_finite_scores_are_rejected():
    with pytest.raises(ValueError, match="Non-finite"):
        score_result(float("nan"), False, 2)


def test_absence_of_scored_fall_is_insufficient():
    result = summarize([dict(score_result(0.1, False, 1), label=0, wall_ms=1)])
    assert result["status"] == "NOT_ENOUGH_EVALUATION_DATA"
    assert result["recall"] is None
