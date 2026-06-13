"""Web Mercator (XYZ slippy-map) coordinate helpers. Tile size is 256 px."""

import math

TILE_SIZE = 256


def lonlat_to_pixel(lon, lat, zoom):
    """Convert lon/lat to global pixel coordinates at the given zoom."""
    scale = TILE_SIZE * (2 ** zoom)
    x = (lon + 180.0) / 360.0 * scale
    siny = math.sin(math.radians(lat))
    siny = min(max(siny, -0.9999), 0.9999)
    y = (0.5 - math.log((1 + siny) / (1 - siny)) / (4 * math.pi)) * scale
    return x, y


def lonlat_to_tile(lon, lat, zoom):
    """Return the (tile_x, tile_y) containing the given lon/lat."""
    x, y = lonlat_to_pixel(lon, lat, zoom)
    return int(x // TILE_SIZE), int(y // TILE_SIZE)


def pixel_in_tile(lon, lat, zoom):
    """Return (tile_x, tile_y, offset_x, offset_y) for a lon/lat.

    offset_x / offset_y are pixel positions in [0, 256) inside that tile.
    """
    x, y = lonlat_to_pixel(lon, lat, zoom)
    tx, ty = int(x // TILE_SIZE), int(y // TILE_SIZE)
    return tx, ty, x - tx * TILE_SIZE, y - ty * TILE_SIZE


def tile_bounds(tx, ty, zoom):
    """Return (west, south, east, north) lon/lat bounds of a tile."""
    n = 2 ** zoom
    west = tx / n * 360.0 - 180.0
    east = (tx + 1) / n * 360.0 - 180.0
    north = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * ty / n))))
    south = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (ty + 1) / n))))
    return west, south, east, north
