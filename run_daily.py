#!/usr/bin/env python3
"""Daily 9:30am job (launchd): update DB, score/generate picks, rebuild the EDA report, run the TOTO alert."""
from __future__ import annotations

import logging
import traceback

import eda_report
import toto_alert
import update_db
from analysis import picks
from sgpools import db

log = logging.getLogger("run_daily")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    errors = []

    added = {}
    try:
        added = update_db.update()
    except Exception:
        log.exception("DB update failed")
        errors.append("DB update failed:\n" + traceback.format_exc(limit=2))

    new_picks = False
    try:
        conn = db.connect()
        try:
            picks.score_past(conn)
            _, new_picks = picks.ensure_next(conn)
        finally:
            conn.close()
    except Exception:
        log.exception("picks failed")
        errors.append("Picks failed:\n" + traceback.format_exc(limit=2))

    try:
        if any(added.values()) or new_picks or not eda_report.REPORT_PATH.exists():
            eda_report.build()
    except Exception:
        log.exception("report build failed")
        errors.append("Report build failed:\n" + traceback.format_exc(limit=2))

    try:
        toto_alert.run()
    except Exception:
        log.exception("TOTO alert failed")
        errors.append("TOTO alert failed:\n" + traceback.format_exc(limit=2))

    if errors:
        try:
            toto_alert.post_slack(":warning: TOTO daily job had errors:\n```" + "\n".join(errors)[:2500] + "```")
        except Exception:
            log.exception("could not post failure notice")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
