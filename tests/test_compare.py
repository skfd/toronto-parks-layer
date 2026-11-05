"""Unit tests for the Overpass fetch: mirrors, retries, and the cache fallback.

What these pin is the failure that actually happened. On 2026-08-10 and again on
2026-08-17 overpass-api.de answered 504, the single attempt gave up, the run
silently compared against a fortnight-old cache and reported success -- so the
gap page went two weeks without anyone noticing. Every test here is about that
run trying harder, and about saying so when it still could not.
"""

import json
import os
import sys

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from addressvault import net  # noqa: E402
from src import compare, config, site  # noqa: E402

GOOD = {"elements": [{"type": "way", "id": i, "tags": {}, "geometry": []}
                     for i in range(config.OSM_MIN_ELEMENTS + 1)]}


class FakeResponse:
    def __init__(self, payload=None, status=200):
        self.payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Server Error")

    def json(self):
        return self.payload


def _post(by_host):
    """A requests.post that answers per hostname from ``by_host``."""
    calls = []

    def post(url, data=None, headers=None, timeout=None):
        calls.append(url)
        for host, reply in by_host.items():
            if host in url:
                if isinstance(reply, Exception):
                    raise reply
                return reply
        raise requests.ConnectionError("no route")

    post.calls = calls
    return post


@pytest.fixture
def paths(tmp_path, monkeypatch):
    """Point the cache + sidecar at a temp dir, and never really sleep."""
    monkeypatch.setattr(config, "OSM_CACHE_PATH", str(tmp_path / "osm-parks.json"))
    monkeypatch.setattr(config, "OSM_FETCH_PATH", str(tmp_path / ".osm-fetch.json"))
    monkeypatch.setattr(compare.time, "sleep", lambda _s: None)
    return tmp_path


def test_a_dead_primary_falls_through_to_the_next_mirror(paths, monkeypatch):
    # The whole point: one sick instance is not an outage.
    monkeypatch.setattr(config, "OVERPASS_URLS",
                        ("https://a.example/api", "https://b.example/api"))
    post = _post({"a.example": FakeResponse(status=504),
                  "b.example": FakeResponse(GOOD)})
    monkeypatch.setattr(compare.requests, "post", post)

    data, _date, from_cache = compare._load_osm()
    assert from_cache is False
    assert len(data["elements"]) == len(GOOD["elements"])
    assert [u.split("/")[2] for u in post.calls] == ["a.example", "b.example"]


def test_the_mirror_list_is_retried_before_giving_up(paths, monkeypatch):
    # A 504 is load shedding, and load sheds. Trying the list once was what
    # turned a transient failure into a fortnight of stale data.
    monkeypatch.setattr(config, "OVERPASS_URLS", ("https://a.example/api",))
    monkeypatch.setattr(config, "OVERPASS_ROUNDS", 3)
    replies = [FakeResponse(status=504), FakeResponse(status=504),
               FakeResponse(GOOD)]

    def post(url, data=None, headers=None, timeout=None):
        return replies.pop(0)

    monkeypatch.setattr(compare.requests, "post", post)
    _data, _date, from_cache = compare._load_osm()
    assert from_cache is False
    assert replies == [], "every round should have been used"


def test_an_implausibly_small_reply_is_not_accepted(paths, monkeypatch):
    # overpass.osm.ch serves a Switzerland extract and answers a Toronto bbox
    # with HTTP 200 and zero elements. Believing it would report every City
    # park as missing from OSM -- 1,745 fictional gaps.
    monkeypatch.setattr(config, "OVERPASS_URLS",
                        ("https://regional.example/api", "https://good.example/api"))
    post = _post({"regional.example": FakeResponse({"elements": []}),
                  "good.example": FakeResponse(GOOD)})
    monkeypatch.setattr(compare.requests, "post", post)

    data, _date, from_cache = compare._load_osm()
    assert from_cache is False
    assert len(data["elements"]) == len(GOOD["elements"])


def _stamped(stamp):
    return {**GOOD, "osm3s": {"timestamp_osm_base": stamp}}


