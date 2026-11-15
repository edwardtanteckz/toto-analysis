/* Minimal WebGL chart renderer (no dependencies).
 *
 * One shared WebGL context renders every chart into an offscreen canvas, which is then
 * blitted onto each chart's own 2D canvas (avoids the browser's ~16-context limit).
 * Marks (bars, bands, grid, lines, heatmap cells) are drawn with WebGL; axis text is
 * drawn on the 2D canvas. Hover uses CPU hit-testing against the mark list.
 *
 * spec = {
 *   x: [min,max], y: [min,max], pad: {l,r,t,b},
 *   xTicks: [{v,label}], yTicks: [{v,label}], xTitle, yTitle,
 *   marks: [
 *     {type:'rect', items:[{x0,x1,y0,y1,color,tip,round}]},      // data coords
 *     {type:'line', points:[[x,y],...], color, width, tips:[...]},
 *     {type:'hband', y0, y1, color}, {type:'hline', y, color, width, dash}
 *   ],
 *   legend: [{label,color,kind:'swatch'|'line'|'band'}]
 * }
 */
(function () {
  "use strict";

  const VS = `
    attribute vec2 a_pos; attribute vec4 a_color; attribute vec4 a_rect; attribute float a_radius;
    uniform vec2 u_size;
    varying vec4 v_color; varying vec4 v_rect; varying float v_radius; varying vec2 v_px;
    void main(){
      v_color=a_color; v_rect=a_rect; v_radius=a_radius; v_px=a_pos;
      vec2 c = a_pos / u_size * 2.0 - 1.0;
      gl_Position = vec4(c.x, -c.y, 0.0, 1.0);
    }`;
  // Rounded-rect SDF for bar ends; radius < 0 disables it (line segments).
  const FS = `
    precision mediump float;
    varying vec4 v_color; varying vec4 v_rect; varying float v_radius; varying vec2 v_px;
    void main(){
      float alpha = 1.0;
      if (v_radius > 0.0) {
        vec2 center = (v_rect.xy + v_rect.zw) * 0.5;
        vec2 hs = abs(v_rect.zw - v_rect.xy) * 0.5;
        float r = min(v_radius, min(hs.x, hs.y));
        vec2 q = abs(v_px - center) - hs + r;
        float d = length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
        alpha = clamp(0.5 - d, 0.0, 1.0);
      }
      gl_FragColor = vec4(v_color.rgb * v_color.a * alpha, v_color.a * alpha);
    }`;

  let gl, glCanvas, prog, buf, loc;
  let glFailed = false;
  function initGL() {
    if (gl) return true;
    if (glFailed) return false;
    try { return setupGL(); } catch (e) { console.error(e); gl = null; glFailed = true; return false; }
  }
  function setupGL() {
    glCanvas = document.createElement("canvas");
    gl = glCanvas.getContext("webgl", { premultipliedAlpha: true, antialias: true, preserveDrawingBuffer: true });
    if (!gl) return false;
    const sh = (type, src) => {
      const s = gl.createShader(type);
      gl.shaderSource(s, src); gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
      return s;
    };
    prog = gl.createProgram();
    gl.attachShader(prog, sh(gl.VERTEX_SHADER, VS));
    gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, FS));
    gl.linkProgram(prog);
    gl.useProgram(prog);
    buf = gl.createBuffer();
    loc = {
      pos: gl.getAttribLocation(prog, "a_pos"), color: gl.getAttribLocation(prog, "a_color"),
      rect: gl.getAttribLocation(prog, "a_rect"), radius: gl.getAttribLocation(prog, "a_radius"),
      size: gl.getUniformLocation(prog, "u_size"),
    };
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    return true;
  }

  // ---- colour helpers
  const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  function rgba(c, a) {
    if (Array.isArray(c)) return c;
    if (c.startsWith("var(")) c = cssVar(c.slice(4, -1));
    const h = c.replace("#", "");
    const n = parseInt(h.length === 3 ? h.split("").map((x) => x + x).join("") : h, 16);
    return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255, a == null ? 1 : a];
  }
  function mix(a, b, t) { return a.map((v, i) => v + (b[i] - v) * t); }
  // Diverging: negative -> --div-neg, 0 -> --div-mid, positive -> --div-pos. v in [-1,1].
  function diverging(v) {
    const mid = rgba(cssVar("--div-mid")), neg = rgba(cssVar("--div-neg")), pos = rgba(cssVar("--div-pos"));
    const t = Math.max(-1, Math.min(1, v));
    return t < 0 ? mix(mid, neg, -t) : mix(mid, pos, t);
  }

  // ---- geometry -> vertex buffer (pos2 color4 rect4 radius1 = 11 floats)
  function pushQuad(out, x0, y0, x1, y1, color, radius) {
    const r = [Math.min(x0, x1), Math.min(y0, y1), Math.max(x0, x1), Math.max(y0, y1)];
    const v = (x, y) => out.push(x, y, color[0], color[1], color[2], color[3], r[0], r[1], r[2], r[3], radius);
    v(r[0], r[1]); v(r[2], r[1]); v(r[0], r[3]);
    v(r[0], r[3]); v(r[2], r[1]); v(r[2], r[3]);
  }
  function pushSegment(out, ax, ay, bx, by, w, color) {
    const dx = bx - ax, dy = by - ay, len = Math.hypot(dx, dy) || 1;
    const nx = (-dy / len) * w / 2, ny = (dx / len) * w / 2;
    const v = (x, y) => out.push(x, y, color[0], color[1], color[2], color[3], 0, 0, 0, 0, -1);
    v(ax + nx, ay + ny); v(bx + nx, by + ny); v(ax - nx, ay - ny);
    v(ax - nx, ay - ny); v(bx + nx, by + ny); v(bx - nx, by - ny);
  }

  const charts = [];
  let tooltip;

  class Chart {
    constructor(container, specFn) {
      this.el = container;
      this.specFn = specFn;
      this.canvas = document.createElement("canvas");
      this.canvas.setAttribute("role", "img");
      this.el.appendChild(this.canvas);
      this.legendEl = document.createElement("div");
      this.legendEl.className = "legend";
      this.el.appendChild(this.legendEl);
      this.hover = null;
      this.canvas.addEventListener("mousemove", (e) => this.onMove(e));
      this.canvas.addEventListener("mouseleave", () => { this.hover = null; hideTip(); this.render(); });
      this.canvas.addEventListener("touchstart", (e) => this.onMove(e.touches[0]), { passive: true });
      new ResizeObserver(() => this.render()).observe(this.el);
      charts.push(this);
    }

    layout(spec) {
      const pad = Object.assign({ l: 48, r: 14, t: 10, b: 30 }, spec.pad || {});
      const w = this.el.clientWidth, h = spec.height || 280;
      const sx = (v) => pad.l + ((v - spec.x[0]) / (spec.x[1] - spec.x[0])) * (w - pad.l - pad.r);
      const sy = (v) => h - pad.b - ((v - spec.y[0]) / (spec.y[1] - spec.y[0])) * (h - pad.t - pad.b);
      return { pad, w, h, sx, sy };
    }

    render() {
      if (!this.el.clientWidth || !initGL()) return;
      const spec = (this.spec = this.specFn());
      const L = (this.L = this.layout(spec));
      const dpr = window.devicePixelRatio || 1;
      const W = Math.round(L.w * dpr), H = Math.round(L.h * dpr);
      this.canvas.width = W; this.canvas.height = H;
      this.canvas.style.width = L.w + "px"; this.canvas.style.height = L.h + "px";
      this.canvas.setAttribute("aria-label", spec.aria || "");

      const out = [];
      const grid = rgba(cssVar("--grid"));
      for (const t of spec.yTicks || []) pushSegment(out, L.pad.l, L.sy(t.v), L.w - L.pad.r, L.sy(t.v), 1, grid);
      this.hits = [];
      for (const m of spec.marks) {
        if (m.type === "hband") {
          pushQuad(out, L.pad.l, L.sy(m.y0), L.w - L.pad.r, L.sy(m.y1), rgba(m.color, m.alpha ?? 1), -1);
        } else if (m.type === "rect") {
          for (const it of m.items) {
            const x0 = L.sx(it.x0), x1 = L.sx(it.x1), y0 = L.sy(it.y0), y1 = L.sy(it.y1);
            let c = rgba(it.color, it.alpha);
            if (this.hover && this.hover.item === it) c = mix(c, rgba(cssVar("--text-1")), 0.25);
            pushQuad(out, x0, y0, x1, y1, c, it.round ?? (m.round ?? 0));
            if (it.tip) this.hits.push({ x0: Math.min(x0, x1), x1: Math.max(x0, x1), y0: Math.min(y0, y1), y1: Math.max(y0, y1), item: it, band: m.hitBand });
          }
        } else if (m.type === "line") {
          const c = rgba(m.color), w = m.width || 2;
          const pts = m.points.map(([x, y]) => [L.sx(x), L.sy(y)]);
          for (let i = 1; i < pts.length; i++) pushSegment(out, pts[i - 1][0], pts[i - 1][1], pts[i][0], pts[i][1], w, c);
          if (m.tips) pts.forEach((p, i) => this.hits.push({ point: p, item: { tip: m.tips[i] }, line: true }));
          if (m.dots) for (const p of pts) pushQuad(out, p[0] - 4, p[1] - 4, p[0] + 4, p[1] + 4, c, 4);
        } else if (m.type === "hline") {
          const c = rgba(m.color), y = L.sy(m.y), w = m.width || 1.5;
          if (m.dash) {
            for (let x = L.pad.l; x < L.w - L.pad.r; x += 10) pushSegment(out, x, y, Math.min(x + 5, L.w - L.pad.r), y, w, c);
          } else pushSegment(out, L.pad.l, y, L.w - L.pad.r, y, w, c);
        } else if (m.type === "vline") {
          const c = rgba(m.color), x = L.sx(m.x);
          pushSegment(out, x, L.pad.t, x, L.h - L.pad.b, m.width || 2, c);
        }
      }
      // crosshair for line charts
      if (this.hover && this.hover.line) {
        pushSegment(out, this.hover.point[0], L.pad.t, this.hover.point[0], L.h - L.pad.b, 1, rgba(cssVar("--text-3")));
        const p = this.hover.point;
        pushQuad(out, p[0] - 5, p[1] - 5, p[0] + 5, p[1] + 5, rgba(cssVar("--surface-1")), 5);
        pushQuad(out, p[0] - 4, p[1] - 4, p[0] + 4, p[1] + 4, rgba(cssVar("--series-1")), 4);
      }

      // WebGL pass (coordinates in CSS px, scaled by dpr)
      glCanvas.width = W; glCanvas.height = H;
      gl.viewport(0, 0, W, H);
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
      const data = new Float32Array(out.map((v, i) => { const k = i % 11; return k < 2 || (k >= 6 && k < 10) || k === 10 && v > 0 ? v * dpr : v; }));
      gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      gl.bufferData(gl.ARRAY_BUFFER, data, gl.STREAM_DRAW);
      const S = 11 * 4;
      gl.enableVertexAttribArray(loc.pos); gl.vertexAttribPointer(loc.pos, 2, gl.FLOAT, false, S, 0);
      gl.enableVertexAttribArray(loc.color); gl.vertexAttribPointer(loc.color, 4, gl.FLOAT, false, S, 8);
      gl.enableVertexAttribArray(loc.rect); gl.vertexAttribPointer(loc.rect, 4, gl.FLOAT, false, S, 24);
      gl.enableVertexAttribArray(loc.radius); gl.vertexAttribPointer(loc.radius, 1, gl.FLOAT, false, S, 40);
      gl.uniform2f(loc.size, W, H);
      gl.drawArrays(gl.TRIANGLES, 0, data.length / 11);

      const ctx = this.canvas.getContext("2d");
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, W, H);
      ctx.drawImage(glCanvas, 0, 0);
      ctx.scale(dpr, dpr);
      this.drawAxes(ctx, spec, L);
      this.drawLegend(spec);
    }

    drawAxes(ctx, spec, L) {
      ctx.font = "11px ui-sans-serif, system-ui, -apple-system, sans-serif";
      ctx.fillStyle = cssVar("--text-2");
      ctx.textAlign = "right"; ctx.textBaseline = "middle";
      for (const t of spec.yTicks || []) ctx.fillText(t.label, L.pad.l - 6, L.sy(t.v));
      ctx.textAlign = "center"; ctx.textBaseline = "top";
      let lastRight = -Infinity;
      for (const t of spec.xTicks || []) {
        const x = L.sx(t.v), w = ctx.measureText(t.label).width;
        if (x - w / 2 < lastRight + 4) continue; // skip colliding labels
        ctx.fillText(t.label, x, L.h - L.pad.b + 6);
        lastRight = x + w / 2;
      }
      if (spec.yLeftLabels) { // categorical y labels (heatmap rows)
        ctx.textAlign = "right"; ctx.textBaseline = "middle";
        for (const t of spec.yLeftLabels) ctx.fillText(t.label, L.pad.l - 6, L.sy(t.v));
      }
      ctx.fillStyle = cssVar("--text-3");
      if (spec.xTitle) { ctx.textAlign = "right"; ctx.textBaseline = "bottom"; ctx.fillText(spec.xTitle, L.w - L.pad.r, L.h - 1); }
      if (spec.yTitle) { ctx.textAlign = "left"; ctx.textBaseline = "top"; ctx.fillText(spec.yTitle, 2, 0); }
    }

    drawLegend(spec) {
      this.legendEl.innerHTML = (spec.legend || []).map((l) =>
        `<span class="lg"><i class="lg-${l.kind || "swatch"}" style="--c:${l.color}"></i>${l.label}</span>`).join("");
    }

    onMove(e) {
      if (!this.hits) return;
      const r = this.canvas.getBoundingClientRect();
      const mx = e.clientX - r.left, my = e.clientY - r.top;
      let best = null, bestD = Infinity;
      for (const h of this.hits) {
        let d;
        if (h.line) d = Math.abs(h.point[0] - mx);                                   // crosshair: nearest x
        else if (h.band) d = mx >= h.x0 - 2 && mx <= h.x1 + 2 ? Math.abs(my - (h.y0 + h.y1) / 2) / 1000 : Infinity; // whole column
        else d = mx >= h.x0 - 3 && mx <= h.x1 + 3 && my >= h.y0 - 3 && my <= h.y1 + 3 ? 0 : Infinity;
        if (d < bestD) { bestD = d; best = h; }
      }
      const changed = (best && best.item) !== (this.hover && this.hover.item);
      this.hover = best;
      if (best) showTip(best.item.tip, e.clientX, e.clientY); else hideTip();
      if (changed) this.render();
    }
  }

  function showTip(html, x, y) {
    if (!tooltip) { tooltip = document.createElement("div"); tooltip.className = "tooltip"; document.body.appendChild(tooltip); }
    tooltip.innerHTML = html;
    tooltip.style.display = "block";
    const tw = tooltip.offsetWidth, th = tooltip.offsetHeight;
    const left = x + 14 + tw > window.innerWidth - 8 ? x - tw - 14 : x + 14;
    tooltip.style.left = Math.max(8, left) + "px";
    tooltip.style.top = Math.max(8, Math.min(y - th / 2, window.innerHeight - th - 8)) + "px";
  }
  function hideTip() { if (tooltip) tooltip.style.display = "none"; }

  function niceTicks(min, max, count = 5, fmt = (v) => v.toLocaleString()) {
    const span = max - min || 1;
    const step0 = span / count, mag = Math.pow(10, Math.floor(Math.log10(step0)));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= count) || 10 * mag;
    const out = [];
    for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) out.push({ v: +v.toFixed(10), label: fmt(+v.toFixed(10)) });
    return out;
  }

  window.WGLCharts = {
    chart: (el, specFn) => new Chart(el, specFn),
    renderAll: () => charts.forEach((c) => c.render()),
    supported: () => initGL(),
    niceTicks, diverging, cssVar,
  };
})();
