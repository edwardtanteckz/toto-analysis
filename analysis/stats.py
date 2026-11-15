"""Randomness analysis for TOTO (6/49) and 4D.

Three lenses, all computed on the same data:
  * Monte Carlo baseline  - simulate many fair histories of the same length; every
    statistic gets a null distribution and an empirical p-value.
  * Bayesian Dirichlet-multinomial - "is any number biased?": posterior over the
    per-number probabilities, credible intervals, and a Bayes factor (fair vs biased).
  * Classical randomness tests - chi-square, runs, KS, serial correlation, gap test,
    with Benjamini-Hochberg correction across the family.
"""
from __future__ import annotations

import sqlite3
from math import comb

import numpy as np
from scipy import stats
from scipy.special import gammaln

TOTO_N, TOTO_K = 49, 6
MC_SIMS = 10_000
CHUNK = 250
SEED = 20261115


# ---------------------------------------------------------------- loading
def load_toto(conn: sqlite3.Connection):
    rows = conn.execute(
        "SELECT draw_no, draw_date, n1,n2,n3,n4,n5,n6, additional, group1_prize "
        "FROM toto_draws ORDER BY draw_no"
    ).fetchall()
    return [dict(r) for r in rows]


def load_fourd(conn: sqlite3.Connection):
    draws = [dict(r) for r in conn.execute("SELECT draw_no, draw_date FROM fourd_draws ORDER BY draw_no")]
    nums: dict[int, list[tuple[str, str]]] = {d["draw_no"]: [] for d in draws}
    for r in conn.execute("SELECT draw_no, category, number FROM fourd_numbers ORDER BY draw_no, category, position"):
        nums.setdefault(r["draw_no"], []).append((r["category"], r["number"]))
    for d in draws:
        d["numbers"] = nums.get(d["draw_no"], [])
    return draws


# ---------------------------------------------------------------- helpers
def bh_adjust(pvals: list[float]) -> list[float]:
    p = np.asarray(pvals, float)
    order = np.argsort(p)
    ranked = p[order] * len(p) / (np.arange(len(p)) + 1)
    adj = np.minimum.accumulate(ranked[::-1])[::-1].clip(max=1)
    out = np.empty_like(adj)
    out[order] = adj
    return out.tolist()


def emp_p(observed: float, sims: np.ndarray, side: str = "greater") -> float:
    """Empirical p-value with +1 correction."""
    if side == "greater":
        k = np.sum(sims >= observed)
    elif side == "less":
        k = np.sum(sims <= observed)
    else:  # two-sided around the null median
        med = np.median(sims)
        k = np.sum(np.abs(sims - med) >= abs(observed - med))
    return float((k + 1) / (len(sims) + 1))


