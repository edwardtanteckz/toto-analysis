# toto-analysis

Exploratory analysis of Singapore Pools **TOTO** (6/49) and **4D** results:

- Scrapes public results from singaporepools.com.sg into SQLite (`data/sgpools.db`).
- One daily **9:30am SGT** job on **GitHub Actions** (`.github/workflows/daily.yml`): fetches new draws,
  rebuilds the report, commits the DB + report back to the repo, and sends a **Telegram (and/or Slack)
  alert one working day before each TOTO draw** (date + estimated Group 1 prize).
  Weekends and Singapore public holidays are skipped (Mon draw → Fri alert, Thu draw → Wed alert).
- **Pre-draw picks**: 3 TOTO sets and 3 4D numbers for every draw, shown at the top of each report tab
  (TOTO sets are also in the alert). Generated once per draw, then scored against the result:
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
cp .env.example .env && chmod 600 .env     # local runs only: Telegram and/or Slack settings
python make_picks.py --show                # picks for the next TOTO and 4D draws
python toto_alert.py --dry-run             # see when the next alert would fire
python toto_alert.py --force               # send a test message now
./scripts/install_launchd.sh               # optional: run locally via launchd instead of GitHub Actions
```

## Files

| Path | Purpose |
|---|---|
| `sgpools/scraper.py` | Draw lists, TOTO/4D result pages, next-draw jackpot estimate |
| `sgpools/db.py` | SQLite schema + idempotent inserts |
| `update_db.py` | Backfill / incremental update |
| `toto_alert.py` | Working-day-before TOTO alert (deduped via `alerts_sent`) |
| `sgpools/notify.py` | Telegram + Slack sender; `python -m sgpools.notify --test` / `--chat-id` |
| `analysis/picks.py`, `make_picks.py` | Pre-draw picks, popularity model, scoring past picks |
| `run_daily.py` | Daily entrypoint: update → score/generate picks → rebuild report → alert; sends errors as a notification |
| `analysis/stats.py` | Monte Carlo, Dirichlet–multinomial, randomness tests |
| `eda_report.py`, `web/` | Report builder; dependency-free WebGL charts (`web/charts.js`) |
| `.github/workflows/daily.yml` | GitHub Actions schedule (09:30 SGT) |
| `launchd/`, `scripts/install_launchd.sh` | Optional local macOS scheduling |

## Database tables

`toto_draws`, `toto_prizes`, `fourd_draws`, `fourd_numbers` (long format: first/second/third/starter/consolation),
`toto_next_draw` (jackpot estimate snapshots), `alerts_sent`, `picks` (picks per draw + scored result).

```bash
sqlite3 data/sgpools.db "SELECT draw_date, n1,n2,n3,n4,n5,n6, additional, group1_prize FROM toto_draws ORDER BY draw_no DESC LIMIT 5"
```

## Scheduling (GitHub Actions)

The workflow runs daily at 09:23 Singapore, with a backup run at 10:47 (GitHub sometimes delays or skips scheduled runs). Both are safe to run: the alert is recorded once sent, and a late run still alerts any time up to 6.30pm on draw day.
After each run it commits `data/sgpools.db` and `reports/eda.html` back to `main`, so **`git pull` before
looking at the report or running anything locally**. Download the latest report from the repo, or from
the published page **https://edwardtanteckz.github.io/toto-analysis/** (GitHub Pages, updated by every daily run and linked from the TOTO alert).

Secrets (repo **Settings → Secrets and variables → Actions**): `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`,
optional `SLACK_WEBHOOK_URL`.

Manual runs: **Actions → Daily TOTO/4D job → Run workflow**, mode `test-notification`, `test-alert` (sends the real alert now), `dry-run-alert` or `daily`.
Or from a terminal: `gh workflow run daily.yml -f mode=test-notification`.

Don't run the local launchd job at the same time: two copies of the DB would drift apart.

### Local alternative (launchd)

```bash
launchctl kickstart gui/$UID/com.toto.daily   # run now
tail -f logs/daily.log
./scripts/install_launchd.sh uninstall        # remove
```
