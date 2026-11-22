from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/ml"))
from pr07_pi_validation import Trace, summarize


def test_raw_and_engine_entries_are_distinct():
    trace = Trace(.75)
    trace.observe(1, .8, False)
    trace.observe(2, .9, False)
    trace.observe(3, .5, False)
    trace.observe(4, .9, True)
    trace.observe(4.1, .9, True)
    assert trace.raw == [1, 4]
    assert trace.alerts == [4]
    result = trace.evaluate((3.5, 4.5))
    assert result["engine"]["tp"] == 1
    assert result["raw"]["fp"] == 1
    assert summarize([{"events": result}], "engine")["delay_p50_s"] == pytest.approx(.5)


def test_missing_score_still_counts_as_missed_fall():
    result = Trace(.5).evaluate((2, 3))
    assert result["engine"]["fn"] == 1
    assert result["engine"]["covered"] is False
