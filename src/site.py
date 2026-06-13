"""Render the GitHub Pages landing page into the build output."""

import json
import os
import re
import shutil
from datetime import date

from PIL import Image

from src import config

# Screenshots shown on the landing page, copied from the project root when
# present (they are added manually after the first publish).
SCREENSHOTS = ["iD.png", "JOSM.png"]
SCREENSHOT_MAX_WIDTH = 1500


def build_site():
    """Render index.html, copy assets and screenshots into build/site/."""
    os.makedirs(config.SITE_DIR, exist_ok=True)

    park_count = "1,700+"
    if os.path.isfile(config.COUNT_PATH):
        with open(config.COUNT_PATH, encoding="utf-8") as f:
            park_count = f"{int(f.read().strip()):,}"

    build_date = date.today().isoformat()

    with open(os.path.join(config.ASSETS_DIR, "index.html.tmpl"),
              encoding="utf-8") as f:
        html = f.read()

    replacements = {
        "{{PAGES_URL}}": config.PAGES_URL,
        "{{VECTOR_URL}}": f"{config.PAGES_URL}/tiles/vector/{{z}}/{{x}}/{{y}}.pbf",
        "{{RASTER_URL}}": f"{config.PAGES_URL}/tiles/raster/{{z}}/{{x}}/{{y}}.png",
        "{{RASTER_URL_JOSM}}": (
            f"{config.PAGES_URL}/tiles/raster/{{zoom}}/{{x}}/{{y}}.png"
        ),
        "{{VECTOR_URL_JOSM}}": (
            f"{config.PAGES_URL}/tiles/vector/{{zoom}}/{{x}}/{{y}}.pbf"
        ),
        "{{BUILD_DATE}}": build_date,
        "{{DATA_DATE}}": _data_date(build_date),
        "{{PARK_COUNT}}": park_count,
        "{{GITHUB_REPO}}": config.GITHUB_REPO,
        "{{DATASET_PAGE}}": config.DATASET_PAGE,
        "{{LICENSE_URL}}": config.LICENSE_URL,
    }
    for key, value in replacements.items():
        html = html.replace(key, value)

    with open(os.path.join(config.SITE_DIR, "index.html"), "w",
              encoding="utf-8") as f:
        f.write(html)
    for name in ("index.css", "index.js"):
        shutil.copy(
            os.path.join(config.ASSETS_DIR, name),
            os.path.join(config.SITE_DIR, name),
        )
    for name in SCREENSHOTS:
        src = os.path.join(config.PROJECT_DIR, name)
        if os.path.isfile(src):
            _copy_image(src, os.path.join(config.SITE_DIR, name),
                        SCREENSHOT_MAX_WIDTH)
    _build_gaps_page(build_date)
    # .nojekyll stops GitHub Pages running Jekyll over the tile directories.
    open(os.path.join(config.SITE_DIR, ".nojekyll"), "w").close()
    print(f"Site rendered: {config.SITE_DIR}")


def _build_gaps_page(build_date):
    """Render gaps/ (map + table) when a comparison has produced gaps.geojson."""
    if not os.path.isfile(config.GAPS_GEOJSON_PATH):
        print("  (no gaps.geojson -- run 'compare'; skipping gap page)")
        return

    gaps_dir = os.path.join(config.SITE_DIR, "gaps")
    os.makedirs(gaps_dir, exist_ok=True)

    summary = {}
    if os.path.isfile(config.GAPS_COUNT_PATH):
        with open(config.GAPS_COUNT_PATH, encoding="utf-8") as f:
            summary = json.load(f)

    with open(os.path.join(config.ASSETS_DIR, "gaps.html.tmpl"),
              encoding="utf-8") as f:
        html = f.read()
    replacements = {
        "{{PAGES_URL}}": config.PAGES_URL,
        "{{BUILD_DATE}}": build_date,
        "{{DATA_DATE}}": _data_date(build_date),
        "{{MISSING_COUNT}}": f"{summary.get('missing', 0):,}",
        "{{MISMATCH_COUNT}}": f"{summary.get('mismatch', 0):,}",
        "{{CITY_COUNT}}": f"{summary.get('city', 0):,}",
        "{{OSM_COUNT}}": f"{summary.get('osm_rings', 0):,}",
        "{{GITHUB_REPO}}": config.GITHUB_REPO,
    }
    for key, value in replacements.items():
        html = html.replace(key, value)

    with open(os.path.join(gaps_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    shutil.copy(config.GAPS_GEOJSON_PATH, os.path.join(gaps_dir, "gaps.geojson"))
    for name in ("gaps.css", "gaps.js"):
        shutil.copy(os.path.join(config.ASSETS_DIR, name),
                    os.path.join(gaps_dir, name))
    print(f"Gap page rendered: {gaps_dir}")


def _data_date(fallback):
    """Return the City data's date (YYYY-MM-DD) from the download sidecar."""
    if os.path.isfile(config.LAST_DOWNLOAD_PATH):
        with open(config.LAST_DOWNLOAD_PATH, encoding="utf-8") as f:
            sidecar = json.load(f)
        match = re.search(r"\d{4}-\d{2}-\d{2}", sidecar.get("filename", ""))
        if match:
            return match.group(0)
    return fallback


def _copy_image(src, dst, max_width):
    """Copy an image into the site, downscaling it if wider than max_width."""
    with Image.open(src) as img:
        if img.width > max_width:
            height = round(img.height * max_width / img.width)
            resized = img.resize((max_width, height), Image.LANCZOS)
            resized.save(dst, optimize=True)
            print(f"  {os.path.basename(src)}: {img.width}px -> {max_width}px")
        else:
            shutil.copy(src, dst)
