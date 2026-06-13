"""Unit tests for the Web Mercator tile math."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.tilemath import (  # noqa: E402
    TILE_SIZE,
    lonlat_to_pixel,
    lonlat_to_tile,
    pixel_in_tile,
    tile_bounds,
)

# City Hall, Toronto -- a stable reference point well inside the dataset.
TORONTO_LON, TORONTO_LAT = -79.3839, 43.6534


def test_world_center_tile():
    # lon/lat (0, 0) is the world centre; at zoom 1 that is tile (1, 1).
    assert lonlat_to_tile(0.0, 0.0, 1) == (1, 1)


def test_pixel_offsets_within_tile():
    for zoom in (12, 14, 16, 18):
        _, _, ox, oy = pixel_in_tile(TORONTO_LON, TORONTO_LAT, zoom)
        assert 0.0 <= ox < TILE_SIZE
        assert 0.0 <= oy < TILE_SIZE


def test_tile_contains_its_point():
    for zoom in (12, 14, 16, 18):
        tx, ty = lonlat_to_tile(TORONTO_LON, TORONTO_LAT, zoom)
        west, south, east, north = tile_bounds(tx, ty, zoom)
        assert west <= TORONTO_LON <= east
        assert south <= TORONTO_LAT <= north


def test_pixel_and_tile_offset_agree():
    for zoom in (12, 16, 18):
        x, y = lonlat_to_pixel(TORONTO_LON, TORONTO_LAT, zoom)
        tx, ty, ox, oy = pixel_in_tile(TORONTO_LON, TORONTO_LAT, zoom)
        assert abs((tx * TILE_SIZE + ox) - x) < 1e-6
        assert abs((ty * TILE_SIZE + oy) - y) < 1e-6


def test_tile_bounds_ordering():
    west, south, east, north = tile_bounds(1145, 1495, 12)
    assert west < east
    assert south < north


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("All tile-math tests passed.")
