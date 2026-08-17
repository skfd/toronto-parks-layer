"""CLI entry point for the Toronto parks tile layer build."""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from addressvault import LinkUnavailable

from src import config
from src.download import download
from src.slim import slim
from src.compare import compare
from src.vector import build_vector
from src.raster import build_raster
from src.site import build_site
from src.publish import publish

# Offline or metered is not a build failure -- same as if the machine had been
# off, the run just did not happen. 75 is the conventional EX_TEMPFAIL, matching
# the addressvault CLI, so the scheduled task's restart-on-failure retries it
# and a wrapper can tell "no network" apart from a broken build.
EXIT_LINK_UNAVAILABLE = 75
# The tiles built and published fine, but the gap page is comparing against
# cached OSM because no Overpass mirror answered. Non-zero so the scheduled
# task's restart policy (3 tries, 30 min apart) treats it as the retryable
# outage it is -- two silent 504s in Aug 2026 cost the page a fortnight of
# freshness while the task reported success both times. Raised only after the
# publish, so a flaky Overpass never costs the tiles.
EXIT_OSM_STALE = 70


def _banner(text):
    print()
    print(f"=== {text} ===")


def cmd_download(args):
    _banner("Download")
    status, path = download(force=args.force)
    print(f"{status}: {path}")


def cmd_slim(args):
    _banner("Slim")
    slim(_latest_geojson())


def cmd_compare(args):
    _banner("Compare with OSM")
    return compare()


def cmd_vector(args):
    _banner("Vector tiles")
    build_vector()


def cmd_raster(args):
    _banner("Raster tiles")
    counts = build_raster()
    for zoom, n in sorted(counts.items()):
        print(f"  z{zoom}: {n:,} tiles")
        if n == 0:
            raise RuntimeError(f"Raster zoom {zoom} produced no tiles.")


def cmd_site(args):
    _banner("Site")
    build_site()


def cmd_publish(args):
    _banner("Publish")
    publish()


def cmd_build(args):
    """Run the pipeline; return True if the gap page used live OSM data."""
    cmd_download(args)
    cmd_slim(args)
    # The OSM comparison is best-effort: a flaky Overpass must not stop a build.
    # "Best-effort" is not "one attempt" though -- compare() works through every
    # mirror several times before it settles for the cache, and says which it
    # used so the caller can report a stale gap page as the outage it is.
    fresh = False
    try:
        summary = cmd_compare(args)
        fresh = not summary.get("osm_stale")
    except LinkUnavailable:
        raise          # the link died mid-run; that is a 75, not a build fault
    except Exception as e:
        print(f"Warning: OSM comparison skipped ({e}).")
    cmd_vector(args)
    cmd_raster(args)
    cmd_site(args)
    return fresh


def cmd_update(args):
    fresh = cmd_build(args)
    cmd_publish(args)
    if not fresh:
        print("\nThe site is published, but its gap page is comparing against "
              "cached OSM data.")
        print("Exiting non-zero so the scheduled task retries the Overpass "
              "fetch rather than waiting a week.")
        sys.exit(EXIT_OSM_STALE)


def _latest_geojson():
    """Return the newest downloaded Green Spaces GeoJSON in data/."""
    if not os.path.isdir(config.DATA_DIR):
        raise RuntimeError("No data/ directory. Run 'download' first.")
    files = sorted(
        f for f in os.listdir(config.DATA_DIR)
        if f.startswith("green-spaces-") and f.endswith(".geojson")
    )
    if not files:
        raise RuntimeError("No Green Spaces GeoJSON in data/. Run 'download' first.")
    return os.path.join(config.DATA_DIR, files[-1])


COMMANDS = {
    "download": (cmd_download, "Download the latest Green Spaces GeoJSON"),
    "slim": (cmd_slim, "Filter parks into slim GeoJSONL"),
    "compare": (cmd_compare, "Compare City polygons against OSM -> gaps.geojson"),
    "vector": (cmd_vector, "Build vector (MVT) tiles via WSL tippecanoe"),
    "raster": (cmd_raster, "Build labelled raster (PNG) tiles"),
    "site": (cmd_site, "Render the GitHub Pages landing page"),
    "publish": (cmd_publish, "Force-push the site to the gh-pages branch"),
    "build": (cmd_build, "download + slim + vector + raster + site"),
    "update": (cmd_update, "build + publish (scheduled-task entry point)"),
}


def main():
    parser = argparse.ArgumentParser(
        description="Toronto Parks Tile Layer builder"
    )
    sub = parser.add_subparsers(dest="command")
    for name, (_, help_text) in COMMANDS.items():
        p = sub.add_parser(name, help=help_text)
        if name in ("download", "build", "update"):
            p.add_argument(
                "--force", action="store_true",
                help="Re-download even if the remote file is unchanged",
            )

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        return
    if not hasattr(args, "force"):
        args.force = False

    try:
        COMMANDS[args.command][0](args)
    except LinkUnavailable as e:
        print(f"\nSkipped: {e}")
        print("Nothing was fetched or published; the task will retry.")
        sys.exit(EXIT_LINK_UNAVAILABLE)


if __name__ == "__main__":
    main()
