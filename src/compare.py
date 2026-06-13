"""Compare the City Green Spaces polygons against OSM park areas.

Pulls park-like areas from OpenStreetMap (Overpass) within Toronto, then for
each kept City polygon checks whether an OSM area overlaps it. The result is
written to data/gaps.geojson:

  * "missing"  -- no OSM park area overlaps the City polygon (add it to OSM);
  * "mismatch" -- one overlaps, but the OSM name differs from the City name
                  (or the OSM area is unnamed).

Overlap is tested with pure-Python centroid-in-polygon checks (both
directions) after a bounding-box prefilter -- enough for a review tool, no GIS
dependency. A flaky Overpass falls back to the cached response.
"""

import json
import os
import re

import requests

from src import config


def compare():
    """Build data/gaps.geojson + summary from City vs OSM. Returns the summary."""
    rings = _osm_rings(_load_osm())
    print(f"OSM park-area rings: {len(rings):,}")
    city = list(_city_features())
    print(f"City polygons:       {len(city):,}")

    gaps, n_missing, n_mismatch = _match(city, rings)
    _write_gaps(gaps)

    summary = {
        "osm_rings": len(rings),
        "city": len(city),
        "missing": n_missing,
        "mismatch": n_mismatch,
    }
    with open(config.GAPS_COUNT_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"Gaps: {n_missing:,} missing in OSM, {n_mismatch:,} name mismatches")
    return summary


# --- OSM source -------------------------------------------------------------

def _overpass_query():
    s, w, n, e = config.TORONTO_BBOX
    bbox = f"{s},{w},{n},{e}"
    parts = []
    for key, values in config.OSM_AREA_TAGS.items():
        rx = "|".join(values)
        parts.append(f'  way["{key}"~"^({rx})$"]({bbox});')
        parts.append(f'  relation["{key}"~"^({rx})$"]({bbox});')
    return "[out:json][timeout:180];\n(\n" + "\n".join(parts) + "\n);\nout tags geom;"


def _load_osm():
    """Fetch park areas from Overpass, caching the raw response; fall back to cache."""
    query = _overpass_query()
    try:
        print("Querying Overpass for OSM park areas ...")
        resp = requests.post(
            config.OVERPASS_URL,
            data={"data": query},
            headers={"User-Agent": config.USER_AGENT},
            timeout=300,
        )
        resp.raise_for_status()
        data = resp.json()
        with open(config.OSM_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f)
        return data
    except (requests.RequestException, ValueError) as e:
        print(f"Warning: Overpass fetch failed ({e}).")
        if os.path.isfile(config.OSM_CACHE_PATH):
            print("Using cached OSM data.")
            with open(config.OSM_CACHE_PATH, encoding="utf-8") as f:
                return json.load(f)
        raise


def _osm_rings(data):
    """Flatten OSM ways and relation outer members into matchable rings."""
    rings = []
    for el in data.get("elements", []):
        name = (el.get("tags") or {}).get("name")
        if el.get("type") == "way":
            rings.append(_make_ring(el.get("geometry"), name, "way", el["id"]))
        elif el.get("type") == "relation":
            for m in el.get("members", []):
                if m.get("type") == "way" and m.get("role") in ("outer", ""):
                    rings.append(
                        _make_ring(m.get("geometry"), name, "relation", el["id"])
                    )
    return [r for r in rings if r]


def _make_ring(geom, name, otype, oid):
    if not geom:
        return None
    pts = [(p["lon"], p["lat"]) for p in geom if "lon" in p and "lat" in p]
    if len(pts) < 3:
        return None
    return {
        "pts": pts,
        "name": name,
        "otype": otype,
        "oid": oid,
        "bbox": _bbox(pts),
        "centroid": _centroid(pts),
    }


# --- City source ------------------------------------------------------------

