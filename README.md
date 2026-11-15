# toto-analysis

Exploratory analysis of Singapore Pools **TOTO** (6/49) and **4D** results:

- Scrapes public results from singaporepools.com.sg into SQLite (`data/sgpools.db`).
- One daily **9:30am** macOS launchd job: fetches new draws, rebuilds the report, and posts a
  **Slack DM alert one working day before each TOTO draw** (date + estimated Group 1 prize).
  Weekends and Singapore public holidays are skipped (Mon draw → Fri alert, Thu draw → Wed alert).
- An interactive, self-contained **WebGL** report (`reports/eda.html`) that asks “is it random?” using:
  - **Monte Carlo baseline**: 10,000 simulated fair histories of the same length. These give bands on the charts and empirical p-values.
  - **Bayesian Dirichlet–multinomial**: per-number posterior + 95% credible intervals, plus Bayes factors (fair vs biased).
  - **Randomness tests**: chi-square, runs tests, KS on sums, lag-1 serial correlation, gap test, pair co-occurrence,
    and 4D digit/pattern tests, with Benjamini–Hochberg correction.

> Lottery draws are independent and designed to be uniform. This project measures how consistent the
> history is with fairness. It does **not** predict numbers.

## Setup

```bash
pip install -r requirements.txt
python update_db.py --backfill-years 2     # first load (~10 min, 1 request/sec)
python eda_report.py --open                # build + open reports/eda.html
cp .env.example .env && chmod 600 .env     # then paste your Slack webhook URL
python toto_alert.py --dry-run             # see when the next alert would fire
python toto_alert.py --force               # send a test message now
./scripts/install_launchd.sh               # install the 9:30am daily job
```

## Files

| Path | Purpose |
|---|---|
| `sgpools/scraper.py` | Draw lists, TOTO/4D result pages, next-draw jackpot estimate |
| `sgpools/db.py` | SQLite schema + idempotent inserts |
| `update_db.py` | Backfill / incremental update |
| `toto_alert.py` | Working-day-before alert to Slack (deduped via `alerts_sent`) |
| `run_daily.py` | launchd entrypoint: update → rebuild report → alert; posts errors to Slack |
| `analysis/stats.py` | Monte Carlo, Dirichlet–multinomial, randomness tests |
| `eda_report.py`, `web/` | Report builder; dependency-free WebGL charts (`web/charts.js`) |
| `launchd/`, `scripts/install_launchd.sh` | macOS scheduling |

## Database tables

`toto_draws`, `toto_prizes`, `fourd_draws`, `fourd_numbers` (long format: first/second/third/starter/consolation),
`toto_next_draw` (jackpot estimate snapshots), `alerts_sent`.

```bash
sqlite3 data/sgpools.db "SELECT draw_date, n1,n2,n3,n4,n5,n6, additional, group1_prize FROM toto_draws ORDER BY draw_no DESC LIMIT 5"
```

## Scheduling

```bash
launchctl kickstart gui/$UID/com.toto.daily   # run now
tail -f logs/daily.log
./scripts/install_launchd.sh uninstall        # remove
```
