#!/usr/bin/env python3
"""Daily 9:30am job (launchd): update the DB, rebuild the EDA report, then run the TOTO alert."""
from __future__ import annotations

import logging
import traceback

import eda_report
import toto_alert
import update_db

log = logging.getLogger("run_daily")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    errors = []

    try:
        added = update_db.update()
        if any(added.values()) or not eda_report.REPORT_PATH.exists():
            eda_report.build()
    except Exception:
        log.exception("DB update / report failed")
        errors.append("DB update failed:\n" + traceback.format_exc(limit=2))

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
