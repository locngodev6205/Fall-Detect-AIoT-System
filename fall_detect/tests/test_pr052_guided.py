import numpy as np

from research.guided_test import image_quality


def test_readiness_requires_non_black_changing_frames():
    dark = np.zeros((48, 64), np.uint8)
    lit = np.full_like(dark, 90)
    changed = np.full_like(dark, 95)
    assert not image_quality([dark]*25)['ready']
    assert not image_quality([lit]*25)['ready']
    assert not image_quality([lit, changed])['ready']
    assert image_quality([lit, changed]*14)['ready']
