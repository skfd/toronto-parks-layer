# Toronto Parks Layer

Turns the City of Toronto [Green Spaces](https://open.toronto.ca/dataset/green-spaces/)
dataset (~1,750 park-ish polygons) into map-tile layers that OpenStreetMap
mappers can add to the **JOSM** and **iD** editors as a reference overlay.

**Live layer and how to add it: https://skfd.github.io/toronto-parks-layer/**

It is a sibling of
[toronto-addresses-layer](https://github.com/skfd/toronto-addresses-layer) and
[toronto-waterways-layer](https://github.com/skfd/toronto-waterways-layer):
the same `download -> slim -> tiles -> site -> publish` pipeline, pointed at
the Green Spaces polygons. (The City's older "Parks" dataset is deprecated;
its page redirects to Green Spaces.)

## What it produces

- **Vector tiles** (MVT) &mdash; interactive in iD; click a polygon to read its
  `name`, `class` and `area_id` tags.
- **Raster tiles** (PNG) &mdash; translucent green fills with magenta outlines
  and park-name labels; a readable backdrop for JOSM. A name only renders once
  the polygon is big enough on screen to fit it, so big parks are labelled from
  city zoom and small parkettes only when zoomed in.
- A **landing page** with copy-paste "add this layer" instructions for both
  editors.

All of it is published to GitHub Pages and rebuilt weekly.

## What is kept

Green Spaces classes kept by the slim filter (`INCLUDE_AREA_CLASSES` in
[`src/config.py`](src/config.py)): `Park`, `Open Green Space`, `Golf Course`,
`Cemetery`, `Civic Centre Square` and their `OTHER_*` variants. Traffic
islands, road slivers, boulevards, hydro corridors, building grounds and the
generic administrative `OTHER_*` classes are dropped. Names are converted from
the City's ALL CAPS to title case.

## Setup

1. Install Python dependencies:
   ```
   pip install -r requirements.txt
   ```
2. Set up WSL2 + tippecanoe once &mdash; see [wsl-setup.md](wsl-setup.md).
3. Confirm the GitHub repo in `src/config.py` (`GITHUB_REPO`, `PAGES_URL`).

## Usage

```
python run.py download   # fetch the latest Green Spaces GeoJSON (smart-cached)
python run.py slim       # filter to park-ish polygons -> slim GeoJSONL
python run.py vector     # build vector (MVT) tiles via WSL tippecanoe
python run.py raster     # build labelled raster (PNG) tiles
python run.py site       # render the landing page
python run.py publish    # force-push the site to the gh-pages branch

python run.py build      # download + slim + vector + raster + site
python run.py update     # build + publish  (the scheduled entry point)
```

Build output lands in `build/site/`; that directory is what gets published.

## Tile endpoints

```
https://skfd.github.io/toronto-parks-layer/tiles/vector/{z}/{x}/{y}.pbf   (z10-19)
https://skfd.github.io/toronto-parks-layer/tiles/raster/{z}/{x}/{y}.png   (z13-17)
```

The vector layer name is `parks`.

## Hosting

The tile pyramid is published to an orphan `gh-pages` branch, recreated and
force-pushed on every build so repository history never grows. One-time step:
in the GitHub repo, set **Settings &rarr; Pages &rarr; Source** to the
`gh-pages` branch (root).

## Scheduling (Windows)

Run as Administrator:

```powershell
.\schedule-add.ps1      # registers a weekly task "TorontoParksLayer", Mondays 15:00
.\schedule-remove.ps1   # unregisters it
```

Weekly is enough &mdash; the City refreshes the Green Spaces dataset monthly.
The task runs `python run.py update` and appends output to `logs\scheduler.log`.

## Tests

```
python tests\test_tilemath.py
python tests\test_slim.py
```

## Licence / attribution

Park data is &copy; City of Toronto, published under the
[Open Government Licence &ndash; Toronto](https://open.toronto.ca/open-data-licence/).
Tiles and the landing page carry that attribution.
