"""Unit tests for the download link gate and mid-body resume."""

import json
import os
import sys

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from addressvault import net  # noqa: E402
from src import config, download as dl  # noqa: E402

# Three 256 KB chunks, so a drop can land partway through a body.
BODY = b"x" * (1024 * 768)
LAST_MODIFIED = "Tue, 05 May 2026 21:59:31 GMT"
CHUNK = 1024 * 256


class FakeResponse:
    """Minimal stand-in for a streamed requests response."""

    def __init__(self, body, status_code=200, headers=None, drop_after=None):
        self.body = body
        self.status_code = status_code
        self.headers = headers or {}
        self.drop_after = drop_after

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size=1):
        sent = 0
        for i in range(0, len(self.body), chunk_size):
            if self.drop_after is not None and sent >= self.drop_after:
                raise requests.ConnectionError("connection dropped")
            chunk = self.body[i:i + chunk_size]
            sent += len(chunk)
            yield chunk


def fake_get(state, drops=0, honor_range=True):
    """A requests.get that drops the first ``drops`` responses mid-body."""
    def get(url, stream=False, timeout=None, headers=None):
        rng = (headers or {}).get("Range")
        state["ranges"].append(rng)
        if rng and honor_range:
            start = int(rng.split("=")[1].split("-")[0])
            resp = FakeResponse(
                BODY[start:], status_code=206,
                headers={"Content-Length": str(len(BODY) - start)},
            )
        else:
            resp = FakeResponse(BODY, headers={
                "Last-Modified": LAST_MODIFIED,
                "Content-Length": str(len(BODY)),
            })
        if len(state["ranges"]) <= drops:
            resp.drop_after = CHUNK
        return resp
    return get


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr(dl, "RETRY_WAIT", 0)


@pytest.fixture(autouse=True)
def usable_link(monkeypatch):
    """Leave the gate open by default; the tests that care close it."""
    monkeypatch.setattr("addressvault.net.wait_for_link", lambda **k: None)


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        config, "LAST_DOWNLOAD_PATH", str(tmp_path / ".last-download.json")
    )
    return tmp_path


def offline_gate(monkeypatch):
    monkeypatch.setattr(
        "addressvault.net.wait_for_link",
        lambda **k: (_ for _ in ()).throw(net.Offline("link is offline")),
    )


def test_a_dead_link_stops_before_any_request(data_dir, monkeypatch):
    # The whole point of the gate: on a weekly trigger, finding out now costs a
    # second, and finding out at the end of a 600 s read costs the slot.
    def boom(*a, **k):
        raise AssertionError("made a request on a dead link")

    offline_gate(monkeypatch)
    monkeypatch.setattr("src.download.requests.head", boom)
    monkeypatch.setattr("src.download.requests.get", boom)

    with pytest.raises(net.Offline):
        dl.download()


def test_a_failed_head_on_a_dead_link_does_not_start_a_download(data_dir, monkeypatch):
    # The gate is open at entry and the link dies before the HEAD -- the failure
    # must still be named a dead link, not "check failed, download anyway".
    # This is the exact shape of the 2026-07-27 run: getaddrinfo, then a
    # traceback out of the download.
    calls = {"head": 0}

    def head(*a, **k):
        calls["head"] += 1
        offline_gate(monkeypatch)
        raise requests.ConnectionError("getaddrinfo failed")

    monkeypatch.setattr("src.download.requests.head", head)
    monkeypatch.setattr("src.download.requests.get", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("started a download on a dead link")))

    with pytest.raises(net.Offline):
        dl.download()
    assert calls["head"] == 1


def test_resumes_after_a_dropped_connection(data_dir, monkeypatch):
    state = {"ranges": []}
    monkeypatch.setattr("src.download.requests.get", fake_get(state, drops=1))
    dest = data_dir / "out.geojson"

    headers = dl._fetch("http://example.invalid/data", str(dest))

    assert dest.read_bytes() == BODY
    assert headers["content_length"] == len(BODY)  # full size, not the 206 tail
    assert headers["last_modified"] == LAST_MODIFIED
    assert state["ranges"] == [None, f"bytes={CHUNK}-"]  # resumed, not restarted


def test_restarts_when_the_server_ignores_range(data_dir, monkeypatch):
    state = {"ranges": []}
    monkeypatch.setattr(
        "src.download.requests.get", fake_get(state, drops=1, honor_range=False)
    )
    dest = data_dir / "out.geojson"

    dl._fetch("http://example.invalid/data", str(dest))

    assert dest.read_bytes() == BODY  # restarted, not appended onto the partial
    assert len(state["ranges"]) == 2


def test_out_of_retries_on_a_dead_link_raises_link_unavailable(data_dir, monkeypatch):
    # The retry budget buys ~90 s, nowhere near long enough to outlast an
    # outage. On exhaustion the run must exit 75, not log a build failure
    # against a portal that was never reachable.
    monkeypatch.setattr(dl, "RETRIES", 1)
    state = {"ranges": []}
    monkeypatch.setattr("src.download.requests.get", fake_get(state, drops=99))
    monkeypatch.setattr(
        "addressvault.net.wait_for_link",
        lambda **k: (_ for _ in ()).throw(net.Offline("link is offline")),
    )

    with pytest.raises(net.Offline):
        dl._fetch("http://example.invalid/data", str(data_dir / "out.geojson"))
    assert len(state["ranges"]) == 2  # the initial attempt plus RETRIES


def test_unchanged_remote_skips_the_download(data_dir, monkeypatch):
    existing = data_dir / "green-spaces-2026-05-05.geojson"
    existing.write_bytes(BODY)
    (data_dir / ".last-download.json").write_text(json.dumps({
        "last_modified": LAST_MODIFIED,
        "content_length": len(BODY),
        "filename": existing.name,
    }))
    monkeypatch.setattr("src.download.requests.head", lambda *a, **k: FakeResponse(
        b"", headers={"Last-Modified": LAST_MODIFIED,
                      "Content-Length": str(len(BODY))}))
    monkeypatch.setattr("src.download.requests.get", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("downloaded an unchanged file")))

    status, path = dl.download()

    assert status == "SKIPPED"
    assert path == str(existing)