def test_a_reply_from_months_old_data_is_not_accepted(paths, monkeypatch):
    # overpass.private.coffee answered 2026-09-29 in full, with OSM as of
    # 2026-05-06. It looked like success and the page showed May as this week.
    monkeypatch.setattr(config, "OVERPASS_URLS",
                        ("https://lagging.example/api", "https://good.example/api"))
    now = compare.datetime.now(compare.timezone.utc)
    fresh = (now - compare.timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    post = _post({"lagging.example": FakeResponse(_stamped("2026-05-06T03:25:00Z")),
                  "good.example": FakeResponse(_stamped(fresh))})
    monkeypatch.setattr(compare.requests, "post", post)

    _data, osm_date, from_cache = compare._load_osm()
    assert from_cache is False
    assert osm_date == fresh[:10], "dated by the data, not by the fetch"
    assert [u.split("/")[2] for u in post.calls] == ["lagging.example", "good.example"]


def test_a_cached_reply_is_dated_by_its_data_not_its_fetch(paths, monkeypatch):
    # The sidecar says fetched yesterday; the data inside says May. May is what
    # the page must print.
    with open(config.OSM_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(_stamped("2026-05-06T03:25:00Z"), f)
    with open(config.OSM_FETCH_PATH, "w", encoding="utf-8") as f:
        json.dump({"fetched": "2026-09-29", "mirror": "lagging.example"}, f)
    assert compare._load_cache()[1] == "2026-05-06"


def test_a_good_fetch_records_when_and_where_it_came_from(paths, monkeypatch):
    monkeypatch.setattr(config, "OVERPASS_URLS", ("https://good.example/api",))
    monkeypatch.setattr(compare.requests, "post",
                        _post({"good.example": FakeResponse(GOOD)}))

    _data, fetched, _from_cache = compare._load_osm()
    with open(config.OSM_FETCH_PATH, encoding="utf-8") as f:
        sidecar = json.load(f)
    assert sidecar == {"fetched": fetched, "mirror": "good.example"}


def test_the_cache_is_used_only_after_every_mirror_fails(paths, monkeypatch):
    with open(config.OSM_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(GOOD, f)
    with open(config.OSM_FETCH_PATH, "w", encoding="utf-8") as f:
        json.dump({"fetched": "2026-08-03", "mirror": "old.example"}, f)

    monkeypatch.setattr(config, "OVERPASS_URLS",
                        ("https://a.example/api", "https://b.example/api"))
    monkeypatch.setattr(config, "OVERPASS_ROUNDS", 2)
    post = _post({"a.example": FakeResponse(status=504),
                  "b.example": FakeResponse(status=504)})
    monkeypatch.setattr(compare.requests, "post", post)
    monkeypatch.setattr(net, "wait_for_link", lambda wait=True: None)

    _data, fetched, from_cache = compare._load_osm()
    assert len(post.calls) == 4, "both mirrors, both rounds"
    # The date carried out is the cache's own, not today's -- that value is what
    # the gap page prints, and printing today's would be the original lie.
    assert (fetched, from_cache) == ("2026-08-03", True)


def test_with_no_cache_and_no_mirror_the_run_is_told_to_fail(paths, monkeypatch):
    monkeypatch.setattr(config, "OVERPASS_URLS", ("https://a.example/api",))
    monkeypatch.setattr(config, "OVERPASS_ROUNDS", 1)
    monkeypatch.setattr(compare.requests, "post",
                        _post({"a.example": FakeResponse(status=504)}))
    monkeypatch.setattr(net, "wait_for_link", lambda wait=True: None)

    with pytest.raises(compare.OsmUnavailable):
        compare._load_osm()


def test_being_offline_is_not_reported_as_an_overpass_outage(paths, monkeypatch):
    # No link means the fetch never happened; that is a 75 elsewhere in the
    # pipeline, not a broken Overpass, and it must not be confused with one.
    with open(config.OSM_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(GOOD, f)
    monkeypatch.setattr(config, "OVERPASS_URLS", ("https://a.example/api",))
    monkeypatch.setattr(config, "OVERPASS_ROUNDS", 1)
    monkeypatch.setattr(compare.requests, "post",
                        _post({"a.example": requests.ConnectionError("offline")}))

    def no_link(wait=True):
        raise net.LinkUnavailable("no usable link")

    monkeypatch.setattr(net, "wait_for_link", no_link)
    _data, _fetched, from_cache = compare._load_osm()
    assert from_cache is True


def test_the_cache_date_falls_back_to_the_file_mtime(paths, monkeypatch):
    # A cache written before the sidecar existed still has to date itself.
    with open(config.OSM_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(GOOD, f)
    os.utime(config.OSM_CACHE_PATH, (1754247600, 1754247600))  # 2026-08-03 local
    assert compare._cache_date().startswith("20")


# --- matching ---------------------------------------------------------------
#
# Reported from the live page: Walmer Rd Parkette and Bishop Allotment Gardens
# both showed as missing with the area plainly mapped underneath them.

X0, Y0 = -79.409, 43.676       # the Walmer Road neighbourhood
MX, MY = 1 / 80500, 1 / 111200  # degrees per metre here


def _ring(*corners):
    """A closed ring from (x, y) corners given in metres from X0, Y0."""
    pts = [(X0 + x * MX, Y0 + y * MY) for x, y in corners]
    return pts + pts[:1]


def _box(x, y, w, h):
    return _ring((x, y), (x + w, y), (x + w, y + h), (x, y + h))


def _ell(x, y, size, arm):
    """An L: its centre of area is outside the L itself."""
    return _ring((x, y), (x + size, y), (x + size, y + arm), (x + arm, y + arm),
                 (x + arm, y + size), (x, y + size))


def _osm(oid, ring, **tags):
    return {"type": "way", "id": oid, "tags": tags,
            "geometry": [{"lon": x, "lat": y} for x, y in ring]}


def _gap(tmp_path, monkeypatch, name, ring, *osm, cls="Park"):
    """The gap feature one City polygon lands in, or None if it is matched."""
    slim = tmp_path / "slim.geojsonl"
    slim.write_text(json.dumps({
        "type": "Feature",
        "properties": {"name": name, "class": cls, "area_id": 1},
        "geometry": {"type": "Polygon", "coordinates": [[list(p) for p in ring]]},
    }) + "\n", encoding="utf-8")
    monkeypatch.setattr(config, "SLIM_PATH", str(slim))
    gaps, _counts = compare._match(list(compare._city_features()),
                                   compare._osm_rings({"elements": list(osm)}))
    return gaps[0]["properties"] if gaps else None


def test_a_sliver_of_a_parkette_matches_at_real_coordinates(tmp_path, monkeypatch):
    # Walmer Rd Parkette is 15 x 44 m. Summed raw at lon/lat, its centroid came
    # out 25 m outside its own bounding box.
    sliver = _ring((0, 0), (15, 30), (12, 44), (2, 20))
    osm = _osm(1, _box(-10, -10, 40, 70), leisure="park", name="Walmer Road Parkette")
    assert _gap(tmp_path, monkeypatch, "Walmer Rd Parkette", sliver, osm) is None


def test_two_l_shapes_overlap_though_neither_centre_is_inside(tmp_path, monkeypatch):
    # Humber Bay Shores and Giovanni Caboto read as missing this way, 90% covered.
    osm = _osm(1, _ell(0, 0, 300, 40), leisure="park")
    gap = _gap(tmp_path, monkeypatch, "Bent Park", _ell(0, 0, 300, 40), osm)
    assert gap["status"] == "unnamed"


def test_a_tennis_club_does_not_take_the_match_from_its_park(tmp_path, monkeypatch):
    # "Pine Point Park" was reported against "Pine Point Tennis Club".
    park = _osm(1, _box(0, 0, 200, 200), leisure="park")
    club = _osm(2, _box(90, 90, 20, 20), landuse="recreation_ground",
                name="Pine Point Tennis Club")
    gap = _gap(tmp_path, monkeypatch, "Pine Point Park", _box(0, 0, 200, 200), club, park)
    assert gap["status"] == "unnamed"


def test_a_same_named_ring_wins_over_a_bigger_overlap(tmp_path, monkeypatch):
    other = _osm(1, _box(0, 0, 200, 200), leisure="park", name="Norris Crescent Parkette")
    same = _osm(2, _box(0, 0, 40, 40), leisure="park", name="Mimico Waterfront Park")
    assert _gap(tmp_path, monkeypatch, "Mimico Waterfront Park",
                _box(0, 0, 200, 200), other, same) is None


def test_a_same_named_ring_beside_the_polygon_still_matches(tmp_path, monkeypatch):
    # Sits in the crook of the L: the bboxes overlap, the polygons do not.
    osm = _osm(1, _ell(0, 0, 300, 40), leisure="park", name="Fairford Parkette")
    assert _gap(tmp_path, monkeypatch, "Fairford Parkette",
                _box(100, 100, 50, 50), osm) is None


def test_a_small_garden_does_not_make_a_big_polygon_mapped(tmp_path, monkeypatch):
    garden = _osm(1, _box(90, 90, 20, 20), leisure="garden", name="Peace Garden")
    gap = _gap(tmp_path, monkeypatch, "Nathan Phillips Square", _box(0, 0, 200, 200), garden)
    assert gap["status"] == "missing"


def test_several_rings_can_cover_a_polygon_between_them(tmp_path, monkeypatch):
    halves = [_osm(i, _box(i * 25, 0, 20, 200), leisure="garden") for i in range(4)]
    gap = _gap(tmp_path, monkeypatch, "Four Winds", _box(0, 0, 500, 200), *halves)
    assert gap["status"] == "unnamed"


def test_an_allotment_answers_for_a_city_garden(tmp_path, monkeypatch):
    # The City's allotments are "Open Green Space"; OSM's are landuse=allotments.
    osm = _osm(1, _box(0, 0, 100, 100), landuse="allotments",
               name="Bishop Allotment Gardens")
    assert _gap(tmp_path, monkeypatch, "Bishop Allotment Gardens", _box(0, 0, 100, 100),
                osm, cls="Open Green Space") is None


def test_an_allotment_does_not_answer_for_a_park(tmp_path, monkeypatch):
    # West Deane Park holds a "Community Garden"; that is not the park.
    osm = _osm(1, _box(0, 0, 100, 100), landuse="allotments", name="Community Garden")
    gap = _gap(tmp_path, monkeypatch, "West Deane Park", _box(0, 0, 100, 100), osm)
    assert gap["status"] == "missing"


def test_a_way_that_doubles_back_is_not_a_ring():
    there_and_back = [{"lon": X0, "lat": Y0}, {"lon": X0 + 0.001, "lat": Y0},
                      {"lon": X0, "lat": Y0}]
    assert compare._make_ring(there_and_back, {}, "way", 1) is None


@pytest.mark.parametrize("city, osm", [
    ("Walmer Rd Parkette", "Walmer Road Parkette"),
    ("174 Soudan Avenue Park", "174 Soudan Ave Park"),
    ("Asterfield - Plumrose Blvd Parkette", "Asterfield-Plumrose Boulevard Parkette"),
])
def test_street_abbreviations_are_not_a_mismatch(city, osm):
    assert compare._norm(city) == compare._norm(osm)


def test_st_is_left_alone_because_it_is_usually_saint():
    assert compare._norm("St. James Park") != compare._norm("Street James Park")


# --- what the reader sees ---------------------------------------------------

def test_a_stale_comparison_says_so_on_the_page():
    note = site._osm_note({"osm_stale": True, "osm_date": "2026-08-03"})
    assert "2026-08-03" in note and "class=\"stale\"" in note


def test_a_fresh_comparison_adds_nothing():
    assert site._osm_note({"osm_stale": False, "osm_date": "2026-08-17"}) == ""
