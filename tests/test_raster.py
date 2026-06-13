"""Tests for raster helpers (run: python tests\\test_raster.py)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import ImageFont

from src.raster import (
    FONT_PATH, FONT_SIZE, _assign_colors, _park_index, _place_labels,
    _ring_centroid,
)


def _boxes_overlap(a, b):
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


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


def test_show_all_labels_do_not_overlap():
    """Regression: adjacent small parkettes whose below-labels share a line.

    Glasgow Street Parkette and Julius Deutsch Park sat side by side at z16,
    so their (wider-than-the-polygon) below-labels printed on top of each
    other -- "Glasgow Street Parkettech Park". _place_labels must nudge the
    smaller park's label down a row instead of overprinting.
    """
    font = ImageFont.truetype(FONT_PATH, FONT_SIZE)

    def square(x, y, w, h):
        return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]

    features = [
        ("Glasgow Street Parkette", [(square(4688369, 6122693, 10, 14), [],
                                      (4688369, 6122693, 4688379, 6122707))]),
        ("Julius Deutsch Park", [(square(4688418, 6122693, 36, 17), [],
                                  (4688418, 6122693, 4688454, 6122710))]),
    ]
    boxes = [box for _x, _y, _name, _anchor, box in _place_labels(features, font)]
    assert not _boxes_overlap(boxes[0], boxes[1]), boxes
    print("test_show_all_labels_do_not_overlap: OK")


def test_color_assignment_is_global_and_unique_per_park():
    """Regression: 'Trinity Square' rendered two-tone across a tile seam.

    Colour was assigned per tile, so a park straddling a seam could shift slot
    in one tile but not the next, splitting its label mid-word. _assign_colors
    must give each park exactly one colour for the whole zoom, and still push
    two adjacent same-preferred parks onto different slots.
    """
    def square(x, y, w, h):
        return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]

    def part(x, y, w, h):
        return (square(x, y, w, h), [], (x, y, x + w, y + h))

    # Alpha Park and Gamma Park both prefer palette slot 0; placed adjacent.
    assert _park_index("Alpha Park") == _park_index("Gamma Park")
    features = [
        ("Alpha Park", [part(1000, 1000, 80, 60)]),
        ("Gamma Park", [part(1100, 1000, 40, 30)]),
    ]
    colors = _assign_colors(features)
    assert colors["Alpha Park"] != colors["Gamma Park"], colors
    assert set(colors) == {"Alpha Park", "Gamma Park"}, colors
    print("test_color_assignment_is_global_and_unique_per_park: OK")


if __name__ == "__main__":
    test_centroid_small_ring_at_large_offset()
    test_centroid_l_shape()
    test_show_all_labels_do_not_overlap()
    test_color_assignment_is_global_and_unique_per_park()
