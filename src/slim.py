"""Filter the Green Spaces GeoJSON into a slim newline-delimited GeoJSON.

The source file is a ~21 MB GeoJSON FeatureCollection; it is parsed as a
stream with ijson for consistency with the sibling projects. Only park-ish
AREA_CLASS values are kept (see config.INCLUDE_AREA_CLASSES); the all-caps
city names are converted to title case. Two outputs are written, one compact
Feature per line: parks-slim.geojsonl (everything kept, used by the gap tool)
and parks-layer.geojsonl (same minus numbered TRCA Lands parcels, the input to
both tile builders).
"""

import json
import os

import ijson

from src import config

# Sanity bounds for the slimmed feature count (~1,750 park-ish polygons).
MIN_EXPECTED = 1_200
MAX_EXPECTED = 3_000


def slim(src_path):
    """Stream the GeoJSON into data/parks-slim.geojsonl.

    Keeps Polygon/MultiPolygon features whose AREA_CLASS is included, with
    `name`, `class` and `area_id` properties. Returns the slim file path.
    Raises if the feature count is implausible.
    """
    print(f"Slimming {src_path} ...")
    os.makedirs(config.DATA_DIR, exist_ok=True)

    count = 0
    layer_count = 0
    skipped = 0
    with open(src_path, "rb") as src, \
            open(config.SLIM_PATH, "w", encoding="utf-8") as out, \
            open(config.LAYER_SLIM_PATH, "w", encoding="utf-8") as layer_out:
        for feature in ijson.items(src, "features.item"):
            props_in = feature.get("properties") or {}
            if props_in.get(config.CLASS_KEY) not in config.INCLUDE_AREA_CLASSES:
                skipped += 1
                continue
            geom = feature.get("geometry") or {}
            if geom.get("type") not in ("Polygon", "MultiPolygon") \
                    or not geom.get("coordinates"):
                skipped += 1
                continue

            props_out = {"class": props_in[config.CLASS_KEY]}
            name = props_in.get(config.NAME_KEY)
            if name:
                props_out["name"] = title_case(str(name).strip())
            area_id = props_in.get(config.AREA_ID_KEY)
            if area_id is not None:
                props_out["area_id"] = int(area_id)

            line = json.dumps({
                "type": "Feature",
                "geometry": {
                    "type": geom["type"],
                    "coordinates": _plain(geom["coordinates"]),
                },
                "properties": props_out,
            }) + "\n"
            out.write(line)
            count += 1
            if not is_trca_lands(name):
                layer_out.write(line)
                layer_count += 1
            if count % 500 == 0:
                print(f"  {count:,} features ...")

    # The landing page counts the parks actually rendered, so it excludes TRCA.
    with open(config.COUNT_PATH, "w", encoding="utf-8") as f:
        f.write(str(layer_count))

    print(f"Done: {config.SLIM_PATH} ({count:,} features, {skipped:,} skipped); "
          f"{config.LAYER_SLIM_PATH} ({layer_count:,} layer features)")
    if not MIN_EXPECTED <= count <= MAX_EXPECTED:
        raise RuntimeError(
            f"Slim feature count {count:,} is outside the expected range "
            f"{MIN_EXPECTED:,}-{MAX_EXPECTED:,} -- aborting."
        )
    return config.SLIM_PATH


def is_trca_lands(name):
    """A numbered "TRCA LANDS (  n)" parcel -- city-tracked TRCA land, not a real
    named park, so it is kept out of the rendered tile layer (the gap tool still
    sees it via the full slim file)."""
    return bool(name) and str(name).strip().upper().startswith("TRCA LANDS")


def title_case(name):
    """Convert an all-caps city name to title case.

    Capitalizes after a space, hyphen, period, slash or opening parenthesis,
    but NOT after an apostrophe ("ST. ANDREW'S" -> "St. Andrew's").
    """
    out = []
    capitalize = True
    for ch in name:
        out.append(ch.upper() if capitalize else ch.lower())
        capitalize = ch in " -./("
    return "".join(out)


def _plain(coords):
    """Recursively convert ijson Decimals to floats for compact json output."""
    if isinstance(coords, list):
        return [_plain(c) for c in coords]
    return float(coords)
