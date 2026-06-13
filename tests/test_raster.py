"""Tests for raster helpers (run: python tests\\test_raster.py)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.raster import _ring_centroid


def test_centroid_small_ring_at_large_offset():
    """Regression: a tiny parkette at z17 global pixel coordinates (~1e7).

    The naive shoelace formula loses the centroid to float cancellation;
    Vesta and Dunvegan Parkette labels rendered hundreds of pixels away.
    """
    ox, oy = 9_375_030.0, 12_240_735.0
    square = [(ox, oy), (ox + 38, oy), (ox + 38, oy + 15), (ox, oy + 15)]
    cx, cy = _ring_centroid(square)
    assert abs(cx - (ox + 19)) < 0.01, f"cx off by {cx - (ox + 19):.3f}px"
    assert abs(cy - (oy + 7.5)) < 0.01, f"cy off by {cy - (oy + 7.5):.3f}px"
    print("test_centroid_small_ring_at_large_offset: OK")


def test_centroid_l_shape():
    """Area centroid of an L-shape leans into the thick arm, origin-independent."""
    for ox, oy in ((0.0, 0.0), (9_000_000.0, 12_000_000.0)):
        ring = [(ox, oy), (ox + 20, oy), (ox + 20, oy + 10),
                (ox + 10, oy + 10), (ox + 10, oy + 20), (ox, oy + 20)]
        cx, cy = _ring_centroid(ring)
        assert abs(cx - (ox + 25 / 3)) < 0.01, (ox, cx)
        assert abs(cy - (oy + 25 / 3)) < 0.01, (oy, cy)
    print("test_centroid_l_shape: OK")


if __name__ == "__main__":
    test_centroid_small_ring_at_large_offset()
    test_centroid_l_shape()
