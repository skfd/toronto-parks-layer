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
