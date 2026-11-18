"""Compare the City Green Spaces polygons against OSM park areas.

Pulls park-like areas from OpenStreetMap (Overpass) within Toronto, then for
each kept City polygon checks whether an OSM area covers it. The result is
written to data/gaps.geojson:

  * "missing"  -- no OSM park area overlaps the City polygon (add it to OSM);
  * "mismatch" -- one overlaps, but its (present) OSM name differs;
  * "unnamed"  -- one overlaps but the OSM area has no name (add one);
  * "retag"    -- one overlaps but it is tagged both leisure=park and
                  landuse=recreation_ground (drop the landuse);
  * "trca"     -- a numbered TRCA Lands parcel that is any of the above; these
                  are not real park names, so they get their own category.

Parks that pass all of that can still land in the file as "review": the names
agree but the outlines do not. That is a prompt to compare two shapes, not a
gap -- see _reviews.

Overlap is the area two polygons really share, measured with shapely after a
bounding-box prefilter -- see _find_match for why a centre-point test is not
enough. A flaky Overpass falls back to the cached response, but only after
every mirror has been tried several times -- see _load_osm.
"""

import json
import math
import re
import time
from datetime import date, datetime, timedelta, timezone

import requests
from layerkit.geom import bbox_overlap as _bbox_overlap
from layerkit.geom import relation_outer_loops as _relation_outer_loops
from layerkit import overpass
# Raised by overpass.load_osm; callers and tests name it as compare's.
from layerkit.overpass import OsmUnavailable  # noqa: F401
from shapely import make_valid
from shapely.geometry import Polygon, mapping, shape
from shapely.ops import unary_union

from src import config, history


