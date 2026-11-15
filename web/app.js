/* Page logic: builds every chart spec from DATA and wires up controls. */
(function () {
  "use strict";
  const W = window.WGLCharts;
  const $ = (id) => document.getElementById(id);
  const T = DATA.toto, F = DATA.fourd;
  const fmt = (v, d = 0) => Number(v).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d });
  const fmtP = (p) => (p == null || isNaN(p) ? "–" : p < 0.001 ? "<0.001" : p.toFixed(3));
  const money = (v) => (v == null ? "–" : "$" + fmt(v));
  const intTicks = (lo, hi, step) => { const o = []; for (let v = lo; v <= hi; v += step) o.push({ v, label: String(v) }); return o; };
  const BAR_R = 4;

  $("meta").textContent =
    `TOTO ${T.first_date} → ${T.last_date} · 4D ${F.first_date} → ${F.last_date} · ${fmt(DATA.mc_sims)} Monte Carlo simulations`;

  // ---------------- theme + tabs
  $("theme").addEventListener("click", () => {
    const root = document.documentElement;
    const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    W.renderAll();
  });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => W.renderAll());
  document.querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((x) => x.setAttribute("aria-selected", x === b));
    $("tab-toto").hidden = b.dataset.tab !== "toto";
    $("tab-fourd").hidden = b.dataset.tab !== "fourd";
    W.renderAll();
  }));
  if (!W.supported()) $("nogl").hidden = false;
  if (location.hash === "#4d") document.querySelector('.tab[data-tab="fourd"]').click();

  // ---------------- shared builders
  function histSpec(hist, observed, title) {
    const { counts, edges } = hist;
    const max = Math.max(...counts);
    const xs = [Math.min(edges[0], observed), Math.max(edges[edges.length - 1], observed)];
    const span = xs[1] - xs[0] || 1;
    xs[0] -= span * 0.03; xs[1] += span * 0.03;
    const dec = span < 2 ? 3 : span < 20 ? 1 : 0;
    return {
      x: xs, y: [0, max * 1.1], height: 220,
      xTicks: W.niceTicks(xs[0], xs[1], 5, (v) => fmt(v, dec)), yTicks: W.niceTicks(0, max * 1.1, 4),
      xTitle: title, yTitle: "simulations",
      marks: [
        { type: "rect", round: 2, items: counts.map((c, i) => ({
          x0: edges[i], x1: edges[i + 1] - (edges[1] - edges[0]) * 0.12, y0: 0, y1: c, color: "var(--band)", alpha: 0.55,
          tip: `<b>${fmt(edges[i], dec)} – ${fmt(edges[i + 1], dec)}</b><br>${fmt(c)} of ${fmt(DATA.mc_sims)} fair simulations`,
        })) },
        { type: "vline", x: observed, color: "var(--series-2)", width: 2 },
      ],
      legend: [{ label: "fair simulations", color: "var(--band)", kind: "swatch" }, { label: `observed = ${fmt(observed, dec)}`, color: "var(--series-2)", kind: "line" }],
    };
  }

  function testsTable(el, tests, nullHists, onSelect) {
    const rows = tests.map((t) => {
      const ok = t.q_bh >= 0.05;
      const has = !!nullHists[t.id];
      return `<tr data-id="${t.id}" class="${has ? "clickable" : ""}" title="${t.question}">
        <td>${t.name}<div class="muted">${t.question}</div></td>
        <td class="num">${fmt(t.stat, Math.abs(t.stat) < 10 ? 3 : 1)}</td>
        <td class="num">${fmtP(t.p)}${t.p_mc != null ? "" : "<span class='muted'>*</span>"}</td>
        <td class="num">${fmtP(t.q_bh)}</td>
        <td><span class="verdict ${ok ? "ok" : "flag"}">${ok ? "✓ Fair" : "⚠ Unusual"}</span></td></tr>`;
    }).join("");
    el.innerHTML = `<thead><tr><th>Test</th><th class="num">Statistic</th><th class="num">p</th><th class="num">q (BH)</th><th>Verdict</th></tr></thead><tbody>${rows}</tbody>
      <tfoot><tr><td colspan="5" class="muted">* classical (analytic) p-value; others are empirical from ${fmt(DATA.mc_sims)} simulations.</td></tr></tfoot>`;
    el.querySelectorAll("tr.clickable").forEach((tr) => tr.addEventListener("click", () => {
      el.querySelectorAll("tr").forEach((x) => x.classList.toggle("sel", x === tr));
      onSelect(tests.find((t) => t.id === tr.dataset.id));
    }));
    const first = el.querySelector("tr.clickable");
    if (first) first.classList.add("sel");
    return tests.find((t) => nullHists[t.id]);
  }

  function observedVsExpected(labels, observed, expected, opts = {}) {
    const max = Math.max(...observed, ...expected) * 1.12;
    const n = labels.length;
    return {
      x: [-0.6, n - 0.4], y: [0, max], height: opts.height || 240, pad: { b: opts.padB || 30 },
      xTicks: labels.map((l, i) => ({ v: i, label: String(l) })), yTicks: W.niceTicks(0, max, 4),
      xTitle: opts.xTitle, yTitle: opts.yTitle || "count",
      marks: [
        { type: "rect", round: BAR_R, items: observed.map((o, i) => ({
          x0: i - 0.32, x1: i + 0.32, y0: 0, y1: o, color: "var(--series-1)",
          tip: `<b>${labels[i]}</b><br>Observed: ${fmt(o)}<br>Expected: ${fmt(expected[i], 1)}<br>Ratio: ${expected[i] ? fmt(o / expected[i], 2) : "–"}×`,
        })) },
        { type: "rect", round: 0, items: expected.map((e, i) => ({ x0: i - 0.42, x1: i + 0.42, y0: e - max * 0.004, y1: e + max * 0.004, color: "var(--text-1)" })) },
      ],
      legend: [{ label: "observed", color: "var(--series-1)" }, { label: "expected if fair", color: "var(--text-1)", kind: "line" }],
    };
  }

  function lineOverBars(labelsX, observed, expected, opts) {
    const max = Math.max(...observed, ...expected) * 1.12;
    const step = opts.tickStep || 1;
    return {
      x: [opts.x0 - 0.6, opts.x0 + observed.length - 0.4], y: [0, max], height: opts.height || 240,
      xTicks: labelsX.map((l, i) => ({ v: opts.x0 + i, label: l })).filter((_, i) => i % step === 0),
      yTicks: W.niceTicks(0, max, 4), xTitle: opts.xTitle, yTitle: opts.yTitle || "count",
      marks: [
        { type: "rect", round: 2, hitBand: true, items: observed.map((o, i) => ({
          x0: opts.x0 + i - 0.38, x1: opts.x0 + i + 0.38, y0: 0, y1: o, color: "var(--series-1)",
          tip: `<b>${opts.tipLabel(i)}</b><br>Observed: ${fmt(o)}<br>Expected: ${fmt(expected[i], 1)}`,
        })) },
        { type: "line", points: expected.map((e, i) => [opts.x0 + i, e]), color: "var(--series-2)", width: 2 },
      ],
      legend: [{ label: "observed", color: "var(--series-1)" }, { label: opts.expLabel || "expected if fair", color: "var(--series-2)", kind: "line" }],
    };
  }

  // ================================================================ TOTO
  const passT = T.tests.filter((t) => t.q_bh >= 0.05).length;
  $("t-kpi-draws").textContent = fmt(T.n_draws);
  $("t-kpi-tests").textContent = `${passT} / ${T.tests.length}`;
  const bf1 = T.bayes.bayes_factors[0].log10_bf_fair;
  $("t-kpi-bf").textContent = bf1 > 6 ? `10^${fmt(bf1, 0)} : 1` : `${fmt(Math.pow(10, bf1), bf1 > 2 ? 0 : 1)} : 1`;
  $("t-kpi-pany").textContent = `${T.bayes.n_confident_over + T.bayes.n_confident_under} / 49`;
  $("t-kpi-pany-l").textContent = `numbers confidently biased (≥95% posterior of being ≥10% over/under fair). Fair machines show ~${fmt(T.bayes.confident_null_mean, 1)} by chance.`;
  $("t-bf-note").innerHTML = "Bayes factor (fair : biased) by prior concentration α — smaller α = prior expects stronger bias: " +
    T.bayes.bayes_factors.map((b) => `α=${b.alpha}: 10<sup>${fmt(b.log10_bf_fair, 1)}</sup>`).join(" · ") +
    `. Above 1 favours a fair machine. Treats each ball as an independent categorical draw (standard approximation; real draws are without replacement within a draw).`;

  // frequency window select
  const sel = $("t-window");
  sel.innerHTML = T.windows.map((w) => `<option value="${w}">${T.freq[w].label} (${T.freq[w].draws} draws)</option>`).join("");
  sel.value = T.windows[T.windows.length - 1];
  const freqChart = W.chart($("c-freq"), () => {
    const f = T.freq[sel.value];
    const max = Math.max(...f.observed, f.fw_hi) * 1.1;
    return {
      x: [0.4, 49.6], y: [0, max], height: 300, aria: "Bar chart of draw frequency per TOTO number",
      xTicks: intTicks(1, 49, 1).filter((t) => t.v === 1 || t.v % 4 === 0 || t.v === 49), yTicks: W.niceTicks(0, max, 5),
      xTitle: "number", yTitle: "times drawn",
      marks: [
        { type: "hband", y0: f.band_lo, y1: f.band_hi, color: "var(--band)", alpha: 0.13 },
        { type: "hline", y: f.fw_hi, color: "var(--text-3)", dash: true },
        { type: "hline", y: f.fw_lo, color: "var(--text-3)", dash: true },
        { type: "hline", y: f.expected, color: "var(--text-2)", width: 1 },
        { type: "rect", round: BAR_R, hitBand: true, items: f.observed.map((c, i) => ({
          x0: i + 1 - 0.36, x1: i + 1 + 0.36, y0: 0, y1: c,
          color: c > f.band_hi || c < f.band_lo ? "var(--series-2)" : "var(--series-1)",
          tip: `<b>Number ${i + 1}</b><br>Drawn ${c}× (expected ${fmt(f.expected, 1)})<br>As additional: ${f.additional[i]}×<br>` +
            `Fair 90% range: ${fmt(f.band_lo)}–${fmt(f.band_hi)}`,
        })) },
      ],
      legend: [
        { label: "inside 90% fair band", color: "var(--series-1)" }, { label: "outside (≈5 of 49 expected by chance)", color: "var(--series-2)" },
        { label: "90% fair band", color: "var(--band)", kind: "band" }, { label: "hottest/coldest range", color: "var(--text-3)", kind: "dash" },
      ],
    };
  });
  sel.addEventListener("change", () => freqChart.render());

  // bayes
  W.chart($("c-bayes"), () => {
    const b = T.bayes;
    const lo = Math.min(...b.per.map((p) => p.lo)) * 0.95, hi = Math.max(...b.per.map((p) => p.hi)) * 1.03;
    return {
      x: [0.4, 49.6], y: [lo, hi], height: 260, aria: "Posterior credible intervals per number",
      xTicks: intTicks(1, 49, 1).filter((t) => t.v === 1 || t.v % 4 === 0 || t.v === 49),
      yTicks: W.niceTicks(lo, hi, 5, (v) => fmt(v * 100, 2) + "%"), xTitle: "number", yTitle: "P(ball = number)",
      marks: [
        { type: "rect", round: 3, hitBand: true, items: b.per.map((p) => ({
          x0: p.label - 0.22, x1: p.label + 0.22, y0: p.lo, y1: p.hi, color: "var(--series-1)", alpha: 0.4,
          tip: `<b>Number ${p.label}</b><br>Posterior mean ${fmt(p.mean * 100, 3)}% (fair ${fmt(b.fair * 100, 3)}%)<br>` +
            `95% CI ${fmt(p.lo * 100, 2)}–${fmt(p.hi * 100, 2)}%<br>P(≥10% over fair) = ${fmt(p.p_over * 100, 1)}%<br>P(≥10% under) = ${fmt(p.p_under * 100, 1)}%`,
        })) },
        { type: "rect", round: 0, items: b.per.map((p) => ({ x0: p.label - 0.3, x1: p.label + 0.3, y0: p.mean - (hi - lo) * 0.004, y1: p.mean + (hi - lo) * 0.004, color: "var(--series-1)" })) },
        { type: "hline", y: b.fair, color: "var(--series-2)", dash: true, width: 1.5 },
      ],
      legend: [{ label: "95% credible interval", color: "var(--series-1)", kind: "band" }, { label: "posterior mean", color: "var(--series-1)", kind: "line" }, { label: "fair = 1/49", color: "var(--series-2)", kind: "dash" }],
    };
  });

  // tests + null
  let tSel;
  const tNull = W.chart($("c-null"), () => { $("t-null-title").textContent = tSel.name; return histSpec(T.null[tSel.id], tSel.stat, "statistic"); });
  tSel = testsTable($("t-tests"), T.tests, T.null, (t) => { tSel = t; tNull.render(); });

  // sums
  $("t-sum-note").textContent = `Observed mean ${fmt(T.sums.mean, 1)} vs fair ${fmt(T.sums.fair_mean, 1)}. Line = exact fair distribution (from simulations).`;
  W.chart($("c-sum"), () => {
    const e = T.sums.observed.edges, c = T.sums.observed.counts;
    return lineOverBars(c.map((_, i) => String(e[i])), c, T.sums.fair, {
      x0: 0, tickStep: 3, xTitle: "sum", yTitle: "draws", tipLabel: (i) => `Sum ${e[i]}–${e[i + 1] - 1}` });
  });

  // balance
  const balSel = $("t-balance");
  const balChart = W.chart($("c-balance"), () => {
    const b = T[balSel.value];
    return observedVsExpected([0, 1, 2, 3, 4, 5, 6], b.observed, b.expected, { xTitle: b.label, yTitle: "draws" });
  });
  balSel.addEventListener("change", () => balChart.render());

  // pairs heatmap
  W.chart($("c-pairs"), () => {
    const size = Math.min($("c-pairs").clientWidth, 620);
    const items = [];
    T.pairs.z.forEach((row, i) => row.forEach((z, j) => {
      if (i === j) return;
      items.push({ x0: j + 0.5, x1: j + 1.5, y0: i + 0.5, y1: i + 1.5, color: W.diverging(z / 3.5),
        tip: `<b>${i + 1} & ${j + 1}</b><br>Together ${fmt(z * Math.sqrt(T.pairs.expected) + T.pairs.expected, 0)}× (expected ${fmt(T.pairs.expected, 1)})<br>z = ${fmt(z, 2)}` });
    }));
    const ticks = intTicks(1, 49, 1).filter((t) => t.v === 1 || t.v % 6 === 0);
    return {
      x: [0.5, 49.5], y: [49.5, 0.5], height: size - 20, pad: { l: 30, r: Math.max(14, $("c-pairs").clientWidth - size + 14), t: 4, b: 24 },
      xTicks: ticks, yLeftLabels: ticks, marks: [{ type: "rect", round: 0, items }],
      legend: [{ label: "fewer than expected", color: "var(--div-neg)" }, { label: "as expected", color: "var(--div-mid)" }, { label: "more than expected", color: "var(--div-pos)" }],
      aria: "Heatmap of pair co-occurrence z-scores",
    };
  });
  $("t-pairs-note").textContent = `Expected per pair: ${fmt(T.pairs.expected, 1)} times. See the “Most frequent pair” test for whether the top pair is surprising.`;
  $("t-pairs").innerHTML = `<thead><tr><th>Pair</th><th class="num">Times together</th></tr></thead><tbody>` +
    T.pairs.top.map((p) => `<tr><td><span class="balls"><span class="ball">${p.a}</span><span class="ball">${p.b}</span></span></td><td class="num">${p.count}</td></tr>`).join("") + "</tbody>";

  // gaps
  W.chart($("c-gaps"), () => lineOverBars(T.gaps.labels, T.gaps.observed, T.gaps.expected, {
    x0: 1, tickStep: 2, xTitle: "draws until it appears again", yTitle: "gaps", expLabel: "geometric (memoryless)", tipLabel: (i) => `Gap ${T.gaps.labels[i]}` }));

  // prize line
  W.chart($("c-prize"), () => {
    const d = T.draws.filter((x) => x.g1 != null);
    const max = Math.max(...d.map((x) => x.g1)) * 1.08;
    const months = [];
    d.forEach((x, i) => { const m = x.date.slice(0, 7); if (!months.length || months[months.length - 1].m !== m) months.push({ m, i }); });
    return {
      x: [0, d.length - 1], y: [0, max], height: 240, aria: "Line chart of Group 1 prize per draw",
      xTicks: months.filter((_, k) => k % 3 === 0).map((m) => ({ v: m.i, label: new Date(m.m + "-01").toLocaleDateString(undefined, { month: "short", year: "2-digit" }) })),
      yTicks: W.niceTicks(0, max, 4, (v) => "$" + fmt(v / 1e6, 0) + "M"), yTitle: "Group 1 prize",
      marks: [{ type: "line", points: d.map((x, i) => [i, x.g1]), color: "var(--series-1)", width: 2,
        tips: d.map((x) => `<b>${x.date}</b> · Draw ${x.no}<br>Group 1 prize: ${money(x.g1)}`) }],
    };
  });

  // recent
  $("t-recent").innerHTML = `<thead><tr><th>Draw</th><th>Date</th><th>Winning numbers</th><th>Additional</th><th class="num">Group 1 prize</th></tr></thead><tbody>` +
    T.draws.slice(-15).reverse().map((d) => `<tr><td>${d.no}</td><td>${d.date}</td><td><span class="balls">${d.nums.map((n) => `<span class="ball">${n}</span>`).join("")}</span></td>
      <td><span class="ball add">${d.add}</span></td><td class="num">${money(d.g1)}</td></tr>`).join("") + "</tbody>";

  // ================================================================ 4D
  const passF = F.tests.filter((t) => t.q_bh >= 0.05).length;
  $("f-kpi-draws").textContent = fmt(F.n_draws);
  $("f-kpi-nums").textContent = fmt(F.n_numbers);
  $("f-kpi-tests").textContent = `${passF} / ${F.tests.length}`;
  const minBf = Math.min(...F.bayes.map((b) => b.bayes_factors[0].log10_bf_fair));
  $("f-kpi-bf").textContent = minBf > 6 ? `10^${fmt(minBf, 0)} : 1` : `${fmt(Math.pow(10, minBf), minBf > 2 ? 0 : 1)} : 1`;

  W.chart($("c-heat"), () => {
    const items = [];
    F.pos_counts.forEach((row, p) => row.forEach((c, d) => {
      const z = (c - F.expected) / Math.sqrt(F.expected * 0.9);
      items.push({ x0: d - 0.48, x1: d + 0.48, y0: p - 0.46, y1: p + 0.46, color: W.diverging(z / 3), round: 3,
        tip: `<b>Position ${p + 1}, digit ${d}</b><br>${fmt(c)} times (expected ${fmt(F.expected, 1)})<br>z = ${fmt(z, 2)}` });
    }));
    return {
      x: [-0.5, 9.5], y: [3.5, -0.5], height: 220, pad: { l: 52 },
      xTicks: intTicks(0, 9, 1), yLeftLabels: [0, 1, 2, 3].map((p) => ({ v: p, label: `Pos ${p + 1}` })), xTitle: "digit",
      marks: [{ type: "rect", items }],
      legend: [{ label: "fewer", color: "var(--div-neg)" }, { label: "as expected", color: "var(--div-mid)" }, { label: "more", color: "var(--div-pos)" }],
    };
  });

  W.chart($("c-fbayes"), () => {
    const all = F.bayes.flatMap((b) => b.per);
    const lo = Math.min(...all.map((p) => p.lo)) * 0.97, hi = Math.max(...all.map((p) => p.hi)) * 1.02;
    const items = [], means = [];
    F.bayes.forEach((b, p) => b.per.forEach((d) => {
      const x = p * 11 + d.label;
      items.push({ x0: x - 0.3, x1: x + 0.3, y0: d.lo, y1: d.hi, color: "var(--series-1)", alpha: 0.4,
        tip: `<b>Position ${p + 1}, digit ${d.label}</b><br>Posterior mean ${fmt(d.mean * 100, 2)}%<br>95% CI ${fmt(d.lo * 100, 2)}–${fmt(d.hi * 100, 2)}%<br>P(≥10% over fair) = ${fmt(d.p_over * 100, 1)}%` });
      means.push({ x0: x - 0.38, x1: x + 0.38, y0: d.mean - (hi - lo) * 0.005, y1: d.mean + (hi - lo) * 0.005, color: "var(--series-1)" });
    }));
    return {
      x: [-0.8, 42.8], y: [lo, hi], height: 240,
      xTicks: [0, 1, 2, 3].map((p) => ({ v: p * 11 + 4.5, label: `Position ${p + 1} (0–9)` })),
      yTicks: W.niceTicks(lo, hi, 4, (v) => fmt(v * 100, 1) + "%"),
      marks: [{ type: "rect", round: 3, hitBand: true, items }, { type: "rect", items: means }, { type: "hline", y: 0.1, color: "var(--series-2)", dash: true }],
      legend: [{ label: "95% credible interval", color: "var(--series-1)", kind: "band" }, { label: "fair = 10%", color: "var(--series-2)", kind: "dash" }],
    };
  });

  let fSel;
  const fNull = W.chart($("c-fnull"), () => { $("f-null-title").textContent = fSel.name; return histSpec(F.null[fSel.id], fSel.stat, "statistic"); });
  fSel = testsTable($("f-tests"), F.tests, F.null, (t) => { fSel = t; fNull.render(); });

  $("f-pal-note").textContent = `Share of numbers by repeated-digit pattern vs exact fair rates. Palindromes (e.g. 1221): ${F.palindromes.observed} observed vs ${fmt(F.palindromes.expected, 1)} expected.`;
  W.chart($("c-patterns"), () => observedVsExpected(F.patterns.labels, F.patterns.observed, F.patterns.expected, { xTitle: "pattern", yTitle: "numbers" }));

  W.chart($("c-dsum"), () => lineOverBars(F.digit_sum.observed.map((_, i) => String(i)), F.digit_sum.observed, F.digit_sum.expected, {
    x0: 0, tickStep: 4, xTitle: "digit sum", yTitle: "numbers", tipLabel: (i) => `Digit sum ${i}` }));

  $("f-rep-note").textContent = `${fmt(F.repeats.distinct_repeated)} distinct numbers won more than once across ${fmt(F.n_draws)} draws. With 23 winners a draw out of 10,000, repeats are expected.`;
  $("f-repeats").innerHTML = `<thead><tr><th>Number</th><th class="num">Times won (any prize)</th></tr></thead><tbody>` +
    F.repeats.top.map((r) => `<tr><td>${r.number}</td><td class="num">${r.count}</td></tr>`).join("") + "</tbody>";
  $("f-recent").innerHTML = `<thead><tr><th>Draw</th><th>Date</th><th>1st prize</th></tr></thead><tbody>` +
    F.draws.slice(-12).reverse().map((d) => `<tr><td>${d.no}</td><td>${d.date}</td><td>${d.first || "–"}</td></tr>`).join("") + "</tbody>";

  W.renderAll();
})();
