# toto-analysis

Exploratory analysis of Singapore Pools **TOTO** (6/49) and **4D** results:

- Scrapes public results from singaporepools.com.sg into SQLite (`data/sgpools.db`).
- One daily **9:30am** macOS launchd job: fetches new draws, rebuilds the report, and posts a
  **Slack DM alert one working day before each TOTO draw** (date + estimated Group 1 prize).
  Weekends and Singapore public holidays are skipped (Mon draw → Fri alert, Thu draw → Wed alert).
- **Pre-draw picks**: 3 TOTO sets and 3 4D numbers for every draw, shown at the top of each report tab
  (TOTO sets are also in the Slack alert). Generated once per draw, then scored against the result:
  - TOTO: *Anti-popular* (avoids numbers other players favour, estimated from Singapore Pools winning-share
    counts, so a win is shared with fewer people), *Typical profile*, *Bayesian posterior*.
  - 4D: *Most common pattern*, *Bayesian digit posterior*, *Pure random*.
  - The odds are identical for every set: TOTO jackpot 1 in 13,983,816, 4D any prize 1 in 435 (Big bet).
  - **How lucky are the picks?** Every stored pick is compared with the actual draw: prizes won vs expected,
    luck percentile, matched numbers vs the exact expected distribution (4D: closest near-miss across all 23
    winning numbers), running profit/loss per lens at $1 per set, and a per-draw table with hits highlighted.
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
python make_picks.py --show                # picks for the next TOTO and 4D draws
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
| `analysis/picks.py`, `make_picks.py` | Pre-draw picks, popularity model, scoring past picks |
| `run_daily.py` | launchd entrypoint: update → score/generate picks → rebuild report → alert; posts errors to Slack |
| `analysis/stats.py` | Monte Carlo, Dirichlet–multinomial, randomness tests |
| `eda_report.py`, `web/` | Report builder; dependency-free WebGL charts (`web/charts.js`) |
| `launchd/`, `scripts/install_launchd.sh` | macOS scheduling |

## Database tables

`toto_draws`, `toto_prizes`, `fourd_draws`, `fourd_numbers` (long format: first/second/third/starter/consolation),
`toto_next_draw` (jackpot estimate snapshots), `alerts_sent`, `picks` (picks per draw + scored result).

```bash
sqlite3 data/sgpools.db "SELECT draw_date, n1,n2,n3,n4,n5,n6, additional, group1_prize FROM toto_draws ORDER BY draw_no DESC LIMIT 5"
```

## Scheduling

```bash
launchctl kickstart gui/$UID/com.toto.daily   # run now
tail -f logs/daily.log
./scripts/install_launchd.sh uninstall        # remove
```
