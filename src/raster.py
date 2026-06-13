"""Render park polygons into raster (PNG) map tiles using Pillow.

Pure Python -- no native dependencies, runs the same on Windows and Linux.

Each polygon is drawn as a translucent green fill (holes respected via a
per-polygon mask) with a vivid outline in the park's hashed colour (see
_PALETTE) so the outline and the name label are visually linked. Both the
colour assignment (_assign_colors) and label placement run once globally per
zoom, so a seam-straddling outline or label is drawn the same colour and shape
in every tile. The label strategy depends on zoom:

* Low zooms (< LABEL_SHOW_ALL_MIN_ZOOM): a label renders only once its polygon
  is a visible shape (LABEL_MIN_POLY_PX gate) and only if it does not collide
  with an already-placed label (greedy, largest park first). All such labels
  are centred on the polygon. This keeps city-overview zooms uncluttered.
* High zooms (>= LABEL_SHOW_ALL_MIN_ZOOM): every named park is labelled, none
  dropped. A big park's name stays centred; a small park's name (largest bbox
  dimension below LABEL_BELOW_MAX_PX) sits just below the polygon so the text
  never overhangs the shape. Labels that would overlap are nudged straight
  down a line at a time (largest park keeps its spot), so dense parkette
  clusters stack into readable rows instead of printing on top of each other.
"""

import hashlib
import json
import os
from collections import defaultdict

from PIL import Image, ImageDraw, ImageFont

from src import config
from src.tilemath import TILE_SIZE, lonlat_to_pixel

FILL_COLOR = (76, 175, 80, 60)         # translucent green, uniform for all parks
OUTLINE_WIDTH = 2
HALO_COLOR = (255, 255, 255, 235)
FONT_PATH = os.path.join(config.ASSETS_DIR, "font", "DejaVuSans-Bold.ttf")
FONT_SIZE = 11
STROKE_WIDTH = 1                       # white halo width, in pixels

# At this zoom and above, switch from the gated/collision strategy to the
# show-all strategy (every named park labelled; small parks labelled below).
LABEL_SHOW_ALL_MIN_ZOOM = 15

# Show-all strategy: a park whose largest bbox dimension is below this (at the
# current zoom) is "small": its name is placed just below the polygon so the
# text never overhangs the shape. Larger parks keep the centred label.
LABEL_BELOW_MAX_PX = 60                 # largest bbox dimension, in pixels
LABEL_BELOW_GAP_PX = 3                  # polygon bottom edge -> top of the text

# Show-all collision resolution: a label that overlaps an already-placed one is
# pushed straight down until its top clears the conflicting box by this gap.
# Largest park first, so the bigger park keeps its natural spot.
LABEL_STACK_GAP_PX = 2                  # vertical gap left between stacked labels
LABEL_STACK_MAX = 6                     # max nudges before a label is placed anyway

# Gated strategy (low zooms): a name renders once its polygon is a visible
# shape at this zoom; collision placement (largest parks first) keeps dense
# parkette clusters readable.
LABEL_MIN_POLY_PX = 24                  # largest bbox dimension, in pixels
_GRID_CELL = 128                        # spatial-hash cell for collision lookups

# Colour assignment: two parks whose shapes come within this distance are
# treated as neighbours and pushed onto different palette slots when possible.
_COLOR_NEAR_PX = 128

# Park identity is conveyed by colour, as in the sibling addresses layer:
# hash(park name) -> stable hue shared by the outline and the name label.
# Reduced palette: every hue must stay visible over tree canopy on aerial
# imagery, so the addresses layer's green/teal/brown entries are dropped.
# All pass WCAG AA (>=4.5:1) against the white halo.
_PALETTE = (
    (194,  24,  91, 255),   # pink
    (123,  31, 162, 255),   # purple
    ( 25, 118, 210, 255),   # blue
    (211,  47,  47, 255),   # red
)
_FALLBACK_COLOR = (66, 66, 66, 255)    # neutral grey when a name is missing

_index_cache = {}


def _park_index(name):
    """Stable preferred palette index for a park name."""
    cached = _index_cache.get(name)
    if cached is not None:
        return cached
    h = int.from_bytes(hashlib.md5(name.encode("utf-8")).digest()[:4], "big")
    idx = h % len(_PALETTE)
    _index_cache[name] = idx
    return idx


