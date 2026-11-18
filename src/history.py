"""Keep the gap counts of every compare run, and rebuild the past on demand.

Each live comparison appends one line to data/history.jsonl: the date, which
OSM data it saw, and the counts from the summary. That is the whole record of
the observer -- a dozen numbers a week -- and gaps/history.html charts it. A
run that fell back to cached OSM observed nothing new and is not recorded,
so the chart never shows a false plateau.

The record is deliberately tiny and reconstructible. OSM keeps its own history,
so a lost file is rebuilt with ``backfill``, which asks Overpass what OSM
looked like on each past Monday and re-runs the comparison against it. That is
why nothing heavier -- the Overpass replies, the per-park verdicts -- is kept.
The one caveat: a reconstructed week uses today's City polygons, since the City
side is not archived; Green Spaces changes monthly and slowly, and the page
says which points are reconstructed.
"""

import time

from addressvault import net
from layerkit import history as _kit

from src import config

FIELDS = ("missing", "mismatch", "unnamed", "retag", "trca", "city", "osm_rings")


def record(summary, day=None):
    """Append the run's row (replacing an earlier row from the same day)."""
    return _kit.record(summary, FIELDS, path=config.HISTORY_PATH, seed=seed,
                       day=day)


def load():
    """All rows, oldest first. An absent file is an empty history."""
    return _kit.load(config.HISTORY_PATH)


def seed():
    """Start a checkout that has no history from the published copy."""
    return _kit.seed(config.HISTORY_PATH, config.HISTORY_URL, config.USER_AGENT)


def backfill(since, until, step_days, pause, sleep=time.sleep):
    """Add rows for past dates by asking Overpass for OSM as it stood then.

    Idempotent: dates already on record are skipped, so an interrupted run is
    resumed by running it again. Stops at the first query that gets no answer
    rather than retrying -- attic queries cost the instance more than live
    ones, and this is a one-off, not the weekly build. Returns the number of
    rows added.
    """
    from src import compare  # here, not at the top: compare imports history

    net.wait_for_link(wait=False)
    seed()
    have = {r["date"] for r in load()}
    days = [d for d in dates(since, until, step_days) if d.isoformat() not in have]
    if not days:
        print("History: nothing to backfill.")
        return 0
    print(f"Backfilling {len(days)} date(s) from {config.ATTIC_URL} ...")
    city = list(compare._city_features())
    added = 0
    for i, d in enumerate(days):
        if i:
            sleep(pause)
        stamp = f"{d.isoformat()}T00:00:00Z"
        print(f"{d}: OSM as of {stamp}")
        data = compare._try_overpass(config.ATTIC_URL, compare._overpass_query(at=stamp))
        if data is None:
            print("  no answer; stopping. Run backfill again later to resume.")
            break
        rings = compare._osm_rings(data)
        _gaps, counts = compare._match(city, rings)
        row = {"date": d.isoformat(), "osm_date": d.isoformat(), "source": "attic",
               "city": len(city), "osm_rings": len(rings), **counts}
        _write(load() + [row])
        added += 1
        print(f"  {counts['missing']:,} missing, {counts['mismatch']:,} mismatch, "
              f"{counts['unnamed']:,} unnamed, {counts['trca']:,} TRCA")
    return added


def dates(since, until, step_days):
    """``since``, then every ``step_days``, while before ``until``."""
    return _kit.dates(since, until, step_days)


def _write(rows):
    _kit.write(config.HISTORY_PATH, rows)
