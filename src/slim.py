"""Filter the Green Spaces GeoJSON into a slim newline-delimited GeoJSON.

The source file is a ~21 MB GeoJSON FeatureCollection; it is parsed as a
stream with ijson for consistency with the sibling projects. Only park-ish
AREA_CLASS values are kept (see config.INCLUDE_AREA_CLASSES); the all-caps
city names are converted to title case. The slim output (one compact Feature
per line) is the shared input to both tile builders.
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
    skipped = 0
    with open(src_path, "rb") as src, \
            open(config.SLIM_PATH, "w", encoding="utf-8") as out:
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

            out.write(json.dumps({
                "type": "Feature",
                "geometry": {
                    "type": geom["type"],
                    "coordinates": _plain(geom["coordinates"]),
                },
                "properties": props_out,
            }) + "\n")
            count += 1
            if count % 500 == 0:
                print(f"  {count:,} features ...")

    with open(config.COUNT_PATH, "w", encoding="utf-8") as f:
        f.write(str(count))

    print(f"Done: {config.SLIM_PATH} ({count:,} features, {skipped:,} skipped)")
    if not MIN_EXPECTED <= count <= MAX_EXPECTED:
        raise RuntimeError(
            f"Slim feature count {count:,} is outside the expected range "
            f"{MIN_EXPECTED:,}-{MAX_EXPECTED:,} -- aborting."
        )
    return config.SLIM_PATH


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
