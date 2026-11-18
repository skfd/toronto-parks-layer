"""Web Mercator (XYZ slippy-map) coordinate helpers. Tile size is 256 px.

They are layerkit's; this module keeps the name the rest of the layer imports.
"""

from layerkit.tilemath import (  # noqa: F401
    TILE_SIZE,
    lonlat_to_pixel,
    lonlat_to_tile,
    pixel_in_tile,
    tile_bounds,
)