def _city_features():
    with open(config.SLIM_PATH, encoding="utf-8") as f:
        for line in f:
            feat = json.loads(line)
            outers = _outer_rings(feat["geometry"])
            if not outers:
                continue
            allpts = [p for ring in outers for p in ring]
            props = feat.get("properties") or {}
            yield {
                "name": props.get("name"),
                "cls": props.get("class"),
                "area_id": props.get("area_id"),
                "geom": feat["geometry"],
                "outers": outers,
                "bbox": _bbox(allpts),
                "centroid": _centroid(max(outers, key=_ring_area)),
            }


def _outer_rings(geom):
    """Outer ring(s) as lists of (lon, lat). Polygon -> 1, MultiPolygon -> many."""
    coords = geom.get("coordinates")
    if not coords:
        return []
    if geom["type"] == "Polygon":
        return [[tuple(p) for p in coords[0]]]
    if geom["type"] == "MultiPolygon":
        return [[tuple(p) for p in poly[0]] for poly in coords if poly]
    return []


# --- Matching ---------------------------------------------------------------

def _match(city, rings):
    gaps = []
    n_missing = n_mismatch = 0
    for c in city:
        match = _find_match(c, rings)
        if match is None:
            gaps.append(_gap_feature(c, "missing", None))
            n_missing += 1
        elif _norm(match["name"]) != _norm(c["name"]):
            gaps.append(_gap_feature(c, "mismatch", match))
            n_mismatch += 1
    return gaps, n_missing, n_mismatch


def _find_match(c, rings):
    """An OSM ring overlapping the City polygon, preferring a same-named one."""
    cnorm = _norm(c["name"])
    best = None
    for r in rings:
        if not _bbox_overlap(c["bbox"], r["bbox"]):
            continue
        if _point_in_ring(c["centroid"], r["pts"]) or any(
            _point_in_ring(r["centroid"], outer) for outer in c["outers"]
        ):
            if cnorm and _norm(r["name"]) == cnorm:
                return r  # exact name match settles it
            if best is None or (r["name"] and not best["name"]):
                best = r  # otherwise prefer a named ring over an unnamed one
    return best


def _gap_feature(c, status, match):
    props = {
        "name": c["name"],
        "class": c["cls"],
        "status": status,
        "area_id": c["area_id"],
    }
    if status == "mismatch" and match:
        props["osm_name"] = match["name"]
        props["osm_url"] = (
            f"https://www.openstreetmap.org/{match['otype']}/{match['oid']}"
        )
    return {
        "type": "Feature",
        "properties": props,
        "geometry": _round_geom(c["geom"]),
    }


def _write_gaps(gaps):
    with open(config.GAPS_GEOJSON_PATH, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": gaps}, f)


# --- Geometry helpers -------------------------------------------------------

def _bbox(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def _bbox_overlap(a, b):
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def _centroid(pts):
    """Area-weighted polygon centroid (shoelace); mean for degenerate rings."""
    n = len(pts)
    area = cx = cy = 0.0
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        cross = x0 * y1 - x1 * y0
        area += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if area == 0:
        return (sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n)
    area *= 0.5
    return (cx / (6 * area), cy / (6 * area))


def _ring_area(pts):
    n = len(pts)
    area = 0.0
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        area += x0 * y1 - x1 * y0
    return abs(area) / 2


def _point_in_ring(pt, pts):
    """Ray-casting point-in-polygon test."""
    x, y = pt
    n = len(pts)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if (yi > y) != (yj > y):
            xint = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < xint:
                inside = not inside
        j = i
    return inside


def _norm(name):
    """Loose name key: lowercase, alphanumerics only, single-spaced."""
    if not name:
        return ""
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def _round_geom(geom):
    return {"type": geom["type"], "coordinates": _round(geom["coordinates"])}


def _round(c):
    if isinstance(c, (int, float)):
        return round(c, 5)  # ~1 m -- ample for a reference outline, smaller file
    return [_round(x) for x in c]