def runs_z(binary: np.ndarray) -> np.ndarray:
    """Wald-Wolfowitz runs z-score along the last axis (vectorised)."""
    b = binary.astype(np.int8)
    n1 = b.sum(-1).astype(float)
    n = b.shape[-1]
    n0 = n - n1
    runs = 1 + np.sum(b[..., 1:] != b[..., :-1], axis=-1)
    mu = 2 * n1 * n0 / n + 1
    var = (mu - 1) * (mu - 2) / (n - 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        return (runs - mu) / np.sqrt(var)


def histogram(values, bins) -> dict:
    h, edges = np.histogram(values, bins=bins)
    return {"counts": h.tolist(), "edges": [float(e) for e in edges]}


def dirichlet_analysis(counts: np.ndarray, labels: list, alpha: float = 1.0, rng=None, threshold: float = 1.10) -> dict:
    """Posterior Dirichlet(alpha + counts) over len(counts) categories."""
    k = len(counts)
    n = int(counts.sum())
    post = alpha + counts
    total = post.sum()
    a, b = post, total - post
    p0 = 1.0 / k
    per = []
    for lab, c, ai, bi in zip(labels, counts, a, b):
        lo, hi = stats.beta.ppf([0.025, 0.975], ai, bi)
        per.append({
            "label": lab, "count": int(c),
            "mean": float(ai / total), "lo": float(lo), "hi": float(hi),
            "p_over": float(stats.beta.sf(p0 * threshold, ai, bi)),   # P(p_i > 1.1 * fair)
            "p_under": float(stats.beta.cdf(p0 / threshold, ai, bi)),
        })

    def log_bf01(al):  # log Bayes factor: fair-uniform vs Dirichlet(al) prior; multinomial coef cancels
        log_m_fair = n * np.log(p0)
        log_m_dm = gammaln(k * al) - gammaln(n + k * al) + np.sum(gammaln(counts + al) - gammaln(al))
        return float(log_m_fair - log_m_dm)

    bfs = [{"alpha": al, "log10_bf_fair": log_bf01(al) / np.log(10)} for al in (1.0, 10.0, 100.0, 1000.0)]
    rng = rng or np.random.default_rng(SEED)
    samples = rng.dirichlet(post, size=20_000)
    max_ratio = samples.max(axis=1) * k
    return {
        "fair": p0, "threshold": threshold, "alpha": alpha, "n": n, "per": per,
        "bayes_factors": bfs,
        "p_any_over": float(np.mean(max_ratio > threshold)),
        # numbers we'd call biased: >=95% posterior probability of being >=10% off fair
        "n_confident_over": int(sum(p["p_over"] >= 0.95 for p in per)),
        "n_confident_under": int(sum(p["p_under"] >= 0.95 for p in per)),
        "max_ratio_ci": [float(np.quantile(max_ratio, 0.025)), float(np.quantile(max_ratio, 0.975))],
    }


def confident_null_mean(sim_counts: np.ndarray, bayes: dict) -> float:
    """Average number of 'confidently biased' categories in fair simulations (chance baseline)."""
    k = sim_counts.shape[1]
    a = bayes["alpha"] + sim_counts
    b = a.sum(1, keepdims=True) - a
    p0, th = bayes["fair"], bayes["threshold"]
    flagged = (stats.beta.sf(p0 * th, a, b) >= 0.95) | (stats.beta.cdf(p0 / th, a, b) >= 0.95)
    return float(flagged.sum(1).mean()) if k else 0.0


# ---------------------------------------------------------------- TOTO
def _toto_stats(ind: np.ndarray) -> dict[str, np.ndarray]:
    """Statistics for a batch of histories. ind: (S, N, 49) bool indicator."""
    S, N, K = ind.shape
    counts = ind.sum(1)                                        # (S,49)
    exp = N * TOTO_K / TOTO_N
    chi2 = ((counts - exp) ** 2 / exp).sum(1)
    nums = np.arange(1, K + 1)
    sums = (ind * nums).sum(2)                                 # (S,N)
    odd = (ind[..., 0::2]).sum(2)                              # numbers 1,3,5.. are odd
    # runs tests across draws
    rz_sum = runs_z(sums > np.median(sums, axis=1, keepdims=True))
    rz_odd = runs_z(odd >= 3)
    # lag-1 serial correlation of each number's appearance, averaged over numbers
    x = ind.astype(np.float32)
    x = x - x.mean(1, keepdims=True)
    num = (x[:, 1:] * x[:, :-1]).sum(1)
    den = (x * x).sum(1)
    with np.errstate(invalid="ignore", divide="ignore"):
        lag1 = np.nanmean(num / den, axis=1)
    # pair co-occurrence: max off-diagonal count
    xi = ind.astype(np.float32)
    pairs = np.einsum("sni,snj->sij", xi, xi)
    iu = np.triu_indices(K, 1)
    max_pair = pairs[:, iu[0], iu[1]].max(1)
    # gaps between consecutive appearances of the same number (pooled)
    flat = ind.transpose(0, 2, 1).reshape(S * K, N)
    r, c = np.nonzero(flat)
    same = r[1:] == r[:-1]
    gaps = (c[1:] - c[:-1])[same]
    gap_owner = (r[1:][same]) // K
    p = TOTO_K / TOTO_N
    edges = np.arange(1, 22)                                   # bins 1..20, 21+
    gk = np.minimum(gaps, 21)
    gap_hist = np.zeros((S, 21))
    np.add.at(gap_hist, (gap_owner, gk - 1), 1)
    probs = np.array([p * (1 - p) ** (g - 1) for g in range(1, 21)] + [(1 - p) ** 20])
    tot = gap_hist.sum(1, keepdims=True)
    gap_chi2 = ((gap_hist - tot * probs) ** 2 / (tot * probs)).sum(1)
    return {
        "counts": counts, "chi2": chi2, "max_count": counts.max(1), "min_count": counts.min(1),
        "sums": sums, "rz_sum": rz_sum, "rz_odd": rz_odd, "lag1": lag1,
        "max_pair": max_pair, "pairs": pairs, "gap_hist": gap_hist, "gap_chi2": gap_chi2,
        "gap_edges": edges, "gap_probs": probs,
    }


def _simulate_toto(N: int, sims: int, rng) -> np.ndarray:
    """(S, N, 49) indicator of fair 6-from-49 draws without replacement."""
    keys = rng.random((sims, N, TOTO_N), dtype=np.float32)
    idx = np.argpartition(keys, TOTO_K, axis=2)[..., :TOTO_K]
    ind = np.zeros((sims, N, TOTO_N), dtype=bool)
    np.put_along_axis(ind, idx, True, axis=2)
    return ind


def analyse_toto(draws: list[dict], sims: int = MC_SIMS, windows=(50, 100)) -> dict:
    rng = np.random.default_rng(SEED)
    N = len(draws)
    main = np.array([[d[f"n{i}"] for i in range(1, 7)] for d in draws])
    real = np.zeros((1, N, TOTO_N), dtype=bool)
    real[0, np.arange(N)[:, None], main - 1] = True
    obs = _toto_stats(real)

    win_list = [w for w in windows if w < N] + [N]
    keys = ["chi2", "max_count", "min_count", "rz_sum", "rz_odd", "lag1", "max_pair", "gap_chi2"]
    null = {k: [] for k in keys}
    win_counts = {w: [] for w in win_list}
    sum_hist_pool = np.zeros(300)
    for start in range(0, sims, CHUNK):
        s = min(CHUNK, sims - start)
        ind = _simulate_toto(N, s, rng)
        st = _toto_stats(ind)
        for k in keys:
            null[k].append(st[k])
        for w in win_list:
            win_counts[w].append(ind[:, -w:, :].sum(1))
        sum_hist_pool += np.bincount(st["sums"].ravel(), minlength=300)[:300]
    null = {k: np.concatenate(v) for k, v in null.items()}
    win_counts = {w: np.concatenate(v) for w, v in win_counts.items()}

    # KS: real sums vs the pooled fair-sum distribution; MC p from fresh sims vs same reference
    ref_cdf = np.cumsum(sum_hist_pool) / sum_hist_pool.sum()

    def ks_stat(sums_2d):
        h = np.apply_along_axis(lambda r: np.bincount(r, minlength=300)[:300], 1, sums_2d)
        return np.abs(np.cumsum(h, 1) / sums_2d.shape[1] - ref_cdf).max(1)

    ks_obs = float(ks_stat(obs["sums"])[0])
    ks_null = ks_stat(_toto_stats(_simulate_toto(N, 2000, rng))["sums"])

    # frequency windows: observed counts + MC envelopes (pointwise and family-wise)
    freq = {}
    for w in win_list:
        sim = win_counts[w]
        freq[str(w)] = {
            "label": "All draws" if w == N else f"Last {w}",
            "draws": w,
            "observed": real[0, -w:, :].sum(0).tolist(),
            "additional": np.bincount([d["additional"] for d in draws[-w:]], minlength=50)[1:].tolist(),
            "expected": w * TOTO_K / TOTO_N,
            "band_lo": float(np.quantile(sim, 0.05)), "band_hi": float(np.quantile(sim, 0.95)),
            "fw_lo": float(np.quantile(sim.min(1), 0.05)), "fw_hi": float(np.quantile(sim.max(1), 0.95)),
        }

    # sums
    sums = obs["sums"][0]
    support = np.arange(300)
    fair_pmf = sum_hist_pool / sum_hist_pool.sum()
    bins = np.arange(20, 285, 10)
    fair_binned = np.add.reduceat(fair_pmf[20:], bins[:-1] - 20)[: len(bins) - 1] * N

    # odd/even & low/high vs hypergeometric
    odd_counts = (main % 2 == 1).sum(1)
    low_counts = (main <= 24).sum(1)
    def hyper_block(counts, successes, label):
        pmf = stats.hypergeom.pmf(np.arange(7), TOTO_N, successes, TOTO_K)
        obs_h = np.bincount(counts, minlength=7)
        exp_h = pmf * N
        # merge sparse tails (0,1) and (5,6) for the chi-square
        o = np.array([obs_h[:2].sum(), *obs_h[2:5], obs_h[5:].sum()])
        e = np.array([exp_h[:2].sum(), *exp_h[2:5], exp_h[5:].sum()])
        chi = float(((o - e) ** 2 / e).sum())
        return {"label": label, "observed": obs_h.tolist(), "expected": exp_h.tolist(),
                "chi2": chi, "p": float(stats.chi2.sf(chi, len(o) - 1))}

    # pairs heatmap z-scores
    pair_counts = obs["pairs"][0]
    exp_pair = N * (TOTO_K * (TOTO_K - 1)) / (TOTO_N * (TOTO_N - 1))
    pz = (pair_counts - exp_pair) / np.sqrt(exp_pair)
    np.fill_diagonal(pz, 0)
    iu = np.triu_indices(TOTO_N, 1)
    top_idx = np.argsort(pair_counts[iu])[::-1][:10]
    top_pairs = [{"a": int(iu[0][i] + 1), "b": int(iu[1][i] + 1), "count": int(pair_counts[iu][i])} for i in top_idx]

    # gaps
    gap_obs = obs["gap_hist"][0]
    gap_exp = gap_obs.sum() * obs["gap_probs"]

    # tests (one row each)
    tests = [
        {"id": "chi2", "name": "Number frequency (chi-square)", "stat": float(obs["chi2"][0]),
         "p_classic": float(stats.chi2.sf(obs["chi2"][0], TOTO_N - 1)), "p_mc": emp_p(obs["chi2"][0], null["chi2"]),
         "question": "Do some numbers come up more often than others?"},
        {"id": "max_count", "name": "Hottest number (max count)", "stat": float(obs["max_count"][0]),
         "p_classic": None, "p_mc": emp_p(obs["max_count"][0], null["max_count"]),
         "question": "Is the most frequent number more frequent than chance allows?"},
        {"id": "min_count", "name": "Coldest number (min count)", "stat": float(obs["min_count"][0]),
         "p_classic": None, "p_mc": emp_p(obs["min_count"][0], null["min_count"], "less"),
         "question": "Is the least frequent number rarer than chance allows?"},
        {"id": "rz_sum", "name": "Runs test: sum above/below median", "stat": float(obs["rz_sum"][0]),
         "p_classic": float(2 * stats.norm.sf(abs(obs["rz_sum"][0]))), "p_mc": emp_p(obs["rz_sum"][0], null["rz_sum"], "two"),
         "question": "Do high-sum and low-sum draws cluster in streaks?"},
        {"id": "rz_odd", "name": "Runs test: odd-heavy draws", "stat": float(obs["rz_odd"][0]),
         "p_classic": float(2 * stats.norm.sf(abs(obs["rz_odd"][0]))), "p_mc": emp_p(obs["rz_odd"][0], null["rz_odd"], "two"),
         "question": "Do odd-heavy draws come in streaks?"},
        {"id": "ks_sum", "name": "Sum distribution (KS vs fair)", "stat": ks_obs,
         "p_classic": None, "p_mc": emp_p(ks_obs, ks_null),
         "question": "Does the sum of the 6 numbers follow the fair distribution?"},
        {"id": "lag1", "name": "Serial correlation (lag 1)", "stat": float(obs["lag1"][0]),
         "p_classic": None, "p_mc": emp_p(obs["lag1"][0], null["lag1"], "two"),
         "question": "Does a number appearing make it more/less likely next draw?"},
        {"id": "gap_chi2", "name": "Gap test (geometric)", "stat": float(obs["gap_chi2"][0]),
         "p_classic": float(stats.chi2.sf(obs["gap_chi2"][0], 20)), "p_mc": emp_p(obs["gap_chi2"][0], null["gap_chi2"]),
         "question": "Are waiting times between repeats of a number memoryless?"},
        {"id": "max_pair", "name": "Most frequent pair", "stat": float(obs["max_pair"][0]),
         "p_classic": None, "p_mc": emp_p(obs["max_pair"][0], null["max_pair"]),
         "question": "Is any pair of numbers drawn together suspiciously often?"},
    ]
    oe, lh = hyper_block(odd_counts, 25, "Odd numbers per draw"), hyper_block(low_counts, 24, "Low numbers (1-24) per draw")
    tests.append({"id": "odd", "name": "Odd/even split (hypergeometric)", "stat": oe["chi2"], "p_classic": oe["p"], "p_mc": None,
                  "question": "Is the odd/even balance per draw as expected?"})
    tests.append({"id": "low", "name": "Low/high split (hypergeometric)", "stat": lh["chi2"], "p_classic": lh["p"], "p_mc": None,
                  "question": "Is the low/high balance per draw as expected?"})
    _finish_tests(tests)

    null_hists = {k: histogram(null[k], 40) for k in keys}
    null_hists["ks_sum"] = histogram(ks_null, 40)

    bayes = dirichlet_analysis(real[0].sum(0), list(range(1, 50)), rng=rng)
    bayes["confident_null_mean"] = confident_null_mean(_simulate_toto(N, 1000, rng).sum(1), bayes)

    return {
        "n_draws": N,
        "first_date": draws[0]["draw_date"], "last_date": draws[-1]["draw_date"],
        "draws": [{"no": d["draw_no"], "date": d["draw_date"], "nums": [d[f"n{i}"] for i in range(1, 7)],
                   "add": d["additional"], "g1": d["group1_prize"]} for d in draws],
        "freq": freq, "windows": [str(w) for w in win_list],
        "bayes": bayes,
        "sums": {"observed": histogram(sums, bins), "fair": fair_binned.tolist(),
                 "mean": float(sums.mean()), "fair_mean": float((support * fair_pmf).sum())},
        "odd_even": oe, "low_high": lh,
        "pairs": {"z": np.round(pz, 2).tolist(), "expected": exp_pair, "top": top_pairs},
        "gaps": {"observed": gap_obs.tolist(), "expected": gap_exp.tolist(),
                 "labels": [str(g) for g in range(1, 21)] + ["21+"]},
        "tests": tests, "null": null_hists, "mc_sims": sims,
    }


def _finish_tests(tests):
    ps = [t["p_mc"] if t["p_mc"] is not None else t["p_classic"] for t in tests]
    for t, p, q in zip(tests, ps, bh_adjust(ps)):
        t["p"] = p
        t["q_bh"] = q
        t["verdict"] = "Consistent with fair draws" if q >= 0.05 else "Unusual - worth a closer look"


# ---------------------------------------------------------------- 4D
def _pattern(num: str) -> str:
    c = sorted(np.unique(list(num), return_counts=True)[1].tolist(), reverse=True)
    return {(1, 1, 1, 1): "All different", (2, 1, 1): "One pair", (2, 2): "Two pairs",
            (3, 1): "Triple", (4,): "Quad"}[tuple(c)]


PATTERNS = ["All different", "One pair", "Two pairs", "Triple", "Quad"]


def analyse_fourd(draws: list[dict], sims: int = MC_SIMS) -> dict:
    rng = np.random.default_rng(SEED + 1)
    all_nums = [n for d in draws for _, n in d["numbers"]]
    N = len(draws)
    per_draw = max(len(d["numbers"]) for d in draws) if draws else 23
    M = len(all_nums)
    digits = np.array([[int(ch) for ch in n] for n in all_nums])         # (M,4)
    pos_counts = np.stack([np.bincount(digits[:, p], minlength=10) for p in range(4)])  # (4,10)
    exp = M / 10
    pos_chi2 = ((pos_counts - exp) ** 2 / exp).sum(1)
    total_chi2 = float(pos_chi2.sum())

    # exact pattern / digit-sum / palindrome rates over 0000-9999
    universe = [f"{i:04d}" for i in range(10000)]
    pat_exp = {p: 0 for p in PATTERNS}
    for u in universe:
        pat_exp[_pattern(u)] += 1
    pat_obs = {p: 0 for p in PATTERNS}
    for n in all_nums:
        pat_obs[_pattern(n)] += 1
    o = np.array([pat_obs[p] for p in PATTERNS], float)
    e = np.array([pat_exp[p] / 10000 * M for p in PATTERNS])
    merge = slice(2, None)  # merge sparse classes (two pairs, triple, quad)
    oo = np.array([o[0], o[1], o[merge].sum()])
    ee = np.array([e[0], e[1], e[merge].sum()])
    pat_chi2 = float(((oo - ee) ** 2 / ee).sum())

    dsum_obs = digits.sum(1)
    dsum_exact = np.bincount([sum(map(int, u)) for u in universe], minlength=37) / 10000
    pal_obs = sum(1 for n in all_nums if n == n[::-1])

    # repeats: numbers appearing in >1 draw; MC with uniform draws (with replacement within a draw;
    # duplicates within a draw are ~2.5% likely and immaterial for these statistics)
    uniq, freq_counts = np.unique(np.array(all_nums), return_counts=True)
    repeats_obs = int((freq_counts > 1).sum())
    sim_chi2 = np.empty(sims)
    sim_rep = np.empty(sims)
    sim_dig = np.empty(sims)
    for i in range(sims):
        x = rng.integers(0, 10000, size=M)
        sim_rep[i] = M - len(np.unique(x))  # occurrences beyond first, close proxy
        d = np.stack([(x // 10 ** (3 - p)) % 10 for p in range(4)])
        pc = np.stack([np.bincount(d[p], minlength=10) for p in range(4)])
        sim_chi2[i] = ((pc - exp) ** 2 / exp).sum()
        sim_dig[i] = np.abs(pc - exp).max()
    rep_obs_proxy = M - len(uniq)

    # first-prize parity runs across draws
    first = [next((n for c, n in d["numbers"] if c == "first"), None) for d in draws]
    first = [f for f in first if f]
    rz_first = float(runs_z(np.array([int(f) >= 5000 for f in first]))) if len(first) > 10 else float("nan")

    tests = [
        {"id": "pos_chi2", "name": "Digit frequency, all positions (chi-square)", "stat": total_chi2,
         "p_classic": float(stats.chi2.sf(total_chi2, 36)), "p_mc": emp_p(total_chi2, sim_chi2),
         "question": "Are digits 0-9 equally likely in every position?"},
        *[
            {"id": f"pos{p+1}", "name": f"Digit frequency, position {p+1}", "stat": float(pos_chi2[p]),
             "p_classic": float(stats.chi2.sf(pos_chi2[p], 9)), "p_mc": None,
             "question": f"Are digits equally likely in position {p+1}?"}
            for p in range(4)
        ],
        {"id": "max_dev", "name": "Largest digit deviation", "stat": float(np.abs(pos_counts - exp).max()),
         "p_classic": None, "p_mc": emp_p(float(np.abs(pos_counts - exp).max()), sim_dig),
         "question": "Is any single position/digit cell too far from expected?"},
        {"id": "pattern", "name": "Digit patterns (pair/triple/quad)", "stat": pat_chi2,
         "p_classic": float(stats.chi2.sf(pat_chi2, 2)), "p_mc": None,
         "question": "Do repeated-digit patterns occur at the expected rates?"},
        {"id": "repeats", "name": "Numbers repeating across draws", "stat": float(rep_obs_proxy),
         "p_classic": None, "p_mc": emp_p(rep_obs_proxy, sim_rep, "two"),
         "question": "Do winning numbers repeat more/less than chance?"},
        {"id": "runs_first", "name": "Runs test: 1st prize high/low", "stat": rz_first,
         "p_classic": float(2 * stats.norm.sf(abs(rz_first))), "p_mc": None,
         "question": "Do high/low 1st-prize numbers come in streaks?"},
    ]
    _finish_tests(tests)

    bayes = [dirichlet_analysis(pos_counts[p], list(range(10)), rng=rng) for p in range(4)]
    return {
        "n_draws": N, "n_numbers": M, "per_draw": per_draw,
        "first_date": draws[0]["draw_date"], "last_date": draws[-1]["draw_date"],
        "pos_counts": pos_counts.tolist(), "expected": exp,
        "patterns": {"labels": PATTERNS, "observed": o.tolist(), "expected": e.tolist()},
        "palindromes": {"observed": pal_obs, "expected": 100 / 10000 * M},
        "digit_sum": {"observed": np.bincount(dsum_obs, minlength=37).tolist(), "expected": (dsum_exact * M).tolist()},
        "repeats": {"distinct_repeated": repeats_obs, "top": [
            {"number": str(n), "count": int(c)} for n, c in sorted(zip(uniq, freq_counts), key=lambda t: -t[1])[:10]]},
        "bayes": bayes,
        "tests": tests,
        "null": {"pos_chi2": histogram(sim_chi2, 40), "max_dev": histogram(sim_dig, 40), "repeats": histogram(sim_rep, 40)},
        "mc_sims": sims,
        "draws": [{"no": d["draw_no"], "date": d["draw_date"], "first": first_n} for d, first_n in
                  zip(draws, [next((n for c, n in d["numbers"] if c == "first"), None) for d in draws])],
    }