def compare():
    """Build data/gaps.geojson + summary from City vs OSM. Returns the summary."""
    data, osm_date, from_cache = _load_osm()
    rings = _osm_rings(data)
    print(f"OSM park-area rings: {len(rings):,}")
    city = list(_city_features())
    print(f"City polygons:       {len(city):,}")

    gaps, counts = _match(city, rings)
    reviews = _reviews(city, rings, gaps)
    _write_gaps(gaps + reviews)

    summary = {"osm_rings": len(rings), "city": len(city),
               "osm_date": osm_date, "osm_stale": from_cache,
               "review": len(reviews), **counts}
    with open(config.GAPS_COUNT_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(
        f"Gaps: {counts['missing']:,} missing, {counts['mismatch']:,} mismatch, "
        f"{counts['unnamed']:,} unnamed OSM, {counts['retag']:,} to retag, "
        f"{counts['trca']:,} TRCA; {len(reviews):,} worth a look"
    )
    if from_cache:
        print(f"NOTE: compared against cached OSM data from {osm_date}, "
              f"not a live Overpass fetch.")
    history.record(summary)
    return summary


# --- OSM source -------------------------------------------------------------

def _overpass_query(at=None):
    """The Overpass QL for park-like areas; ``at`` (ISO instant) asks for OSM
    as it stood then -- an attic query, used by the history backfill."""
    s, w, n, e = config.TORONTO_BBOX
    bbox = f"{s},{w},{n},{e}"
    parts = []
    for key, values in config.OSM_AREA_TAGS.items():
        rx = "|".join(values)
        parts.append(f'  way["{key}"~"^({rx})$"]({bbox});')
        parts.append(f'  relation["{key}"~"^({rx})$"]({bbox});')
    # "out geom" (body verbosity) so RELATIONS carry their members + geometry;
    # "out tags geom" would strip member lists and silently drop every relation.
    settings = "[out:json][timeout:180]"
    if at:
        settings += f'[date:"{at}"]'
    return settings + ";\n(\n" + "\n".join(parts) + "\n);\nout geom;"


def _load_osm():
    """Return (data, data_date, from_cache) for OSM park areas.

    The fetch -- every mirror, the list retried, then the cache -- is
    layerkit.overpass.load_osm; the reasons for each rule are written there.

    What this layer keeps for itself is the date: the day of the OSM data the
    reply holds, which is what the page prints and the history records.
    """
    data, _base, from_cache = overpass.load_osm(
        _overpass_query(), what="park areas",
        urls=config.OVERPASS_URLS, rounds=config.OVERPASS_ROUNDS,
        round_wait=config.OVERPASS_ROUND_WAIT,
        cache_path=config.OSM_CACHE_PATH, fetch_path=config.OSM_FETCH_PATH,
        try_one=_try_overpass, undated=None)
    if from_cache:
        return data, _data_date(data) or _cache_date(), True
    return data, _data_date(data) or date.today().isoformat(), False


def _try_overpass(url, query):
    """One attempt at one mirror; None if it failed or answered implausibly."""
    return overpass.try_overpass(
        url, query, user_agent=config.USER_AGENT,
        timeout=config.OVERPASS_TIMEOUT,
        min_elements=config.OSM_MIN_ELEMENTS,
        max_age_days=config.OSM_MAX_AGE_DAYS,
        # This layer still accepts a reply that carries no timestamp_osm_base,
        # as it always has. Every sibling refuses one; dropping this line makes
        # this layer do the same (its tests' GOOD reply is undated).
        allow_undated=True)


def _load_cache():
    """(data, data_date) for the cached Overpass reply, or None.

    Dated by the OSM data it holds, not by when it was fetched: a reply fetched
    yesterday from a lagging mirror is still May's OSM, and the page prints
    this date as the one the diff is against.
    """
    cached = overpass.load_cache(config.OSM_CACHE_PATH, config.OSM_FETCH_PATH)
    if cached is None:
        return None
    data, when = cached
    return data, _data_date(data) or when


def _osm_base(data):
    """The reply's own osm3s.timestamp_osm_base -- the last minutely diff the
    answering instance had applied -- as an aware datetime, or None."""
    return overpass.osm_base_time(data)


def _data_date(data):
    base = _osm_base(data)
    return base.date().isoformat() if base else None


def _cache_date():
    """How current the cached reply is: the sidecar, else the file's mtime."""
    return overpass.cache_date(config.OSM_CACHE_PATH, config.OSM_FETCH_PATH)


def _osm_rings(data):
    """Flatten OSM ways and relation outer members into matchable rings."""
    rings = []
    for el in data.get("elements", []):
        tags = el.get("tags") or {}
        if el.get("type") == "way":
            rings.append(_make_ring(el.get("geometry"), tags, "way", el["id"]))
        elif el.get("type") == "relation":
            for loop in _relation_outer_loops(el):
                rings.append(_make_ring(loop, tags, "relation", el["id"]))
    return [r for r in rings if r]


def _make_ring(geom, tags, otype, oid):
    if not geom:
        return None
    pts = [(p["lon"], p["lat"]) for p in geom if "lon" in p and "lat" in p]
    if len(pts) < 3:
        return None
    outline = _valid(Polygon(pts))
    if outline.is_empty:
        return None
    return {
        "shape": outline,
        "name": tags.get("name"),
        "allotment": tags.get("landuse") == "allotments",
        "double_tagged": (tags.get("leisure") == "park"
                          and tags.get("landuse") == "recreation_ground"),
        "otype": otype,
        "oid": oid,
        "bbox": outline.bounds,
    }


# --- City source ------------------------------------------------------------

def _city_features():
    with open(config.SLIM_PATH, encoding="utf-8") as f:
        for line in f:
            feat = json.loads(line)
            outline = _valid(shape(feat["geometry"]))
            if outline.is_empty:
                continue
            props = feat.get("properties") or {}
            yield {
                "name": props.get("name"),
                "cls": props.get("class"),
                "area_id": props.get("area_id"),
                "geom": feat["geometry"],
                "shape": outline,
                "bbox": outline.bounds,
            }


# --- Matching ---------------------------------------------------------------

def _match(city, rings):
    gaps = []
    counts = {"missing": 0, "mismatch": 0, "unnamed": 0, "retag": 0, "trca": 0}
    for c in city:
        match = _find_match(c, rings)
        if match is None:
            status = "missing"
        elif match["double_tagged"]:
            status = "retag"  # first, and any name gap shows up once it is fixed
        elif not match["name"]:
            status = "unnamed"
        elif _norm(match["name"]) != _norm(c["name"]):
            status = "mismatch"
        else:
            continue  # an OSM area with the same name overlaps -- not a gap
        if _is_trca(c["name"]):
            status = "trca"
        gaps.append(_gap_feature(c, status, match))
        counts[status] += 1
    return gaps, counts


def _is_trca(name):
    """Numbered TRCA Lands parcel ("Trca Lands ( 39)") -- not a real park name."""
    return _norm(name).startswith("trca lands")


def _is_garden(c):
    """A City polygon an allotment can stand in for.

    The City has no garden class: its allotments are "Open Green Space" with
    "Allotment Gardens" or "Garden Plots" in the name.
    """
    return c["cls"] == "Open Green Space" or bool(_GARDEN_NAME.search(c["name"] or ""))


def _find_match(c, rings):
    """The OSM ring that matches the City polygon, or None.

    Decided by the area the polygons really share. Testing centre points instead
    fails both ways: a park wrapped around a corner has its centre outside its
    own outline, and a tennis club's centre sits inside the park around it, so
    the club passes while the park does not.

    A same-named ring settles it at any overlap, and even at none if the bboxes
    touch. Otherwise OSM has to cover MIN_OVERLAP_SHARE of the City polygon, and
    the ring covering the most of it is the match.
    """
    cnorm = _norm(c["name"])
    garden = _is_garden(c)
    area = c["shape"].area
    best = None
    best_share = covered = 0.0
    name_fallback = None
    for r in rings:
        if not _bbox_overlap(c["bbox"], r["bbox"]):
            continue
        if r["allotment"] and not garden:
            continue  # a community plot inside a park is not that park
        share = c["shape"].intersection(r["shape"]).area / area
        if bool(cnorm) and _norm(r["name"]) == cnorm:
            if share > 0:
                return r  # exact name match settles it
            if name_fallback is None:
                name_fallback = r
        covered += share
        if share > best_share:
            best, best_share = r, share
    if name_fallback:
        return name_fallback
    return best if covered >= config.MIN_OVERLAP_SHARE else None


# --- Worth a look -----------------------------------------------------------

def _reviews(city, rings, gaps):
    """Features for matched parks whose outlines disagree, most disputed first.

    Kept apart from _match on purpose. A gap is something to fix; this is only a
    reason to look, because the City and OSM can both be right about a park's
    extent. Reviewed on 2026-11-04: of the 20 worst, 16 looked like OSM problems
    and 4 were two fair ideas of one park, and no test here tells them apart. So
    these stay out of the gap counts and the history chart, which is the record
    of work going down, and false flags are accepted.
    """
    flagged = {g["properties"]["area_id"] for g in gaps}
    rows = {}
    for c in city:
        if c["area_id"] in flagged or not c["name"] or _is_trca(c["name"]):
            continue
        row = _review(c, city, rings)
        if row:
            rows[row["properties"]["name"], row["properties"]["osm_url"]] = row
    rows = list(rows.values())
    rows.sort(key=lambda f: -f["properties"]["disputed_ha"])
    return rows


def _review(c, city, rings):
    """The review feature for one matched City park, or None if it is fine.

    A park the City holds as several polygons is judged whole, or each half of
    a golf club looks like it shares little with the club's one OSM outline.
    """
    cnorm = _norm(c["name"])
    same = [r for r in rings
            if _bbox_overlap(c["bbox"], r["bbox"]) and _norm(r["name"]) == cnorm]
    if not same:
        return None
    osm = unary_union([r["shape"] for r in same])
    whole = unary_union([d["shape"] for d in city if d["name"] == c["name"]
                         and _bbox_overlap(d["bbox"], osm.bounds)])
    c = {**c, "shape": whole, "bbox": whole.bounds, "geom": mapping(whole)}
    shared = whole.intersection(osm).area
    combined = whole.area + osm.area - shared
    lat = (c["bbox"][1] + c["bbox"][3]) / 2
    disputed_ha = _hectares(combined - shared, lat)

    reasons = [f"OSM area also covers {name}"
               for name in _parks_covered(osm, cnorm, city, lat)]
    reasons += [f"Mostly inside OSM's {name}"
                for name in _osm_owners(c, shared, cnorm, rings, lat)]
    if (shared / combined < config.REVIEW_MAX_OVERLAP
            and disputed_ha >= config.REVIEW_MIN_DISPUTED_HA):
        reasons.append("Little shared area")
    if not reasons:
        return None

    match = max(same, key=lambda r: whole.intersection(r["shape"]).area)
    feature = _gap_feature(c, "review", match)
    feature["properties"].update({
        "reasons": reasons,
        "city_ha": round(_hectares(whole.area, lat), 1),
        "osm_ha": round(_hectares(osm.area, lat), 1),
        "shared_pct": round(100 * shared / combined),
        "disputed_ha": round(disputed_ha, 1),
        "osm_geom": _round_geom(mapping(osm)),
    })
    return feature


def _parks_covered(osm, cnorm, city, lat):
    """Other named City parks that the same-named OSM area mostly covers."""
    names = set()
    for d in city:
        if (not d["name"] or _is_trca(d["name"])
                or not _bbox_overlap(d["bbox"], osm.bounds)
                or _norm(d["name"]) == cnorm):
            continue
        area = d["shape"].area
        if _hectares(area, lat) < config.REVIEW_MIN_NEIGHBOUR_HA:
            continue
        if d["shape"].intersection(osm).area / area >= config.REVIEW_COVERED_SHARE:
            names.add(d["name"])
    return sorted(names)


def _osm_owners(c, shared, cnorm, rings, lat):
    """Differently named OSM areas holding more of the park than its own does."""
    names = set()
    for r in rings:
        if (not r["name"] or r["allotment"]
                or not _bbox_overlap(c["bbox"], r["bbox"])
                or _norm(r["name"]) == cnorm):
            continue
        held = c["shape"].intersection(r["shape"]).area
        if (held > shared and held / c["shape"].area >= config.REVIEW_INSIDE_SHARE
                and _hectares(held, lat) >= config.REVIEW_INSIDE_MIN_HA):
            names.add(r["name"])
    return sorted(names)


def _hectares(area, lat):
    """An area in square degrees as hectares, at this latitude."""
    return area * 111320 ** 2 * math.cos(math.radians(lat)) / 10000


def _gap_feature(c, status, match):
    props = {
        "name": c["name"],
        "class": c["cls"],
        "status": status,
        "area_id": c["area_id"],
    }
    if match:
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

def _valid(geom):
    """The polygon as an area shapely can intersect; empty if it has none."""
    return make_valid(geom, method="structure", keep_collapsed=False)


# The City appends a borough to disambiguate duplicate names ("Oriole Park -
# Toronto"); OSM never does. Longer borough names first so they win the match.
_BOROUGH_SUFFIX = re.compile(
    r"\s+-\s+(north york|east york|toronto|etobicoke|scarborough|york)\s*$"
)
# Generic feature words the City and OSM disagree on appending ("Sugar Beach"
# vs "Sugar Beach Park", "St. James Cemetery" vs "... Cemetery and Crematorium").
_GENERIC_SUFFIX = re.compile(r"\s+(?:and\s+)?(?:park|cemetery|crematorium|club)$")
# Street words the City and OSM abbreviate differently ("Walmer Rd Parkette" vs
# "Walmer Road Parkette"). "St" stays out of it: it is usually Saint here.
_STREET_WORDS = {"rd": "road", "ave": "avenue", "blvd": "boulevard",
                 "dr": "drive", "cres": "crescent"}
_GARDEN_NAME = re.compile(r"garden|allotment|plot", re.IGNORECASE)


def _norm(name):
    """Loose match key: drop the artefacts City and OSM names differ on.

    Lowercases and reduces to single-spaced alphanumerics, and additionally
    strips the City's " - <Borough>" suffix, unifies "&"/"and", spells out street
    abbreviations, drops a leading article, and trims generic trailing feature
    words -- so spatially matched parks aren't flagged as mismatches over naming
    convention alone. Affects matching only; the displayed name keeps the raw
    City data.
    """
    if not name:
        return ""
    # Delete apostrophes so the City's "St. Andrews" keys the same as OSM's
    # "St. Andrew's" (rather than splitting into a stray "s" token).
    s = name.lower().replace("&", " and ").replace("'", "").replace("’", "")
    s = _BOROUGH_SUFFIX.sub("", s)
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    s = " ".join(_STREET_WORDS.get(word, word) for word in s.split())
    s = re.sub(r"^the\s+", "", s)
    while True:
        trimmed = _GENERIC_SUFFIX.sub("", s).strip()
        if trimmed == s:
            return s
        s = trimmed or s  # keep the last word if the name is only generic words


def _round_geom(geom):
    return {"type": geom["type"], "coordinates": _round(geom["coordinates"])}


def _round(c):
    if isinstance(c, (int, float)):
        return round(c, 5)  # ~1 m -- ample for a reference outline, smaller file
    return [_round(x) for x in c]
