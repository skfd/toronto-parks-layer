"""CLI entry point for the Toronto parks tile layer build."""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src import config
from src.download import download
from src.slim import slim
from src.vector import build_vector
from src.raster import build_raster
from src.site import build_site
from src.publish import publish


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
    cmd_download(args)
    cmd_slim(args)
    cmd_vector(args)
    cmd_raster(args)
    cmd_site(args)


def cmd_update(args):
    cmd_build(args)
    cmd_publish(args)


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

    COMMANDS[args.command][0](args)


if __name__ == "__main__":
    main()
