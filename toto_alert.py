#!/usr/bin/env python3
"""Post a Slack alert one working day before the next TOTO draw.

    python toto_alert.py            # post only if today is the working day before the draw
    python toto_alert.py --dry-run  # print what would happen, post nothing
    python toto_alert.py --force    # post now regardless of date (testing)
"""
from __future__ import annotations

import argparse
import logging
import os
from datetime import date, timedelta
from pathlib import Path

import holidays
import requests

from analysis import picks
from sgpools import db, scraper

log = logging.getLogger("toto_alert")
ENV_PATH = Path(__file__).resolve().parent / ".env"


def load_env() -> None:
    """Minimal .env loader (KEY=VALUE lines); real env vars win."""
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def is_working_day(d: date) -> bool:
    return d.weekday() < 5 and d not in holidays.Singapore(years=d.year)


def previous_working_day(d: date) -> date:
    d -= timedelta(days=1)
    while not is_working_day(d):
        d -= timedelta(days=1)
    return d


def format_message(nxt: scraper.NextToto, sets: list[dict] | None = None) -> str:
    prize = f"${nxt.est_jackpot:,}" if nxt.est_jackpot else (nxt.raw_jackpot or "n/a")
    msg = (
        f":8ball: *TOTO draw coming up*\n"
        f"*Draw date:* {nxt.draw_date:%a, %d %b %Y}, 6.30pm\n"
        f"*Est. Group 1 (grand) prize:* {prize}"
    )
    if sets:
        msg += "\n\n*Picks for this draw*\n" + "\n".join(
            f"{s['set_no']}. `{' '.join(f'{n:02d}' for n in s['numbers'])}`  _{s['lens']}_" for s in sets)
        msg += f"\n_Odds per set: 1 in {picks.TOTO_ODDS:,} (same for every set). Anti-popular only means fewer people to share a win with._"
    return msg


def post_slack(text: str) -> None:
    load_env()
    url = os.environ.get("SLACK_WEBHOOK_URL")
    if not url:
        raise RuntimeError(f"SLACK_WEBHOOK_URL is not set (add it to {ENV_PATH})")
    r = requests.post(url, json={"text": text}, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"Slack webhook returned HTTP {r.status_code}: {r.text[:200]}")


def run(today: date | None = None, dry_run: bool = False, force: bool = False) -> bool:
    """Returns True if an alert was (or, in dry-run, would be) sent."""
    today = today or date.today()
    nxt = scraper.fetch_next_toto()
    alert_day = previous_working_day(nxt.draw_date)
    log.info("next draw %s, alert day %s, today %s", nxt.draw_date, alert_day, today)

    conn = db.connect()
    try:
        db.record_next_toto(conn, nxt)
        try:
            picks.ensure(conn, "toto", nxt.draw_date)
            sets = picks.get_picks(conn, "toto", nxt.draw_date)
        except Exception:
            log.exception("could not load picks; sending alert without them")
            sets = None
        msg = format_message(nxt, sets)
        already = conn.execute("SELECT 1 FROM alerts_sent WHERE draw_date=?", (nxt.draw_date.isoformat(),)).fetchone()
        due = force or (today == alert_day and not already)
        if dry_run:
            print(f"Next draw: {nxt.draw_date}  alert day: {alert_day}  today: {today}  "
                  f"already sent: {bool(already)}  would send: {due}\n---\n{msg}")
            return due
        if not due:
            return False
        post_slack(msg)
        if not force:
            with conn:
                conn.execute("INSERT OR REPLACE INTO alerts_sent VALUES (?,?,?)",
                             (nxt.draw_date.isoformat(), db.now(), msg))
        log.info("alert posted for draw %s", nxt.draw_date)
        return True
    finally:
        conn.close()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    run(dry_run=args.dry_run, force=args.force)


if __name__ == "__main__":
    main()
