#!/usr/bin/env python3
"""Build reports/eda.html: runs the randomness analysis and embeds it in a WebGL report."""
from __future__ import annotations

import argparse
import json
import logging
import math
from datetime import datetime
from pathlib import Path

from analysis import stats
from sgpools import db

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
REPORT_PATH = ROOT / "reports" / "eda.html"
log = logging.getLogger("eda_report")


def _clean(o):
    """Make NaN/inf JSON-safe."""
    if isinstance(o, float):
        return None if math.isnan(o) or math.isinf(o) else round(o, 6)
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    return o


def build(sims: int = stats.MC_SIMS, out: Path = REPORT_PATH) -> Path:
    conn = db.connect()
    try:
        toto, fourd = stats.load_toto(conn), stats.load_fourd(conn)
    finally:
        conn.close()
    if not toto or not fourd:
        raise SystemExit("DB is empty - run `python update_db.py --backfill-years 2` first.")
    log.info("analysing %d TOTO and %d 4D draws (%d simulations)", len(toto), len(fourd), sims)
    data = _clean({"toto": stats.analyse_toto(toto, sims), "fourd": stats.analyse_fourd(fourd, sims), "mc_sims": sims})

    html = (WEB / "template.html").read_text()
    payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    html = (html.replace("__CHARTS_JS__", (WEB / "charts.js").read_text())
                .replace("__APP_JS__", (WEB / "app.js").read_text())
                .replace("__SIMS__", f"{sims:,}")
                .replace("__GENERATED__", datetime.now().strftime("%d %b %Y %H:%M"))
                .replace("__DATA__", payload))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)
    log.info("wrote %s (%.0f KB)", out, out.stat().st_size / 1024)
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sims", type=int, default=stats.MC_SIMS, help="Monte Carlo simulations (default 10000)")
    p.add_argument("--open", action="store_true", help="open the report in the browser")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    path = build(args.sims)
    if args.open:
        import webbrowser
        webbrowser.open(path.as_uri())


if __name__ == "__main__":
    main()
