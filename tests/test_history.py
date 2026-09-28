"""The gap history: what a compare run records, what a backfill reconstructs,
and what the trend page is rendered from.

The record exists so the gap page can show the worklist shrinking week to week
(and so a mapper can see their own parks disappear from it). Two properties
matter more than the rest: a run on cached OSM must not add a point -- it saw
nothing new, and a flat line it drew would be a lie -- and a backfill must be
safe to interrupt and re-run, since it is paced slowly on purpose.
"""

import json
import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import compare, config, history, site  # noqa: E402

SUMMARY = {"missing": 120, "mismatch": 30, "unnamed": 45, "trca": 5,
           "city": 1745, "osm_rings": 6690, "osm_date": "2026-09-28",
           "osm_stale": False}


@pytest.fixture
def paths(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "HISTORY_PATH", str(tmp_path / "history.jsonl"))
    monkeypatch.setattr(config, "SLIM_PATH", str(tmp_path / "parks-slim.geojsonl"))
    monkeypatch.setattr(history, "seed", lambda: False)
    monkeypatch.setattr("addressvault.net.wait_for_link", lambda **k: None)
    return tmp_path


def test_a_live_run_appends_one_row_with_the_counts(paths):
    history.record(SUMMARY, day="2026-09-28")
    rows = history.load()
    assert len(rows) == 1
    assert rows[0] == {"date": "2026-09-28", "osm_date": "2026-09-28",
                       "source": "live", "missing": 120, "mismatch": 30,
                       "unnamed": 45, "trca": 5, "city": 1745, "osm_rings": 6690}


def test_a_second_run_the_same_day_replaces_the_first(paths):
    # The scheduler retries a stale run half an hour later; the day gets the
    # later, better answer, not two points.
    history.record(SUMMARY, day="2026-09-28")
    history.record({**SUMMARY, "missing": 118}, day="2026-09-28")
    rows = history.load()
    assert [r["missing"] for r in rows] == [118]


def test_a_run_on_cached_osm_is_not_recorded(paths):
    assert history.record({**SUMMARY, "osm_stale": True}) is None
    assert history.load() == []


def test_rows_load_oldest_first(paths):
    history.record(SUMMARY, day="2026-09-28")
    history.record(SUMMARY, day="2026-09-14")
    assert [r["date"] for r in history.load()] == ["2026-09-14", "2026-09-28"]


def test_dates_step_from_since_and_stop_before_until():
    got = list(history.dates(date(2026, 6, 1), date(2026, 6, 22), 7))
    assert got == [date(2026, 6, 1), date(2026, 6, 8), date(2026, 6, 15)]


def test_the_attic_query_only_adds_a_date_setting():
    live = compare._overpass_query()
    attic = compare._overpass_query(at="2026-06-01T00:00:00Z")
    assert attic.startswith('[out:json][timeout:180][date:"2026-06-01T00:00:00Z"];')
    assert attic.split(";", 1)[1] == live.split(";", 1)[1]


def _fake_overpass(answers):
    """A compare._try_overpass that replays ``answers`` per call."""
    calls = []

    def try_overpass(url, query):
        calls.append((url, query))
        return answers.pop(0)

    try_overpass.calls = calls
    return try_overpass


def test_backfill_skips_dates_on_record_and_stops_on_no_answer(paths, monkeypatch):
    history.record(SUMMARY, day="2026-06-08")
    monkeypatch.setattr(compare, "_city_features", lambda: iter([]))
    fake = _fake_overpass([{"elements": []}, None, {"elements": []}])
    monkeypatch.setattr(compare, "_try_overpass", fake)
    slept = []
    added = history.backfill(date(2026, 6, 1), date(2026, 6, 29), 7, 30,
                             sleep=slept.append)

    # 06-01 answered, 06-08 was on record, 06-15 got no answer -> stop; 06-22
    # is left for the next run.
    assert added == 1
    assert [r["date"] for r in history.load()] == ["2026-06-01", "2026-06-08"]
    assert history.load()[0]["source"] == "attic"
    assert all(url == config.ATTIC_URL for url, _q in fake.calls)
    assert '[date:"2026-06-01T00:00:00Z"]' in fake.calls[0][1]
    assert slept == [30], "paced between queries, never before the first"


def test_backfill_counts_gaps_against_the_city_polygons(paths, monkeypatch):
    square = [(-79.40, 43.70), (-79.39, 43.70), (-79.39, 43.71), (-79.40, 43.71)]
    city = [{"name": "Test Park", "cls": "Park", "area_id": 1,
             "geom": {"type": "Polygon", "coordinates": [list(map(list, square))]},
             "outers": [square], "bbox": compare._bbox(square),
             "centroid": compare._centroid(square)}]
    monkeypatch.setattr(compare, "_city_features", lambda: iter(city))
    monkeypatch.setattr(compare, "_try_overpass",
                        _fake_overpass([{"elements": []}]))
    history.backfill(date(2026, 6, 1), date(2026, 6, 2), 7, 0, sleep=lambda s: None)
    row = history.load()[0]
    assert row["missing"] == 1 and row["city"] == 1 and row["osm_rings"] == 0


def test_the_history_page_inlines_the_rows_and_tables_them(paths, tmp_path):
    history.record(SUMMARY, day="2026-09-21")
    history.record({**SUMMARY, "missing": 118}, day="2026-09-28")
    gaps_dir = tmp_path / "site" / "gaps"
    gaps_dir.mkdir(parents=True)
    site._build_history_page(str(gaps_dir), "2026-09-28")

    html = (gaps_dir / "history.html").read_text(encoding="utf-8")
    assert "2 comparisons since 2026-09-21" in html
    inline = html.split('id="history-data">', 1)[1].split("</script>", 1)[0]
    assert [r["missing"] for r in json.loads(inline)] == [120, 118]
    assert html.index("<td>2026-09-28</td>") < html.index("<td>2026-09-21</td>")
    assert "{{" not in html
    assert (gaps_dir / "history.js").is_file()
    assert (gaps_dir / "history.jsonl").read_text(encoding="utf-8").count("\n") == 2


def test_the_history_page_renders_without_any_history(paths, tmp_path):
    gaps_dir = tmp_path / "site" / "gaps"
    gaps_dir.mkdir(parents=True)
    site._build_history_page(str(gaps_dir), "2026-09-28")
    html = (gaps_dir / "history.html").read_text(encoding="utf-8")
    assert "0 comparisons since 2026-09-28" in html
    assert not (gaps_dir / "history.jsonl").exists()
