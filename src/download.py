"""Download the Toronto Green Spaces GeoJSON from the Open Data portal.

Mirrors the smart-cache pattern of the sibling toronto-addresses-layer project:
a HEAD request compares Last-Modified + Content-Length against a small JSON
sidecar and only re-fetches on change.

Every request is gated on a usable link first (``addressvault.net``, the same
gate the address vault pulls behind). The weekly trigger is what makes that
worth doing: a run lost to a dead link is not retried until next Monday, and on
2026-07-27 this task died exactly that way -- an unhandled getaddrinfo
traceback out of the very first request. A link that dies mid-body now resumes
instead of costing the whole download.
"""

import json
import os
import time
from datetime import date, datetime

import requests
from addressvault import net

from src import config

# The Green Spaces dump is ~20 MB. Smaller than the streets sibling's, but a
# retry costs nothing when the link is healthy and buys back a week when it is
# not.
RETRIES = 3
RETRY_WAIT = 30


def download(force=False):
    """Download the latest Green Spaces GeoJSON.

    Returns (status, filepath) where status is "DOWNLOADED" or "SKIPPED".
    Raises ``net.LinkUnavailable`` when the host has no usable link: nothing was
    attempted, so the caller exits 75 rather than reporting a build failure.
    """
    os.makedirs(config.DATA_DIR, exist_ok=True)

    # Ask before doing anything. Offline or metered, nothing below can work, and
    # finding out here costs a second instead of a 600 s read timeout. Never
    # block waiting for the link: the task carries a hard ExecutionTimeLimit, so
    # a wait would be killed mid-sleep -- retrying is the scheduler's job.
    net.wait_for_link(wait=False)

    print("Checking for updates...")
    remote = _head()

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
    final = _fetch(config.DATASET_URL, filepath)
    print(f"\nDone: {filepath} ({os.path.getsize(filepath) // (1024 * 1024)} MB)")

    _save_sidecar(final, filename)
    return "DOWNLOADED", filepath


def _head():
    """Remote Last-Modified + Content-Length, or {} if the check failed."""
    try:
        resp = requests.head(config.DATASET_URL, timeout=30, allow_redirects=True)
        resp.raise_for_status()
        return {
            "last_modified": resp.headers.get("Last-Modified"),
            "content_length": _parse_int(resp.headers.get("Content-Length")),
        }
    except requests.RequestException as e:
        # Ask why before shrugging this off. "Could not check, download anyway"
        # is right for a flaky portal, but wrong for a dead link -- the download
        # cannot work either, and only rediscovers that after four attempts.
        net.wait_for_link(wait=False)
        print(f"Warning: could not check remote headers: {e}")
        return {}


def _fetch(url, dest):
    """Stream ``url`` to ``dest``; return the response headers worth keeping.

    Retries a dropped connection, resuming with a Range request where the server
    allows it and starting over where it does not. A content-encoded body cannot
    be resumed: Range counts encoded bytes, and what is on disk is decoded. The
    kept headers come from the full response, never a 206 -- a range reply's
    Content-Length describes the tail, and the sidecar compares whole files.
    """
    got = 0
    resumable = False
    headers = {}
    for attempt in range(RETRIES + 1):
        want = {"Range": f"bytes={got}-"} if got else {}
        try:
            with requests.get(url, stream=True, timeout=600, headers=want) as resp:
                resp.raise_for_status()
                if resp.status_code != 206:  # full body: (re)start from byte 0
                    got = 0
                    resumable = not resp.headers.get("Content-Encoding")
                    headers = {
                        "last_modified": resp.headers.get("Last-Modified"),
                        "content_length": _parse_int(
                            resp.headers.get("Content-Length")
                        ),
                    }
                total = headers.get("content_length") or 0
                with open(dest, "ab" if got else "wb") as f:
                    for chunk in resp.iter_content(chunk_size=1024 * 256):
                        f.write(chunk)
                        got += len(chunk)
                        if total:
                            print(
                                f"\r  {got // (1024 * 1024)} / "
                                f"{total // (1024 * 1024)} MB "
                                f"({got * 100 // total}%)",
                                end="", flush=True,
                            )
            return headers
        except (requests.ConnectionError, requests.Timeout,
                requests.exceptions.ChunkedEncodingError) as e:
            total = headers.get("content_length")
            if resumable and total and got >= total:
                return headers  # dropped on the last chunk; the file is whole
            if attempt == RETRIES:
                # Out of retries. If the link itself is down then this was never
                # a portal failure -- say so, and the run exits 75 instead of
                # logging a build error against a site never reached at all.
                net.wait_for_link(wait=False)
                raise
            if not resumable:
                got = 0
            print(f"\n  download dropped at {got:,} bytes ({e});"
                  f" retrying in {RETRY_WAIT}s")
            time.sleep(RETRY_WAIT)


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
