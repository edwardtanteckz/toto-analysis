#!/usr/bin/env python3
"""Fetch Singapore Pools TOTO and 4D results into SQLite.

    python update_db.py --backfill-years 2   # first load
    python update_db.py                      # incremental: only draws not yet in the DB
"""
from __future__ import annotations

import argparse
import logging
from datetime import date, timedelta

from sgpools import db, scraper

log = logging.getLogger("update_db")


def _sync(conn, game: str, refs, table: str, fetch, insert, since: date | None) -> int:
    have = db.existing_draws(conn, table)
    if since is None:
        # Incremental: fill anything missing from the oldest draw we hold onwards
        # (or the last 2 years if the table is empty).
        row = conn.execute(f"SELECT MIN(draw_date) FROM {table}").fetchone()
        since = date.fromisoformat(row[0]) if row[0] else date.today() - timedelta(days=730)
    todo = sorted(
        (r for r in refs if r.draw_no not in have and r.draw_date >= since and not r.cancelled),
        key=lambda r: r.draw_no,
    )
    added = 0
    for i, ref in enumerate(todo, 1):
        try:
            insert(conn, fetch(ref))
            added += 1
            if i % 25 == 0 or i == len(todo):
                log.info("%s: %d/%d (draw %d, %s)", game, i, len(todo), ref.draw_no, ref.draw_date)
        except Exception as e:  # keep going; one bad page shouldn't stop the run
            log.error("%s draw %d failed: %s", game, ref.draw_no, e)
    return added


def update(backfill_years: float | None = None) -> dict[str, int]:
    since = date.today() - timedelta(days=round(365.25 * backfill_years)) if backfill_years else None
    conn = db.connect()
    try:
        added = {
            "toto": _sync(conn, "TOTO", scraper.toto_draw_list(), "toto_draws", scraper.fetch_toto, db.insert_toto, since),
            "fourd": _sync(conn, "4D", scraper.fourd_draw_list(), "fourd_draws", scraper.fetch_fourd, db.insert_fourd, since),
        }
    finally:
        conn.close()
    log.info("added: %s", added)
    return added


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--backfill-years", type=float, help="load every draw from the last N years")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    update(args.backfill_years)


if __name__ == "__main__":
    main()
