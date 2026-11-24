#!/usr/bin/env python3
"""Send a Telegram/Slack alert one working day before the next TOTO draw.

    python toto_alert.py            # post only if today is the working day before the draw
    python toto_alert.py --dry-run  # print what would happen, post nothing
    python toto_alert.py --force    # post now regardless of date (testing)
"""
from __future__ import annotations

import argparse
import html
import logging
import os
from datetime import date, timedelta

import holidays

from analysis import picks
from sgpools import db, notify, scraper

log = logging.getLogger("toto_alert")


def is_working_day(d: date) -> bool:
    return d.weekday() < 5 and d not in holidays.Singapore(years=d.year)


def previous_working_day(d: date) -> date:
    d -= timedelta(days=1)
    while not is_working_day(d):
        d -= timedelta(days=1)
    return d


ODDS_NOTE = (f"Odds per set: 1 in {picks.TOTO_ODDS:,} (same for every set). "
             "Anti-popular only means fewer people to share a win with.")


def report_url() -> str | None:
    """Public EDA report: REPORT_URL if set, else the repo's GitHub Pages URL when running on Actions."""
    notify.load_env()
    if os.environ.get("REPORT_URL"):
        return os.environ["REPORT_URL"]
    repo = os.environ.get("GITHUB_REPOSITORY")  # "owner/name", set by GitHub Actions
    if repo and "/" in repo:
        owner, name = repo.split("/", 1)
        return f"https://{owner.lower()}.github.io/{name}/"
    return None


def format_message(nxt: scraper.NextToto, sets: list[dict] | None = None) -> notify.Message:
    prize = f"${nxt.est_jackpot:,}" if nxt.est_jackpot else (nxt.raw_jackpot or "n/a")
    when = f"{nxt.draw_date:%a, %d %b %Y}, 6.30pm"
    slack = f":8ball: *TOTO draw coming up*\n*Draw date:* {when}\n*Est. Group 1 (grand) prize:* {prize}"
    tg = (f"🎱 <b>TOTO draw coming up</b>\n<b>Draw date:</b> {html.escape(when)}\n"
          f"<b>Est. Group 1 (grand) prize:</b> {html.escape(prize)}")
    if sets:
        nums = lambda s: " ".join(f"{n:02d}" for n in s["numbers"])
        slack += "\n\n*Picks for this draw*\n" + "\n".join(
            f"{s['set_no']}. `{nums(s)}`  _{s['lens']}_" for s in sets) + f"\n_{ODDS_NOTE}_"
        tg += "\n\n<b>Picks for this draw</b>\n" + "\n".join(
            f"{s['set_no']}. <code>{nums(s)}</code>  <i>{html.escape(s['lens'])}</i>" for s in sets) + f"\n<i>{html.escape(ODDS_NOTE)}</i>"
    url = report_url()
    if url:
        slack += f"\n\n<{url}|:bar_chart: View the EDA report>"
        tg += f'\n\n📊 <a href="{html.escape(url, quote=True)}">View the EDA report</a>'
    return notify.Message(slack=slack, telegram=tg)


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
                  f"already sent: {bool(already)}  would send: {due}  channels: {notify.channels() or 'none'}\n"
                  f"--- Telegram ---\n{msg.telegram}\n--- Slack ---\n{msg.slack}")
            return due
        if not due:
            return False
        sent_to = notify.send(msg)
        if not force:
            with conn:
                conn.execute("INSERT OR REPLACE INTO alerts_sent VALUES (?,?,?)",
                             (nxt.draw_date.isoformat(), db.now(), msg.telegram))
        log.info("alert sent for draw %s via %s", nxt.draw_date, ", ".join(sent_to))
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