def _assign_colors(features):
    """Map every park to one palette colour for the whole zoom.

    Computed once per zoom rather than per tile, so a park keeps a single
    colour everywhere: a label or outline that straddles a tile seam is drawn
    the same colour on both sides instead of switching mid-word.

    Each park prefers its hashed slot (_park_index). Parks are coloured largest
    first; a park takes its preferred slot unless a nearby already-coloured park
    (shapes within _COLOR_NEAR_PX) already holds it, in which case it shifts to
    the next free slot. With only four slots, a park hemmed in by four
    differently-coloured neighbours keeps its preferred colour.
    """
    grid = defaultdict(list)  # cell -> [(bbox, color_idx), ...]

    def cells(x0, y0, x1, y1):
        for cx in range(int(x0 // _GRID_CELL), int(x1 // _GRID_CELL) + 1):
            for cy in range(int(y0 // _GRID_CELL), int(y1 // _GRID_CELL) + 1):
                yield (cx, cy)

    parks = []
    for name, parts in features:
        if not name:
            continue
        bbox = (min(p[2][0] for p in parts), min(p[2][1] for p in parts),
                max(p[2][2] for p in parts), max(p[2][3] for p in parts))
        area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
        parks.append((area, name, bbox))

    result = {}
    for _area, name, bbox in sorted(
        parks, key=lambda p: (p[0], p[1]), reverse=True
    ):
        if name in result:
            continue
        x0, y0, x1, y1 = bbox
        near = (x0 - _COLOR_NEAR_PX, y0 - _COLOR_NEAR_PX,
                x1 + _COLOR_NEAR_PX, y1 + _COLOR_NEAR_PX)
        used = set()
        for key in cells(*near):
            for ob, oidx in grid.get(key, ()):
                if (near[0] < ob[2] and near[2] > ob[0] and
                        near[1] < ob[3] and near[3] > ob[1]):
                    used.add(oidx)
        preferred = _park_index(name)
        idx = preferred
        for offset in range(len(_PALETTE)):
            cand = (preferred + offset) % len(_PALETTE)
            if cand not in used:
                idx = cand
                break
        result[name] = _PALETTE[idx]
        for key in cells(*bbox):
            grid[key].append((bbox, idx))
    return result


def _color_of(color_map, name):
    """Look up the tile-local colour for a park, with grey fallback."""
    if not name:
        return _FALLBACK_COLOR
    return color_map.get(name, _FALLBACK_COLOR)


def build_raster(slim_path=None):
    """Render PNG tiles for every zoom in config.RASTER_ZOOMS.

    Returns a dict {zoom: tile_count}.
    """
    slim_path = slim_path or config.LAYER_SLIM_PATH
    font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
    return {z: _render_zoom(slim_path, z, font) for z in config.RASTER_ZOOMS}


def _render_zoom(slim_path, zoom, font):
    print(f"Raster z{zoom}: projecting polygons ...")
    features = _read_features(slim_path, zoom)

    labels = (_place_labels(features, font)
              if zoom >= LABEL_SHOW_ALL_MIN_ZOOM
              else _place_labels_gated(features, font))
    color_map = _assign_colors(features)
    print(f"Raster z{zoom}: {len(features):,} polygons, "
          f"{len(labels):,} labels placed")

    print(f"Raster z{zoom}: bucketing into tiles ...")
    poly_tiles = defaultdict(list)
    for name, parts in features:
        for ext, holes, bbox in parts:
            for key in _tiles_touching(bbox):
                poly_tiles[key].append((name, ext, holes))

    label_tiles = defaultdict(list)
    for x, y, name, anchor, box in labels:
        for key in _tiles_touching(box):
            label_tiles[key].append((x, y, name, anchor))

    out_dir = os.path.join(config.RASTER_TILE_DIR, str(zoom))
    keys = set(poly_tiles) | set(label_tiles)
    print(f"Raster z{zoom}: rendering {len(keys):,} tiles ...")

    made_dirs = set()
    written = 0
    for tx, ty in keys:
        img = _render_tile(tx, ty, poly_tiles.get((tx, ty), ()),
                           label_tiles.get((tx, ty), ()), font, color_map)
        if img.getbbox() is None:
            continue  # bbox over-approximation: polygon never entered this tile
        tdir = os.path.join(out_dir, str(tx))
        if tdir not in made_dirs:
            os.makedirs(tdir, exist_ok=True)
            made_dirs.add(tdir)
        img.save(os.path.join(tdir, f"{ty}.png"), optimize=True)
        written += 1
    return written


def _read_features(slim_path, zoom):
    """Return [(name, [(ext_ring, holes, bbox), ...]), ...] in zoom pixels."""
    features = []
    with open(slim_path, encoding="utf-8") as f:
        for line in f:
            feat = json.loads(line)
            geom = feat["geometry"]
            polys = (geom["coordinates"] if geom["type"] == "MultiPolygon"
                     else [geom["coordinates"]])
            parts = []
            for rings in polys:
                projected = [
                    [lonlat_to_pixel(lon, lat, zoom) for lon, lat in ring]
                    for ring in rings
                ]
                ext = projected[0]
                xs = [p[0] for p in ext]
                ys = [p[1] for p in ext]
                bbox = (min(xs), min(ys), max(xs), max(ys))
                parts.append((ext, projected[1:], bbox))
            features.append((feat["properties"].get("name", ""), parts))
    return features


def _place_labels(features, font):
    """High-zoom strategy: label every named park, none dropped.

    Big parks (largest bbox dimension >= LABEL_BELOW_MAX_PX) get the name
    centred on the centroid of their largest part. Small parks get it just
    below the polygon so the text never overhangs the shape.

    Labels are placed largest park first against a spatial hash: one that would
    overlap an already-placed label is nudged straight down (its top clearing
    the conflict by LABEL_STACK_GAP_PX) until it fits, so adjacent parkettes
    stack into rows. Nothing is dropped -- after LABEL_STACK_MAX nudges a label
    is placed where it lands.

    Returns [(x, y, name, anchor, box), ...], where anchor is the Pillow text
    anchor and box is the text's pixel extent (used to bucket it into tiles).
    """
    pad = STROKE_WIDTH
    grid = defaultdict(list)

    def cells(x0, y0, x1, y1):
        for cx in range(int(x0 // _GRID_CELL), int(x1 // _GRID_CELL) + 1):
            for cy in range(int(y0 // _GRID_CELL), int(y1 // _GRID_CELL) + 1):
                yield (cx, cy)

    def conflict_bottom(box):
        """Lowest bottom edge among placed labels overlapping box, else None."""
        x0, y0, x1, y1 = box
        bottom = None
        for key in cells(*box):
            for ox0, oy0, ox1, oy1 in grid.get(key, ()):
                if x0 < ox1 and x1 > ox0 and y0 < oy1 and y1 > oy0:
                    bottom = oy1 if bottom is None else max(bottom, oy1)
        return bottom

    candidates = []
    for name, parts in features:
        if not name:
            continue
        ext, _holes, bbox = max(
            parts, key=lambda p: (p[2][2] - p[2][0]) * (p[2][3] - p[2][1])
        )
        bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
        w = font.getlength(name)
        cx, cy = _ring_centroid(ext)
        if max(bw, bh) >= LABEL_BELOW_MAX_PX:
            x, y, anchor, top = cx, cy, "mm", cy - FONT_SIZE / 2
        else:
            top = bbox[3] + LABEL_BELOW_GAP_PX
            x, y, anchor = cx, top, "ma"
        candidates.append((bw * bh, x, y, top, w, name, anchor))

    labels = []
    for _area, x, y, top, w, name, anchor in sorted(
        candidates, key=lambda c: (c[0], c[1]), reverse=True
    ):
        for _ in range(LABEL_STACK_MAX + 1):
            box = (x - w / 2 - pad, top - pad,
                   x + w / 2 + pad, top + FONT_SIZE + pad)
            bottom = conflict_bottom(box)
            if bottom is None:
                break
            new_top = bottom + LABEL_STACK_GAP_PX + pad
            y += new_top - top
            top = new_top
        for key in cells(*box):
            grid[key].append(box)
        labels.append((x, y, name, anchor, box))
    return labels


def _place_labels_gated(features, font):
    """Low-zoom strategy: one centred label per visible, non-colliding park.

    A label whose polygon is still too small to see at this zoom
    (LABEL_MIN_POLY_PX), or that collides with an already-placed label, is
    dropped. Greedy, largest park first, against a spatial hash so seam-
    straddling labels render identically in every tile.

    Returns [(x, y, name, anchor, box), ...]; anchor is always "mm" (centred).
    """
    grid = defaultdict(list)

    def cells(x0, y0, x1, y1):
        for cx in range(int(x0 // _GRID_CELL), int(x1 // _GRID_CELL) + 1):
            for cy in range(int(y0 // _GRID_CELL), int(y1 // _GRID_CELL) + 1):
                yield (cx, cy)

    def collides(box):
        x0, y0, x1, y1 = box
        for key in cells(*box):
            for ox0, oy0, ox1, oy1 in grid.get(key, ()):
                if x0 < ox1 and x1 > ox0 and y0 < oy1 and y1 > oy0:
                    return True
        return False

    candidates = []
    for name, parts in features:
        if not name:
            continue
        ext, _holes, bbox = max(
            parts, key=lambda p: (p[2][2] - p[2][0]) * (p[2][3] - p[2][1])
        )
        bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
        if max(bw, bh) < LABEL_MIN_POLY_PX:
            continue
        w = font.getlength(name)
        cx, cy = _ring_centroid(ext)
        candidates.append((bw * bh, cx, cy, name, w))

    labels = []
    for _area, cx, cy, name, w in sorted(candidates, reverse=True):
        pad = STROKE_WIDTH
        box = (cx - w / 2 - pad, cy - FONT_SIZE / 2 - pad,
               cx + w / 2 + pad, cy + FONT_SIZE / 2 + pad)
        if collides(box):
            continue
        for key in cells(*box):
            grid[key].append(box)
        labels.append((cx, cy, name, "mm", box))
    return labels


def _ring_centroid(ring):
    """Area centroid of a closed ring; falls back to the vertex mean.

    The ring is translated to a local origin first: global pixel coordinates
    run into the millions at high zooms, and the raw shoelace cross-products
    lose all precision to float cancellation on small polygons.
    """
    rx, ry = ring[0]
    a = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
        x0, y0, x1, y1 = x0 - rx, y0 - ry, x1 - rx, y1 - ry
        cross = x0 * y1 - x1 * y0
        a += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if abs(a) < 1e-9:
        return (sum(p[0] for p in ring) / len(ring),
                sum(p[1] for p in ring) / len(ring))
    return cx / (3 * a) + rx, cy / (3 * a) + ry


def _tiles_touching(bbox, pad=OUTLINE_WIDTH + STROKE_WIDTH):
    x0, y0, x1, y1 = bbox
    for tx in range(int((x0 - pad) // TILE_SIZE), int((x1 + pad) // TILE_SIZE) + 1):
        for ty in range(int((y0 - pad) // TILE_SIZE), int((y1 + pad) // TILE_SIZE) + 1):
            yield (tx, ty)


def _render_tile(tx, ty, polys, labels, font, color_map):
    img = Image.new("RGBA", (TILE_SIZE, TILE_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    ox, oy = tx * TILE_SIZE, ty * TILE_SIZE

    def local(ring):
        return [(x - ox, y - oy) for x, y in ring]

    # Fills first (via a mask so holes stay clear), then all outlines on top.
    for _name, ext, holes in polys:
        mask = Image.new("L", (TILE_SIZE, TILE_SIZE), 0)
        mdraw = ImageDraw.Draw(mask)
        mdraw.polygon(local(ext), fill=255)
        for hole in holes:
            mdraw.polygon(local(hole), fill=0)
        img.paste(FILL_COLOR, (0, 0), mask)

    for name, ext, holes in polys:
        for ring in (ext, *holes):
            pts = local(ring)
            draw.line(pts + pts[:1], fill=_color_of(color_map, name),
                      width=OUTLINE_WIDTH)

    for x, y, name, anchor in labels:
        draw.text(
            (x - ox, y - oy), name, font=font, fill=_color_of(color_map, name),
            stroke_width=STROKE_WIDTH, stroke_fill=HALO_COLOR, anchor=anchor,
        )

    return img
