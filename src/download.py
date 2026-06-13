"""Download the Toronto Green Spaces GeoJSON from the Open Data portal.

Mirrors the smart-cache pattern of the sibling toronto-addresses-layer project:
a HEAD request compares Last-Modified + Content-Length against a small JSON
sidecar and only re-fetches on change.
"""

import json
import os
from datetime import date, datetime

import requests

from src import config


def download(force=False):
    """Download the latest Green Spaces GeoJSON.

    Returns (status, filepath) where status is "DOWNLOADED" or "SKIPPED".
    """
    os.makedirs(config.DATA_DIR, exist_ok=True)

    print("Checking for updates...")
    remote = {}
    try:
        resp = requests.head(config.DATASET_URL, timeout=30, allow_redirects=True)
        resp.raise_for_status()
        remote = {
            "last_modified": resp.headers.get("Last-Modified"),
            "content_length": _parse_int(resp.headers.get("Content-Length")),
        }
    except requests.RequestException as e:
        print(f"Warning: could not check remote headers: {e}")

    sidecar = _load_sidecar()
    if not force and remote and sidecar:
        unchanged = (
            remote.get("last_modified") == sidecar.get("last_modified")
            and remote.get("content_length") == sidecar.get("content_length")
        )
        existing = os.path.join(config.DATA_DIR, sidecar.get("filename", ""))
        if unchanged and os.path.isfile(existing):
            return "SKIPPED", existing

    # Name the file after the remote Last-Modified date when available.
    file_date = date.today()
    if remote.get("last_modified"):
        try:
            file_date = datetime.strptime(
                remote["last_modified"], "%a, %d %b %Y %H:%M:%S %Z"
            ).date()
        except ValueError:
            pass

    filename = f"green-spaces-{file_date.isoformat()}.geojson"
    filepath = os.path.join(config.DATA_DIR, filename)

    print(f"Downloading to {filepath} ...")
    resp = requests.get(config.DATASET_URL, stream=True, timeout=600)
    resp.raise_for_status()

    final = {
        "last_modified": resp.headers.get("Last-Modified"),
        "content_length": _parse_int(resp.headers.get("Content-Length")),
    }
    total = int(resp.headers.get("content-length", 0))
    downloaded = 0
    with open(filepath, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 256):
            f.write(chunk)
            downloaded += len(chunk)
            if total:
                pct = downloaded * 100 // total
                print(
                    f"\r  {downloaded // (1024 * 1024)} / "
                    f"{total // (1024 * 1024)} MB ({pct}%)",
                    end="", flush=True,
                )
    print(f"\nDone: {filepath} ({downloaded // (1024 * 1024)} MB)")

    _save_sidecar(final, filename)
    return "DOWNLOADED", filepath


def _load_sidecar():
    if os.path.isfile(config.LAST_DOWNLOAD_PATH):
        with open(config.LAST_DOWNLOAD_PATH, encoding="utf-8") as f:
            return json.load(f)
    return None


def _save_sidecar(headers, filename):
    with open(config.LAST_DOWNLOAD_PATH, "w", encoding="utf-8") as f:
        json.dump({**headers, "filename": filename}, f, indent=2)


def _parse_int(val):
    try:
        return int(val)
    except (ValueError, TypeError):
        return None
