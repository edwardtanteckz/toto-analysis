"""Pre-draw number picks: 3 TOTO sets and 3 4D numbers per draw, each from a labelled lens.

Honest framing: draws are fair, so every TOTO set has the same 1 in 13,983,816 jackpot
chance, and every 4D number has the same odds and fixed payout. The only lever analysis has
is TOTO's shared prize pools: picking numbers other players avoid means fewer people to split
with if you do win. Picks are generated once per draw (seeded by game + date) and stored.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date, datetime, time, timedelta
from math import comb

import numpy as np

from analysis import stats
from sgpools import db

TOTO_ODDS = comb(49, 6)                       # 13,983,816
# P(any TOTO prize) = P(>= 3 main numbers matched)
P_TOTO_ANY = sum(comb(6, k) * comb(43, 6 - k) for k in range(3, 7)) / TOTO_ODDS
P_4D_ANY = 23 / 10_000                         # "Big" bet wins on any of 23 prize numbers
FOURD_DRAW_DAYS = {2, 5, 6}                    # Wed, Sat, Sun
DRAW_TIME = time(18, 30)

# Prior popularity (log-scale bump) from published lotto-player studies: birthdays and lucky numbers.
LUCKY = {8: 0.03, 18: 0.03, 28: 0.03, 38: 0.02, 48: 0.01, 7: 0.02, 9: 0.015, 3: 0.01, 6: 0.01, 13: -0.01}


def _prior() -> np.ndarray:
    p = np.zeros(49)
    p[:31] += 0.03          # 1-31: birthdays (days of month)
    p[:12] += 0.02          # 1-12: also months
    for n, v in LUCKY.items():
        p[n - 1] += v
    return p - p.mean()


# ---------------------------------------------------------------- popularity model
def popularity_model(conn: sqlite3.Connection) -> dict:
    """Estimate how popular each number is with players from Singapore Pools' winning-share counts.

    For each draw, shares won in Group 5 (4 numbers) + Group 7 (3 numbers) rise when the drawn
    numbers are popular. Ridge-regress log(shares) on which numbers were drawn, controlling for
    draw size via log(Group 1 prize pool). Falls back to the prior if it doesn't beat a
    sales-only model in 5-fold cross-validation.
    """
    rows = conn.execute("""
        SELECT d.n1,d.n2,d.n3,d.n4,d.n5,d.n6,d.group1_prize, p5.winning_shares, p7.winning_shares
        FROM toto_draws d
        JOIN toto_prizes p5 ON p5.draw_no=d.draw_no AND p5.prize_group=5
        JOIN toto_prizes p7 ON p7.draw_no=d.draw_no AND p7.prize_group=7
        WHERE p5.winning_shares IS NOT NULL AND p7.winning_shares IS NOT NULL""").fetchall()
    prior = _prior()
    if len(rows) < 60:
        return {"coef": prior.tolist(), "source": "prior", "cv_gain": None, "n": len(rows)}
    X = np.zeros((len(rows), 49))
    for i, r in enumerate(rows):
        X[i, np.array(r[:6]) - 1] = 1
    sales = np.log(np.array([max(r[6] or 1, 1) for r in rows], float))
    y = np.log(np.array([r[7] + r[8] for r in rows], float))

    def ridge(F, t, lam):
        A = np.c_[np.ones(len(F)), F]
        pen = np.eye(A.shape[1]) * lam
        pen[0, 0] = pen[1, 1] = 0                 # don't shrink intercept or sales term
        return np.linalg.solve(A.T @ A + pen, A.T @ t)

    F = np.c_[sales, X]
    folds = np.array_split(np.random.default_rng(0).permutation(len(y)), 5)
    best = (None, -np.inf)
    for lam in (3, 10, 30, 100):
        e_full = e_base = 0.0
        for f in folds:
            tr = np.setdiff1d(np.arange(len(y)), f)
            b = ridge(F[tr], y[tr], lam)
            e_full += ((np.c_[np.ones(len(f)), F[f]] @ b - y[f]) ** 2).sum()
            bb = np.linalg.lstsq(np.c_[np.ones(len(tr)), sales[tr]], y[tr], rcond=None)[0]
            e_base += ((np.c_[np.ones(len(f)), sales[f]] @ bb - y[f]) ** 2).sum()
        gain = 1 - e_full / e_base
        if gain > best[1]:
            best = (lam, gain)
    lam, gain = best
    if gain <= 0:
        return {"coef": prior.tolist(), "source": "prior", "cv_gain": float(gain), "n": len(rows)}
    coef = ridge(F, y, lam)[2:]
    coef = coef - coef.mean()
    blended = 0.7 * coef + 0.3 * prior
    return {"coef": blended.tolist(), "data_coef": coef.tolist(), "source": "data+prior",
            "cv_gain": float(gain), "lambda": lam, "n": len(rows)}


# ---------------------------------------------------------------- helpers
def _rng(game: str, draw_date: date, salt: int) -> np.random.Generator:
    h = hashlib.sha256(f"{game}|{draw_date.isoformat()}|{salt}".encode()).digest()
    return np.random.default_rng(int.from_bytes(h[:8], "big"))


def _max_run(nums) -> int:
    s = sorted(nums)
    best = run = 1
    for a, b in zip(s, s[1:]):
        run = run + 1 if b == a + 1 else 1
        best = max(best, run)
    return best


def _pattern_penalty(nums, last_draw: set[int]) -> float:
    s = sorted(nums)
    pen = 0.0
    if _max_run(s) >= 3:
        pen += 0.15
    diffs = {b - a for a, b in zip(s, s[1:])}
    if len(diffs) == 1:
        pen += 0.3                                  # arithmetic sequence
    if len({(n - 1) // 10 for n in s}) == 1:
        pen += 0.1                                  # all in one decade
    if any(all(n % k == 0 for n in s) for k in range(2, 8)):
        pen += 0.2                                  # all multiples of k
    if max(s) <= 31:
        pen += 0.1                                  # an all-birthday ticket
    pen += 0.05 * len(set(s) & last_draw)
    return pen


def _overlap_ok(cand, chosen, max_overlap=2) -> bool:
    return all(len(set(cand) & set(c)) <= max_overlap for c in chosen)


# ---------------------------------------------------------------- TOTO lenses
def _toto_sets(conn, draw_date: date, salt: int) -> list[dict]:
    rng = _rng("toto", draw_date, salt)
    draws = stats.load_toto(conn)
    last = {draws[-1][f"n{i}"] for i in range(1, 7)} if draws else set()
    counts = np.zeros(49)
    for d in draws:
        for i in range(1, 7):
            counts[d[f"n{i}"] - 1] += 1
    pop = popularity_model(conn)
    coef = np.array(pop["coef"])
    chosen: list[list[int]] = []

    # 1) anti-popular: sample 50k combos, pick randomly among the least popular 1%
    keys = rng.random((50_000, 49))
    combos = np.sort(np.argpartition(keys, 6, axis=1)[:, :6] + 1, axis=1)
    score = coef[combos - 1].sum(1) + np.array([_pattern_penalty(c, last) for c in combos])
    pool = combos[np.argsort(score)[:500]]
    anti = sorted(int(x) for x in pool[rng.integers(len(pool))])
    chosen.append(anti)
    src = "Singapore Pools winning-share data + birthday/lucky-number prior" if pop["source"] != "prior" else "birthday/lucky-number prior"

    # 2) typical profile: the most common shape of a fair draw
    sim = np.sort(np.argpartition(np.random.default_rng(1).random((100_000, 49)), 6, axis=1)[:, :6] + 1, axis=1).sum(1)
    lo, hi = np.quantile(sim, [0.25, 0.75])
    while True:
        c = sorted(int(x) for x in rng.choice(49, 6, replace=False) + 1)
        odd = sum(n % 2 for n in c)
        low = sum(n <= 24 for n in c)
        if (lo <= sum(c) <= hi and odd in (2, 3, 4) and 2 <= low <= 4 and _max_run(c) < 3
                and len({(n - 1) // 10 for n in c}) >= 4 and _overlap_ok(c, chosen)):
            break
    chosen.append(c)

    # 3) Bayesian posterior draw
    while True:
        p = rng.dirichlet(1 + counts)
        c = sorted(int(x) for x in rng.choice(49, 6, replace=False, p=p) + 1)
        if _overlap_ok(c, chosen):
            break
    chosen.append(c)

    return [
        {"lens": "Anti-popular", "numbers": chosen[0],
         "rationale": f"Numbers other players tend to avoid (from {src}). Same odds, but fewer people to share a win with."},
        {"lens": "Typical profile", "numbers": chosen[1],
         "rationale": f"Sum {sum(chosen[1])} (middle 50% is {lo:.0f}–{hi:.0f}), {sum(n % 2 for n in chosen[1])} odd, spread across decades. "
                      "Common shapes are common only because most combinations look like this."},
        {"lens": "Bayesian posterior", "numbers": chosen[2],
         "rationale": "Drawn from the posterior over number probabilities given past draws. The posterior is almost uniform, so this is close to random."},
    ]


# ---------------------------------------------------------------- 4D lenses
def _fourd_sets(conn, draw_date: date, salt: int) -> list[dict]:
    rng = _rng("4d", draw_date, salt)
    draws = stats.load_fourd(conn)
    digits = np.array([[int(ch) for ch in n] for d in draws for _, n in d["numbers"]]) if draws else np.zeros((0, 4), int)
    pos_counts = np.stack([np.bincount(digits[:, p], minlength=10) for p in range(4)]) if len(digits) else np.zeros((4, 10))
    out = ["".join(str(d) for d in rng.choice(10, 4, replace=False))]  # 1) all-different digits
    while True:  # 2) posterior per position
        n = "".join(str(int(rng.choice(10, p=rng.dirichlet(1 + pos_counts[p])))) for p in range(4))
        if n not in out:
            out.append(n)
            break
    while True:  # 3) uniform
        n = f"{int(rng.integers(10_000)):04d}"
        if n not in out:
            out.append(n)
            break
    return [
        {"lens": "Most common pattern", "numbers": out[0],
         "rationale": "All four digits different, the most common pattern (50.4% of numbers). Every number still has the same odds."},
        {"lens": "Bayesian digit posterior", "numbers": out[1],
         "rationale": "Each digit drawn from its position's posterior given past results. Posteriors are almost uniform."},
        {"lens": "Pure random", "numbers": out[2],
         "rationale": "Uniform 0000–9999. 4D pays fixed prizes, so no number is worth more than another."},
    ]


# ---------------------------------------------------------------- draw dates
def next_fourd_date(now: datetime | None = None) -> date:
    now = now or datetime.now()
    d = now.date()
    if d.weekday() in FOURD_DRAW_DAYS and now.time() < DRAW_TIME:
        return d
    d += timedelta(days=1)
    while d.weekday() not in FOURD_DRAW_DAYS:
        d += timedelta(days=1)
    return d


def next_toto_date(conn) -> date:
    from sgpools import scraper
    nxt = scraper.fetch_next_toto()
    db.record_next_toto(conn, nxt)
    return nxt.draw_date


# ---------------------------------------------------------------- persistence
def get_picks(conn, game: str, draw_date: date) -> list[dict]:
    rows = conn.execute("SELECT * FROM picks WHERE game=? AND draw_date=? ORDER BY set_no",
                        (game, draw_date.isoformat())).fetchall()
    return [dict(r, numbers=json.loads(r["numbers"])) for r in rows]


def ensure(conn, game: str, draw_date: date, regenerate: bool = False) -> bool:
    """Create picks for (game, draw_date) if missing. Returns True if new picks were written."""
    existing = get_picks(conn, game, draw_date)
    if existing and not regenerate:
        return False
    salt = (max(r["salt"] for r in existing) + 1) if existing else 0
    sets = _toto_sets(conn, draw_date, salt) if game == "toto" else _fourd_sets(conn, draw_date, salt)
    with conn:
        conn.execute("DELETE FROM picks WHERE game=? AND draw_date=?", (game, draw_date.isoformat()))
        conn.executemany(
            "INSERT INTO picks (game, draw_date, set_no, lens, numbers, rationale, salt, created_at) VALUES (?,?,?,?,?,?,?,?)",
            [(game, draw_date.isoformat(), i, s["lens"], json.dumps(s["numbers"]), s["rationale"], salt, db.now())
             for i, s in enumerate(sets, 1)])
    return True


def ensure_next(conn, regenerate: bool = False) -> tuple[dict[str, date], bool]:
    """Make sure the next TOTO and 4D draws have picks. Returns (dates, any_new_picks)."""
    dates = {"toto": next_toto_date(conn), "fourd": next_fourd_date()}
    created = [ensure(conn, game, d, regenerate) for game, d in dates.items()]
    return dates, any(created)


# ---------------------------------------------------------------- scoring
TOTO_GROUPS = {(6, False): 1, (6, True): 1, (5, True): 2, (5, False): 3, (4, True): 4,
               (4, False): 5, (3, True): 6, (3, False): 7}


def score_toto(nums: list[int], win: list[int], additional: int) -> tuple[int, bool, int | None]:
    m = len(set(nums) & set(win))
    add = additional in nums
    return m, add, TOTO_GROUPS.get((m, add))


def score_past(conn) -> int:
    """Score stored picks whose draw has a result. Returns number of picks scored."""
    n = 0
    pending = conn.execute("SELECT * FROM picks WHERE result IS NULL").fetchall()
    latest = {g: conn.execute(f"SELECT MAX(draw_date) FROM {t}").fetchone()[0] for g, t in (("toto", "toto_draws"), ("fourd", "fourd_draws"))}
    with conn:
        for p in pending:
            nums = json.loads(p["numbers"])
            if p["game"] == "toto":
                d = conn.execute("SELECT * FROM toto_draws WHERE draw_date=?", (p["draw_date"],)).fetchone()
                if d is None:
                    if latest["toto"] and p["draw_date"] < latest["toto"]:
                        conn.execute("UPDATE picks SET result=? WHERE game=? AND draw_date=? AND set_no=?",
                                     (json.dumps({"no_draw": True}), p["game"], p["draw_date"], p["set_no"]))
                    continue
                win = [d[f"n{i}"] for i in range(1, 7)]
                m, add, group = score_toto(nums, win, d["additional"])
                amt = None
                if group:
                    r = conn.execute("SELECT share_amount FROM toto_prizes WHERE draw_no=? AND prize_group=?", (d["draw_no"], group)).fetchone()
                    amt = r[0] if r else None
                result = {"draw_no": d["draw_no"], "matched": m, "additional": add, "group": group, "amount": amt}
                prize = f"Group {group}" if group else None
            else:
                d = conn.execute("SELECT draw_no FROM fourd_draws WHERE draw_date=?", (p["draw_date"],)).fetchone()
                if d is None:
                    if latest["fourd"] and p["draw_date"] < latest["fourd"]:
                        conn.execute("UPDATE picks SET result=? WHERE game=? AND draw_date=? AND set_no=?",
                                     (json.dumps({"no_draw": True}), p["game"], p["draw_date"], p["set_no"]))
                    continue
                hit = conn.execute("SELECT category FROM fourd_numbers WHERE draw_no=? AND number=?", (d["draw_no"], nums)).fetchone()
                result = {"draw_no": d["draw_no"], "category": hit[0] if hit else None}
                prize = hit[0] if hit else None
            conn.execute("UPDATE picks SET result=?, prize=? WHERE game=? AND draw_date=? AND set_no=?",
                         (json.dumps(result), prize, p["game"], p["draw_date"], p["set_no"]))
            n += 1
    return n


# ---------------------------------------------------------------- report payload
def report_data(conn) -> dict:
    out = {}
    for game, p_any in (("toto", P_TOTO_ANY), ("fourd", P_4D_ANY)):
        dates = [r[0] for r in conn.execute("SELECT DISTINCT draw_date FROM picks WHERE game=? ORDER BY draw_date", (game,))]
        pending = [d for d in dates if conn.execute(
            "SELECT 1 FROM picks WHERE game=? AND draw_date=? AND result IS NULL", (game, d)).fetchone()]
        scored = [d for d in dates if d not in pending]
        nxt = pending[-1] if pending else None
        last = scored[-1] if scored else None
        rows = [dict(r) for r in conn.execute("SELECT * FROM picks WHERE game=? AND result IS NOT NULL", (game,))]
        real = [r for r in rows if not json.loads(r["result"]).get("no_draw")]
        g = {"next": None, "last": None,
             "record": {"since": scored[0] if scored else None, "sets": len(real),
                        "prizes": sum(1 for r in real if r["prize"]), "expected": len(real) * p_any}}
        if nxt:
            g["next"] = {"date": nxt, "sets": [{k: s[k] for k in ("lens", "numbers", "rationale")}
                                              for s in get_picks(conn, game, date.fromisoformat(nxt))]}
        if last:
            sets = get_picks(conn, game, date.fromisoformat(last))
            res = json.loads(sets[0]["result"]) if sets else {}
            draw = None
            if game == "toto" and res.get("draw_no"):
                d = conn.execute("SELECT * FROM toto_draws WHERE draw_no=?", (res["draw_no"],)).fetchone()
                draw = {"nums": [d[f"n{i}"] for i in range(1, 7)], "add": d["additional"]}
            elif game == "fourd" and res.get("draw_no"):
                draw = {"winners": [r[0] for r in conn.execute("SELECT number FROM fourd_numbers WHERE draw_no=?", (res["draw_no"],))]}
            g["last"] = {"date": last, "draw": draw,
                         "sets": [{"lens": s["lens"], "numbers": s["numbers"], "result": json.loads(s["result"]), "prize": s["prize"]} for s in sets]}
        out[game] = g
    out["popularity"] = popularity_model(conn)
    out["toto_odds"] = TOTO_ODDS
    out["p_toto_any"] = P_TOTO_ANY
    out["p_4d_any"] = P_4D_ANY
    return out
