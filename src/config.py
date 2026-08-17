"""Configuration constants for the Toronto parks tile layer build.

Single source of truth. No logic here.

Sibling of toronto-addresses-layer / toronto-waterways-layer: same pipeline
(download -> slim -> vector + raster -> site -> publish), but the source is the
Green Spaces polygon dataset and the slim filter keeps only park-ish classes.
"""

import os

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_DIR, "data")
BUILD_DIR = os.path.join(PROJECT_DIR, "build")
SITE_DIR = os.path.join(BUILD_DIR, "site")
ASSETS_DIR = os.path.join(PROJECT_DIR, "assets")
LOGS_DIR = os.path.join(PROJECT_DIR, "logs")

MBTILES_PATH = os.path.join(BUILD_DIR, "parks.mbtiles")
SLIM_PATH = os.path.join(DATA_DIR, "parks-slim.geojsonl")
# Same as SLIM_PATH but without the numbered "TRCA LANDS" parcels: the rendered
# tile layer reads this, the gap tool keeps reading the full SLIM_PATH.
LAYER_SLIM_PATH = os.path.join(DATA_DIR, "parks-layer.geojsonl")
COUNT_PATH = os.path.join(DATA_DIR, "parks.count")
LAST_DOWNLOAD_PATH = os.path.join(DATA_DIR, ".last-download.json")

VECTOR_TILE_DIR = os.path.join(SITE_DIR, "tiles", "vector")
RASTER_TILE_DIR = os.path.join(SITE_DIR, "tiles", "raster")

# Data source: City of Toronto Green Spaces, published in WGS84. This is the
# successor of the deprecated "Parks" dataset (its page points here).
GS_PACKAGE_ID = "9a284a84-b9ff-484b-9e30-82f22c1780b9"
GS_RESOURCE_ID = "7a26629c-b642-4093-b33c-a5a21e4f3d22"
GS_FILENAME = "green-spaces-4326.geojson"
DATASET_URL = (
    f"https://ckan0.cf.opendata.inter.prod-toronto.ca/dataset/"
    f"{GS_PACKAGE_ID}/resource/{GS_RESOURCE_ID}/download/{GS_FILENAME}"
)
DATASET_PAGE = "https://open.toronto.ca/dataset/green-spaces/"
LICENSE_URL = "https://open.toronto.ca/open-data-licence/"
# Plain-ASCII attribution embedded in tile metadata (safe through the WSL shell).
ATTRIBUTION = "(c) City of Toronto, Open Government Licence - Toronto"

# GitHub Pages target. Update both if the repo/account differs.
GITHUB_REPO = "skfd/toronto-parks-layer"
PAGES_URL = "https://skfd.github.io/toronto-parks-layer"

# WSL distro that has tippecanoe installed (see wsl-setup.md).
WSL_DISTRO = "Ubuntu"

# Vector tiles. iD requests tiles at (map zoom - 1) and does NOT overzoom, so
# tiles must be generated natively through the zooms used for mapping. Parks
# are large polygons that read well from city-overview zooms, hence z10.
VECTOR_MINZOOM = 10
VECTOR_MAXZOOM = 19
VECTOR_LAYER_NAME = "parks"

# Raster tiles. Editors overzoom z17 -> z18+. Park name labels are gated by
# fit (a name renders only when the polygon is big enough on screen), so no
# separate label-zoom set is needed.
RASTER_ZOOMS = [13, 14, 15, 16, 17]

# Green Spaces AREA_CLASS values to KEEP: things OSM would map as a park-like
# green area. Traffic islands, road slivers, hydro corridors, building grounds
# and the generic OTHER_* administrative classes are dropped.
INCLUDE_AREA_CLASSES = frozenset({
    "Park",
    "Open Green Space",
    "Golf Course",
    "OTHER_GOLFCOURSE",
    "Cemetery",
    "OTHER_CEMETERY",
    "Civic Centre Square",
})

# Source property keys read from the Green Spaces GeoJSON.
NAME_KEY = "AREA_NAME"        # all-caps name, e.g. "TAYLOR CREEK PARK"
CLASS_KEY = "AREA_CLASS"      # e.g. "Park", "Cemetery", "Golf Course"
AREA_ID_KEY = "AREA_ID"       # stable city identifier for the polygon

# --- OSM comparison (gap-review page) ---
# Park-like areas are pulled from OSM via Overpass and matched against the kept
# City polygons by spatial overlap; the gaps feed build/site/gaps/.
#
# Mirrors are tried in order, and the whole list is retried a few times: the
# failure this guards against is a loaded instance shedding a request, not a bad
# query. A single attempt against a 504 was the entire effort on 2026-08-10 and
# 2026-08-17, and the gap page silently ran on a fortnight-old diff.
#
# Measured 2026-08-17 with this exact query, from this laptop:
#   overpass-api.de          5.1s   200   6,690 elements
#   overpass.private.coffee 16.9s   200   6,577 elements
#   overpass.kumi.systems   32.1s   504   (the "faster mirror" was the sick one)
#   overpass.osm.jp          0.8s   SSL failure
#   overpass.osm.ch          0.9s   200       0 elements
# overpass.osm.ch is deliberately absent: it serves a Switzerland extract and
# answers a Toronto bbox with a perfectly valid empty result, which would read
# as "every City park is missing from OSM". OSM_MIN_ELEMENTS is the guard
# against any mirror that ever does that.
OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
OVERPASS_TIMEOUT = 300
OVERPASS_ROUNDS = 3
OVERPASS_ROUND_WAIT = 60
# Floor on a reply's element count. The query returns ~6,700; anything under a
# few thousand is a wrong-region or truncated answer, not a week's mapping.
OSM_MIN_ELEMENTS = 3000
# Overpass rejects the default requests User-Agent (HTTP 406); identify the tool.
USER_AGENT = "toronto-parks-layer/1.0 (https://github.com/skfd/toronto-parks-layer)"
# Toronto bounding box (S, W, N, E), a touch larger than the city. OSM areas
# outside the city simply match nothing, so a loose box is harmless.
TORONTO_BBOX = (43.58, -79.64, 43.86, -79.12)
# OSM tags treated as a park-like area (the OSM analogue of INCLUDE_AREA_CLASSES).
OSM_AREA_TAGS = {
    "leisure": ("park", "garden", "nature_reserve", "golf_course", "common"),
    "landuse": ("cemetery", "recreation_ground"),
    "amenity": ("grave_yard",),
}
OSM_CACHE_PATH = os.path.join(DATA_DIR, "osm-parks.json")
# When the cached Overpass reply was fetched, and from where. The cache file's
# own mtime cannot say this -- a fallback run rewrites nothing.
OSM_FETCH_PATH = os.path.join(DATA_DIR, ".osm-fetch.json")
GAPS_GEOJSON_PATH = os.path.join(DATA_DIR, "gaps.geojson")
GAPS_COUNT_PATH = os.path.join(DATA_DIR, "gaps.count.json")
