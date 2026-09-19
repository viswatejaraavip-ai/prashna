/* Udhyath operator dashboard SPA (vanilla JS + Chart.js). Hash routes:
   #/overview #/cost #/traces #/trace/<id> #/users #/user/<uid> #/errors
   #/refunds #/support #/flags #/audit */
(function () {
  "use strict";

  const TOKEN_KEY = "udh_admin_token";
  const FIREBASE_VER = "10.12.2";
  const state = { token: null, charts: [], email: "" };
  const $ = (sel, root) => (root || document).querySelector(sel);

  // ---------- utils ----------
  function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  const rs = (u) => (u == null ? "–" : "₹" + (u / 100).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
  const rs0 = (u) => (u == null ? "–" : "₹" + Math.round(u / 100).toLocaleString("en-IN"));
  const num = (n) => (n == null ? "–" : Number(n).toLocaleString("en-IN"));
  const pct = (p) => (p == null ? "–" : p.toFixed(1) + "%");
  const ms = (m) => (m == null ? "–" : m >= 1000 ? (m / 1000).toFixed(1) + " s" : Math.round(m) + " ms");
  function when(iso) {
    if (!iso) return "–";
    const d = new Date(iso);
    return d.toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
  }
  const pill = (s) => `<span class="pill ${esc(s)}">${esc(String(s || "").replace("_", " "))}</span>`;
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  function toast(msg, isErr) {
    const t = document.createElement("div");
    t.className = "toast" + (isErr ? " err" : "");
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), isErr ? 6000 : 3000);
  }

  function confirmBox(title, html, okLabel, danger) {
    const dlg = $("#confirm");
    $("#confirm-title").textContent = title;
    $("#confirm-body").innerHTML = html;
    const ok = $("#confirm-ok");
    ok.textContent = okLabel || "Confirm";
    ok.className = danger ? "danger" : "";
    return new Promise((resolve) => {
      const done = (v) => { dlg.close(); ok.onclick = null; $("#confirm-cancel").onclick = null; resolve(v); };
      ok.onclick = () => done(true);
      $("#confirm-cancel").onclick = () => done(false);
      dlg.oncancel = () => done(false);
      dlg.showModal();
    });
  }

  // ---------- API ----------
  async function api(path, opts) {
    opts = opts || {};
    const headers = { "Content-Type": "application/json" };
    if (state.token) headers.Authorization = "Bearer " + state.token;
    const res = await fetch(path, { method: opts.method || "GET", headers,
      body: opts.body ? JSON.stringify(opts.body) : undefined });
    let data = null;
    try { data = await res.json(); } catch (e) { /* non-JSON */ }
    if (res.status === 401 || (res.status === 403 && path !== "/api/admin/login")) {
      signOut(res.status === 403 ? "This account is not an operator." : "Session expired, sign in again.");
      throw new Error("unauthorized");
    }
    if (!res.ok) {
      let d = data && data.detail;
      if (Array.isArray(d)) d = d.map((x) => x.msg).join("; ");
      if (d && typeof d === "object") d = d.detail || JSON.stringify(d);
      throw new Error(d || "HTTP " + res.status);
    }
    return data;
  }
  const qs = (o) => Object.entries(o).filter(([, v]) => v !== "" && v != null)
    .map(([k, v]) => encodeURIComponent(k) + "=" + encodeURIComponent(v)).join("&");

  // ---------- auth ----------
  function loadScript(src) {
    return new Promise((ok, fail) => {
      const s = document.createElement("script");
      s.src = src; s.onload = ok; s.onerror = () => fail(new Error("Failed to load " + src));
      document.head.appendChild(s);
    });
  }

  async function googleSignIn() {
    const err = $("#login-err");
    err.textContent = "";
    try {
      const cfg = (await api("/api/admin/config")).firebase;
      if (!cfg.apiKey) throw new Error("Firebase web config is not set on the server (FIREBASE_WEB_API_KEY).");
      if (!window.firebase) {
        await loadScript(`https://www.gstatic.com/firebasejs/${FIREBASE_VER}/firebase-app-compat.js`);
        await loadScript(`https://www.gstatic.com/firebasejs/${FIREBASE_VER}/firebase-auth-compat.js`);
      }
      if (!firebase.apps.length) firebase.initializeApp(cfg);
      const provider = new firebase.auth.GoogleAuthProvider();
      provider.setCustomParameters({ prompt: "select_account" });
      const cred = await firebase.auth().signInWithPopup(provider);
      const idToken = await cred.user.getIdToken();
      const r = await api("/api/admin/login", { method: "POST", body: { id_token: idToken } });
      const tok = r.token || r.access_token;
      if (!tok) throw new Error("Login response had no token");
      await useToken(tok);
    } catch (e) {
      if (e.message !== "unauthorized") err.textContent = e.message;
      else err.textContent = "This Google account is not an operator.";
    }
  }

  async function useToken(tok) {
    state.token = tok;
    try { sessionStorage.setItem(TOKEN_KEY, tok); } catch (e) { /* private mode */ }
    const me = await api("/api/admin/me");
    state.email = me.email;
    $("#who").textContent = me.email;
    $("#login").hidden = true;
    $("#shell").hidden = false;
    refreshBanner();
    route();
  }

  function signOut(msg) {
    state.token = null;
    try { sessionStorage.removeItem(TOKEN_KEY); } catch (e) { /* ignore */ }
    try { if (window.firebase && firebase.apps.length) firebase.auth().signOut(); } catch (e) { /* ignore */ }
    $("#shell").hidden = true;
    $("#login").hidden = false;
    $("#login-err").textContent = msg || "";
  }

  // ---------- banner ----------
  async function refreshBanner() {
    try {
      const d = await api("/api/admin/costwatch?hours=24&limit=1");
      renderBanner(d.level, d.avg_cost_units, d.answered, d.warn_units, d.ceiling_units);
    } catch (e) { /* banner is best-effort */ }
  }
  function renderBanner(level, avg, n, warn, ceiling) {
    const b = $("#banner");
    if (level === "breach" || level === "warning") {
      const icon = level === "breach" ? "⛔" : "⚠️";
      const label = level === "breach" ? "Cost ceiling breached" : "Cost warning";
      b.innerHTML = `<div class="banner ${level}" role="alert"><span class="icon" aria-hidden="true">${icon}</span>
        <span>${label}: rolling 24h average cost per query is <b>${rs(avg)}</b>
        over ${num(n)} queries (warning above ${rs(warn)}, ceiling ${rs(ceiling)}).
        <a href="#/cost">Open cost watch</a></span></div>`;
    } else b.innerHTML = "";
  }

  // ---------- charts ----------
  function destroyCharts() { state.charts.forEach((c) => c.destroy()); state.charts = []; }
  function chart(canvas, cfg) {
    if (!window.Chart) { canvas.parentElement.innerHTML = '<p class="muted small">Charts unavailable (Chart.js failed to load). See the table below.</p>'; return; }
    const text2 = css("--text-2"), grid = css("--grid");
    Chart.defaults.color = text2;
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    const own = cfg.options || {};
    cfg.options = Object.assign({ responsive: true, maintainAspectRatio: false, animation: false,
      interaction: { mode: "index", intersect: false } }, own);
    cfg.options.plugins = Object.assign({ legend: { position: "bottom", labels: { boxWidth: 12, usePointStyle: true } } }, own.plugins || {});
    const scales = cfg.options.scales || {};
    Object.values(scales).forEach((s) => {
      s.grid = Object.assign({ color: grid }, s.grid || {});
      s.border = { display: false };
    });
    state.charts.push(new Chart(canvas, cfg));
  }

  // ---------- pages ----------
  const pages = {};

  function kpi(label, value, sub, cls) {
    return `<div class="kpi ${cls || ""}"><div class="label">${esc(label)}</div>
      <div class="value">${value}</div><div class="sub">${sub || ""}</div></div>`;
  }
  const costCls = (u, warn, ceil) => (u == null ? "" : u > ceil ? "breach" : u > warn ? "warning" : "good");

  pages.overview = async function (el, args, query) {
    const days = Number(query.days || 30);
    const d = await api("/api/admin/overview?days=" + days);
    const T = d.totals, t = d.today.rollup, s = d.sample, td = d.today.traces;
    const ceil = d.ceiling_units, warn = d.warn_units;
    const stageTotal = Object.values(s.by_stage).reduce((a, b) => a + b, 0);
    const stageColors = { plan: "--s1", brief: "--s2", reason: "--s3", speech: "--s4", other: "--s5" };

    el.innerHTML = `
      <div class="toolbar"><h2 style="margin:0;flex:1">Overview</h2>
        <label>Period<select id="days">${[7, 14, 30, 60, 90].map((n) =>
          `<option value="${n}" ${n === days ? "selected" : ""}>Last ${n} days</option>`).join("")}</select></label></div>

      <div class="section"><h3>Today (IST)</h3><div class="kpis">
        ${kpi("Queries", num(t.queries), `${num(t.voice_queries)} voice`)}
        ${kpi("Revenue", rs0(t.revenue_units), `${num(t.reports)} reports`)}
        ${kpi("Provider cost", rs0(t.cost_units))}
        ${kpi("Gross margin", pct(t.margin_pct), "", t.margin_pct != null && t.margin_pct < 50 ? "warning" : "")}
        ${kpi("Avg cost / query", rs(td.avg_cost_units), `P95 ${rs(td.p95_cost_units)}`, costCls(td.avg_cost_units, warn, ceil))}
        ${kpi("Over ceiling", num(t.over_ceiling), td.over_ceiling_pct != null ? pct(td.over_ceiling_pct) + " of answered" : "", t.over_ceiling ? "breach" : "good")}
        ${kpi("Sign-ups", num(t.signups))}
        ${kpi("Top-ups", rs0(t.topups_units))}
      </div></div>

      <div class="section"><h3>Last ${days} days</h3><div class="kpis">
        ${kpi("Queries", num(T.queries), `${num(T.voice_queries)} voice · ${num(T.refusals)} refused`)}
        ${kpi("Revenue", rs0(T.revenue_units), `${num(T.reports)} reports sold`)}
        ${kpi("Provider cost", rs0(T.cost_units), `errors: ${num(T.errors)}`)}
        ${kpi("Gross margin", pct(T.margin_pct), `${rs0(T.revenue_units - T.cost_units)} gross profit`, T.margin_pct != null && T.margin_pct < 50 ? "warning" : "good")}
        ${kpi("Avg cost / query", rs(T.avg_cost_units), `target &lt; ${rs(ceil)}`, costCls(T.avg_cost_units, warn, ceil))}
        ${kpi("Over ceiling", num(T.over_ceiling), pct(T.over_ceiling_pct) + " of queries", T.over_ceiling ? "warning" : "good")}
        ${kpi("Sign-ups", num(T.signups))}
        ${kpi("Top-ups", rs0(T.topups_units))}
        ${kpi("Refunds", num(d.refunds.count), `${num(d.refunds.requested)} pending · ${rs0(d.refunds.approved_units)} refunded`, d.refunds.requested ? "warning" : "")}
      </div></div>

      <div class="section"><h3>Cost per answered query <span class="muted small">(sample: last ${s.window_days} days, ${num(s.answered)} queries${s.truncated ? ", truncated to newest " + num(s.size) + " traces" : ""})</span></h3>
      <div class="kpis">
        ${kpi("Average", rs(s.avg_cost_units), `vs ${rs(ceil)} ceiling`, costCls(s.avg_cost_units, warn, ceil))}
        ${kpi("P50", rs(s.p50_cost_units), "median", costCls(s.p50_cost_units, warn, ceil))}
        ${kpi("P95", rs(s.p95_cost_units), `max ${rs(s.max_cost_units)}`, costCls(s.p95_cost_units, warn, ceil))}
        ${kpi("Over ceiling", pct(s.over_ceiling_pct), `${num(s.over_ceiling)} queries`, s.over_ceiling ? "breach" : "good")}
        ${kpi("Latency P50 / P95", ms(s.p50_latency_ms), `P95 ${ms(s.p95_latency_ms)}`)}
        ${kpi("Free turns cost", rs(s.free_turn_cost_units), `${num(s.free_turns)} refused/clarify · ${num(s.errors)} errors (${rs(s.error_cost_units)})`)}
      </div></div>

      <div class="grid two section">
        <div class="card"><h3>Average cost per query by day</h3>
          <div class="chart-box"><canvas id="c-avg"></canvas></div>
          <p class="legend-note">Dashed red line: ${rs(ceil)} ceiling. Dotted: ${rs(warn)} warning.</p></div>
        <div class="card"><h3>Revenue and provider cost by day</h3>
          <div class="chart-box"><canvas id="c-rev"></canvas></div></div>
        <div class="card"><h3>Distribution of cost per query</h3>
          <div class="chart-box"><canvas id="c-hist"></canvas></div>
          <p class="legend-note">Bars at or above ${rs(ceil)} are over the ceiling.</p></div>
        <div class="card"><h3>Cost by stage <span class="muted small">(avg per answered query)</span></h3>
          ${Object.entries(s.by_stage).filter(([k, v]) => v || k !== "other").map(([k, v]) => {
            const per = s.answered ? v / s.answered : 0, share = stageTotal ? (v * 100 / stageTotal) : 0;
            return `<div class="bar-row"><span>${esc(k)}</span><div class="bar-track" title="${esc(k)}: ${rs(per)} per query, ${share.toFixed(1)}%">
              <div class="bar-fill" style="width:${share.toFixed(1)}%;background:var(${stageColors[k]})"></div></div>
              <span class="num">${rs(per)} <span class="muted small">${share.toFixed(0)}%</span></span></div>`;
          }).join("")}
          <h3 style="margin-top:16px">By model</h3>
          <table><thead><tr><th>Model</th><th class="num">Calls</th><th class="num">Tokens in / out</th><th class="num">Cost</th><th class="num">Per call</th></tr></thead><tbody>
          ${Object.entries(s.by_model).sort((a, b) => b[1].cost_units - a[1].cost_units).map(([m, r]) => `<tr>
            <td class="mono">${esc(m)}</td><td class="num">${num(r.calls)}</td>
            <td class="num">${num(r.in_tok)} / ${num(r.out_tok)}</td><td class="num">${rs0(r.cost_units)}</td>
            <td class="num">${rs(r.calls ? r.cost_units / r.calls : null)}</td></tr>`).join("") || '<tr><td colspan="5" class="muted">No data</td></tr>'}
          </tbody></table></div>
      </div>

      <div class="grid two section">
        <div class="card"><h3>By language</h3>${splitTable(s.by_lang, ceil, { hi: "Hindi", te: "Telugu", ta: "Tamil", kn: "Kannada", ml: "Malayalam" }, T.by_lang)}</div>
        <div class="card"><h3>Text vs voice</h3>${splitTable(s.by_mode, ceil, { text: "Text", voice: "Voice" })}
          <h3 style="margin-top:16px">Reports and other AI work</h3>
          <table><thead><tr><th>Kind</th><th class="num">Count</th><th class="num">Cost</th><th class="num">Avg</th></tr></thead><tbody>
          ${Object.entries(s.by_kind).map(([k, r]) => `<tr><td>${esc(k.replace("_", " "))}</td><td class="num">${num(r.count)}</td>
            <td class="num">${rs0(r.cost_units)}</td><td class="num">${rs(r.count ? r.cost_units / r.count : null)}</td></tr>`).join("") || '<tr><td colspan="4" class="muted">None in sample</td></tr>'}
          </tbody></table>
          <p class="muted small">Reports sold in period: ${num(T.reports)} (from rollups). Chapter costs are from the trace sample.</p></div>
      </div>

      <details class="card"><summary>Daily table</summary><div class="table-wrap"><table>
        <thead><tr><th>Day</th><th class="num">Queries</th><th class="num">Voice</th><th class="num">Revenue</th><th class="num">Cost</th>
        <th class="num">Margin</th><th class="num">Avg/query</th><th class="num">Over ceiling</th><th class="num">Errors</th>
        <th class="num">Sign-ups</th><th class="num">Top-ups</th><th class="num">Reports</th></tr></thead><tbody>
        ${d.series.slice().reverse().map((r) => `<tr><td>${esc(r.day)}</td><td class="num">${num(r.queries)}</td><td class="num">${num(r.voice_queries)}</td>
          <td class="num">${rs0(r.revenue_units)}</td><td class="num">${rs0(r.cost_units)}</td><td class="num">${pct(r.margin_pct)}</td>
          <td class="num ${r.avg_cost_units > ceil ? "over" : ""}">${rs(r.avg_cost_units)}</td><td class="num">${num(r.over_ceiling)}</td>
          <td class="num">${num(r.errors)}</td><td class="num">${num(r.signups)}</td><td class="num">${rs0(r.topups_units)}</td><td class="num">${num(r.reports)}</td></tr>`).join("")}
      </tbody></table></div></details>`;

    $("#days").onchange = (e) => { location.hash = "#/overview?days=" + e.target.value; };
    renderBanner(d.watch.level, d.watch.avg_cost_units, d.watch.answered, warn, ceil);

    const labels = d.series.map((r) => r.day.slice(5));
    const flat = (v) => labels.map(() => v / 100);
    chart($("#c-avg"), { type: "line", data: { labels, datasets: [
      { label: "Avg cost / query (₹)", data: d.series.map((r) => r.avg_cost_units == null ? null : r.avg_cost_units / 100),
        borderColor: css("--s1"), backgroundColor: css("--s1"), borderWidth: 2, pointRadius: 3, spanGaps: true },
      { label: "Ceiling", data: flat(ceil), borderColor: css("--ceiling"), borderDash: [6, 4], borderWidth: 1.5, pointRadius: 0 },
      { label: "Warning", data: flat(warn), borderColor: css("--warn"), borderDash: [2, 3], borderWidth: 1.5, pointRadius: 0 },
    ] }, options: { scales: { x: { grid: { display: false } }, y: { beginAtZero: true, suggestedMax: ceil / 100 * 1.2, ticks: { callback: (v) => "₹" + v } } },
      plugins: { tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${c.parsed.y == null ? "–" : "₹" + c.parsed.y.toFixed(2)}` } } } } });

    chart($("#c-rev"), { type: "bar", data: { labels, datasets: [
      { label: "Revenue", data: d.series.map((r) => r.revenue_units / 100), backgroundColor: css("--s1"), borderRadius: 4, borderSkipped: "start" },
      { label: "Provider cost", data: d.series.map((r) => r.cost_units / 100), backgroundColor: css("--s2"), borderRadius: 4, borderSkipped: "start" },
    ] }, options: { datasets: { bar: { categoryPercentage: 0.7, barPercentage: 0.9 } },
      scales: { x: { grid: { display: false } }, y: { beginAtZero: true, ticks: { callback: (v) => "₹" + v.toLocaleString("en-IN") } } },
      plugins: { tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ₹${c.parsed.y.toLocaleString("en-IN")}` } } } } });

    const H = s.cost_histogram;
    chart($("#c-hist"), { type: "bar", data: {
      labels: H.map((b) => b.to == null ? "≥₹" + (b.from / 100) : "₹" + (b.from / 100) + "–" + (b.to / 100)),
      datasets: [{ label: "Queries", data: H.map((b) => b.count), borderRadius: 4, borderSkipped: "start",
        backgroundColor: H.map((b) => b.from >= ceil ? css("--bad") : css("--s1")) }] },
      options: { plugins: { legend: { display: false } }, scales: { x: { grid: { display: false } }, y: { beginAtZero: true, ticks: { precision: 0 } } } } });
  };

  function splitTable(obj, ceil, names, rollupCounts) {
    const rows = Object.entries(obj).sort((a, b) => b[1].queries - a[1].queries);
    return `<table><thead><tr><th></th>${rollupCounts ? '<th class="num">Queries (period)</th>' : ""}
      <th class="num">Sample</th><th class="num">Avg cost</th><th class="num">Margin</th><th class="num">Over ceiling</th></tr></thead><tbody>
      ${rows.map(([k, r]) => `<tr><td>${esc(names[k] || k)}</td>${rollupCounts ? `<td class="num">${num(rollupCounts[k] || 0)}</td>` : ""}
        <td class="num">${num(r.queries)}</td><td class="num ${r.avg_cost_units > ceil ? "over" : ""}">${rs(r.avg_cost_units)}</td>
        <td class="num">${pct(r.margin_pct)}</td><td class="num">${num(r.over_ceiling)}</td></tr>`).join("")}</tbody></table>`;
  }

  function traceTable(rows, ceil, opts) {
    opts = opts || {};
    if (!rows.length) return '<p class="muted">No traces.</p>';
    return `<div class="table-wrap"><table><thead><tr><th>When (IST)</th><th>Status</th><th>Kind</th><th>Lang</th><th>Mode</th>
      <th>User</th><th class="num">Cost</th><th class="num">Charged</th><th class="num">Latency</th><th>Error</th></tr></thead><tbody>
      ${rows.map((t) => `<tr class="click" data-href="#/trace/${encodeURIComponent(t.id)}">
        <td>${when(t.created_at)}</td><td>${pill(t.status)}</td><td>${esc(t.kind || "query")}</td><td>${esc(t.lang)}</td><td>${esc(t.mode)}</td>
        <td class="mono"><a href="#/user/${encodeURIComponent(t.uid || "")}" onclick="event.stopPropagation()">${esc((t.uid || "").slice(0, 14))}</a></td>
        <td class="num ${ceil && t.cost_units > ceil ? "over" : ""}">${rs(t.cost_units)}</td><td class="num">${rs(t.charged_units)}</td>
        <td class="num">${ms(t.latency_ms)}</td><td class="err-text small">${esc((t.error || "").slice(0, 80))}</td></tr>`).join("")}
      </tbody></table></div>`;
  }
  function wireRows(el) {
    el.querySelectorAll("tr.click").forEach((tr) => { tr.onclick = () => { location.hash = tr.dataset.href; }; });
  }

  pages.cost = async function (el, args, query) {
    const hours = Number(query.hours || 24);
    const d = await api("/api/admin/costwatch?" + qs({ hours, limit: 50 }));
    renderBanner(d.level, d.avg_cost_units, d.answered, d.warn_units, d.ceiling_units);
    el.innerHTML = `<div class="toolbar"><h2 style="margin:0;flex:1">Cost watch</h2>
      <label>Window<select id="hours">${[1, 6, 24, 72, 168].map((h) => `<option value="${h}" ${h === hours ? "selected" : ""}>Last ${h < 48 ? h + "h" : h / 24 + " days"}</option>`).join("")}</select></label></div>
      <div class="kpis section">
        ${kpi("Avg cost / query", rs(d.avg_cost_units), `${num(d.answered)} answered`, costCls(d.avg_cost_units, d.warn_units, d.ceiling_units))}
        ${kpi("P95 cost", rs(d.p95_cost_units), "", costCls(d.p95_cost_units, d.warn_units, d.ceiling_units))}
        ${kpi("Status", `${d.level === "ok" ? "✓" : d.level === "warning" ? "⚠" : "⛔"} ${esc(d.level)}`, `warning &gt; ${rs(d.warn_units)} · breach &gt; ${rs(d.ceiling_units)}`, d.level === "ok" ? "good" : d.level)}
        ${kpi("Over ceiling", num(d.over_ceiling.length), "in window + recent flagged")}
      </div>
      <div class="card"><h3>Most expensive queries</h3>${traceTable(d.most_expensive, d.ceiling_units)}</div>
      <div class="card"><h3>Over-ceiling queries</h3>${traceTable(d.over_ceiling, d.ceiling_units)}</div>`;
    $("#hours").onchange = (e) => { location.hash = "#/cost?hours=" + e.target.value; };
    wireRows(el);
  };

  pages.traces = async function (el, args, query) {
    const f = { status: query.status || "", uid: query.uid || "", lang: query.lang || "", mode: query.mode || "",
      kind: query.kind || "", min_rs: query.min_rs || "", date: query.date || "" };
    const sel = (name, opts) => `<select name="${name}"><option value="">any</option>${opts.map((o) =>
      `<option ${f[name] === o ? "selected" : ""}>${o}</option>`).join("")}</select>`;
    el.innerHTML = `<h2>Trace explorer</h2>
      <form class="toolbar card" id="tf">
        <label>Status${sel("status", ["ok", "over_ceiling", "error", "refused", "clarify"])}</label>
        <label>Kind${sel("kind", ["query", "report_chapter", "daily", "teaser"])}</label>
        <label>Language${sel("lang", ["te", "hi", "ta", "kn", "ml"])}</label>
        <label>Mode${sel("mode", ["text", "voice"])}</label>
        <label>User id<input name="uid" value="${esc(f.uid)}" class="mono" size="16"></label>
        <label>Min cost (₹)<input name="min_rs" type="number" step="0.5" min="0" value="${esc(f.min_rs)}" style="width:90px"></label>
        <label>Day (IST)<input name="date" type="date" value="${esc(f.date)}"></label>
        <button>Search</button>
      </form>
      <div class="card" id="tres"><div class="spinner">Loading…</div></div>`;
    $("#tf").onsubmit = (e) => {
      e.preventDefault();
      const fd = Object.fromEntries(new FormData(e.target).entries());
      location.hash = "#/traces?" + qs(fd);
    };
    const params = { status: f.status, uid: f.uid, lang: f.lang, mode: f.mode, kind: f.kind, date: f.date,
      min_cost: f.min_rs ? Math.round(Number(f.min_rs) * 100) : "", limit: 50 };
    let all = [];
    const box = $("#tres");
    async function load(before) {
      const d = await api("/api/admin/traces?" + qs(Object.assign({}, params, { before })));
      all = all.concat(d.traces);
      box.innerHTML = `<p class="muted small">${num(all.length)} traces shown (scanned ${num(d.scanned)} in the last page).</p>
        ${traceTable(all, 500)}${d.next_before ? '<p><button class="secondary" id="more">Load older</button></p>' : ""}`;
      wireRows(box);
      if (d.next_before) $("#more").onclick = () => load(d.next_before);
    }
    await load("");
  };

  pages.trace = async function (el, args) {
    const d = await api("/api/admin/traces/" + encodeURIComponent(args[0]));
    const t = d.trace, ceil = d.ceiling_units;
    const plan = (t.stages || []).find((s) => s.name === "plan");
    const tools = (t.stages || []).find((s) => s.name === "tools");
    const toolErrors = (tools && tools.detail && tools.detail.errors) || [];
    el.innerHTML = `<p><a href="javascript:history.back()">← Back</a></p>
      <h2>Trace <span class="mono">${esc(t.trace_id || t.id)}</span> ${pill(t.status)} ${d.over_ceiling ? pill("over_ceiling") : ""}</h2>
      <div class="kpis section">
        ${kpi("Provider cost", rs(t.cost_units), `ceiling ${rs(ceil)}`, d.over_ceiling ? "breach" : "good")}
        ${kpi("Charged", rs(t.charged_units))}
        ${kpi("Latency", ms(t.latency_ms))}
        ${kpi("Language / mode", esc((t.lang || "–") + " · " + (t.mode || "–")), esc(t.kind || "query"))}
      </div>
      ${t.error ? `<div class="banner breach"><span class="icon">⛔</span><span class="mono">${esc(t.error)}</span></div>` : ""}
      <div class="grid two section">
        <div class="card"><h3>Context</h3><dl class="kv">
          <dt>When</dt><dd>${when(t.created_at)} <span class="muted small">${esc(t.created_at)}</span></dd>
          <dt>User</dt><dd>${t.uid ? `<a href="#/user/${encodeURIComponent(t.uid)}" class="mono">${esc(t.uid)}</a>` : "–"}
            ${d.user ? `<span class="muted">${esc(d.user.name || "")} ${esc(d.user.phone || d.user.email || "")} · balance ${rs(d.user.balance_units)}</span>` : ""}</dd>
          <dt>Session</dt><dd class="mono">${esc(t.session_id || "–")}</dd>
          <dt>Question length</dt><dd>${num(t.question_chars)} chars</dd>
          <dt>Intent</dt><dd>${esc(plan && plan.detail ? plan.detail.intent : "–")}</dd>
          <dt>Tools planned</dt><dd>${esc(plan && plan.detail && plan.detail.tools ? plan.detail.tools.join(", ") : "–")}</dd>
          <dt>Tool errors</dt><dd>${toolErrors.length ? toolErrors.map((e) => `<div class="err-text">${esc(e)}</div>`).join("") : "none"}</dd>
        </dl></div>
        <div class="card"><h3>Conversation</h3>
          ${d.question ? `<div class="bubble user">${esc(d.question.text)}<div class="meta">user · ${when(d.question.created_at)}</div></div>` : '<p class="muted">Question text not found in session messages.</p>'}
          ${d.answer ? `<div class="bubble assistant">${esc(d.answer.text)}<div class="meta">answer · charged ${rs(d.answer.charged_units)} · ${when(d.answer.created_at)}</div></div>` : '<p class="muted">No answer message.</p>'}
        </div>
      </div>
      <div class="card"><h3>Stages</h3><div class="table-wrap"><table><thead><tr><th>Stage</th><th>Model</th>
        <th class="num">In tok</th><th class="num">Cache read</th><th class="num">Out tok</th><th class="num">Units</th>
        <th class="num">Cost</th><th class="num">Share</th><th class="num">Latency</th><th>Detail</th></tr></thead><tbody>
        ${(t.stages || []).map((s) => `<tr><td><b>${esc(s.name)}</b></td><td class="mono">${esc(s.model || "–")}</td>
          <td class="num">${num(s.in_tok)}</td><td class="num">${num(s.cache_read_tok)}</td><td class="num">${num(s.out_tok)}</td>
          <td class="num">${num(s.units)}</td><td class="num">${rs(s.cost_units)}</td>
          <td class="num">${t.cost_units && s.cost_units ? (s.cost_units * 100 / t.cost_units).toFixed(0) + "%" : "–"}</td>
          <td class="num">${ms(s.latency_ms)}</td><td>${s.detail ? `<pre>${esc(JSON.stringify(s.detail, null, 1))}</pre>` : ""}</td></tr>`).join("")}
      </tbody></table></div></div>
      <details class="card"><summary>Raw trace JSON</summary><pre>${esc(JSON.stringify(t, null, 2))}</pre></details>`;
  };

  pages.users = async function (el, args, query) {
    const q = query.q || "";
    el.innerHTML = `<h2>User lookup</h2>
      <form class="toolbar card" id="uf"><label style="flex:1">Phone, email or uid
        <input name="q" value="${esc(q)}" placeholder="+91 98… / name@example.com / uid" autofocus></label><button>Find</button></form>
      <div id="ures"></div>`;
    $("#uf").onsubmit = (e) => { e.preventDefault(); location.hash = "#/users?" + qs({ q: e.target.q.value.trim() }); };
    if (q.length < 2) return;
    const d = await api("/api/admin/users?" + qs({ q }));
    if (d.users.length === 1) { location.replace("#/user/" + encodeURIComponent(d.users[0].id)); return; }
    $("#ures").innerHTML = `<div class="card">${d.users.length ? `<table><thead><tr><th>uid</th><th>Name</th><th>Phone</th><th>Email</th><th>Lang</th><th class="num">Balance</th><th>Joined</th></tr></thead><tbody>
      ${d.users.map((u) => `<tr class="click" data-href="#/user/${encodeURIComponent(u.id)}"><td class="mono">${esc(u.id)}</td><td>${esc(u.name)}</td>
        <td>${esc(u.phone)}</td><td>${esc(u.email)}</td><td>${esc(u.lang)}</td><td class="num">${rs(u.balance_units)}</td><td>${when(u.created_at)}</td></tr>`).join("")}
      </tbody></table>` : '<p class="muted">No matching user.</p>'}</div>`;
    wireRows(el);
  };

  pages.user = async function (el, args) {
    const uid = args[0];
    const d = await api("/api/admin/users/" + encodeURIComponent(uid));
    const u = d.user;
    const simpleTable = (rows, cols, empty) => rows.length ? `<div class="table-wrap"><table><thead><tr>${cols.map((c) =>
      `<th class="${c[2] || ""}">${c[0]}</th>`).join("")}</tr></thead><tbody>${rows.map((r) => `<tr>${cols.map((c) =>
      `<td class="${c[2] || ""}">${c[1](r)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>` : `<p class="muted">${empty}</p>`;
    el.innerHTML = `<p><a href="#/users">← User lookup</a></p>
      <h2>${esc(u.name || "(no name)")} <span class="mono muted small">${esc(u.id)}</span> ${u.deleted_at ? pill("deleted") : ""}</h2>
      <div class="grid two section">
        <div class="card"><h3>Account</h3><dl class="kv">
          <dt>Phone</dt><dd>${esc(u.phone || "–")}</dd><dt>Email</dt><dd>${esc(u.email || "–")}</dd>
          <dt>Language</dt><dd>${esc(u.lang)}</dd><dt>Role / plan</dt><dd>${esc(u.role)} · ${esc(u.plan)} ${u.plan_expires_at ? "until " + when(u.plan_expires_at) : ""}</dd>
          <dt>Joined</dt><dd>${when(u.created_at)}</dd><dt>Trial claimed</dt><dd>${u.trial_claimed ? "yes" : "no"}</dd>
          <dt>Disclaimer</dt><dd>${u.disclaimer_accepted_at ? when(u.disclaimer_accepted_at) : "not accepted"}</dd>
          <dt>Devices</dt><dd class="mono small">${d.devices.device_hashes.map(esc).join("<br>") || "–"}</dd>
          <dt>Push tokens</dt><dd>${num(d.devices.fcm_tokens)}</dd>
          <dt>Profiles</dt><dd>${d.profiles.map((p) => esc(p.name + " (" + p.relation + ")")).join(", ") || "–"}</dd>
        </dl></div>
        <div class="card"><h3>Wallet</h3>
          <div class="kpis">${kpi("Balance", rs(u.balance_units))}</div>
          <form id="adj" class="toolbar" style="margin-top:12px">
            <label>Adjust by (₹, negative to debit)<input name="rs" type="number" step="0.01" required style="width:140px"></label>
            <label style="flex:1">Reason<input name="reason" required minlength="3" placeholder="e.g. goodwill for failed answer"></label>
            <button>Adjust</button></form>
          <p class="muted small">Goes through the wallet ledger (type "adjust") and is audited.</p>
        </div>
      </div>
      <div class="card"><h3>Ledger</h3>${simpleTable(d.ledger, [["When", (r) => when(r.created_at)], ["Type", (r) => esc(r.type)],
        ["Delta", (r) => `<span class="${r.delta_units < 0 ? "err-text" : ""}">${rs(r.delta_units)}</span>`, "num"], ["Balance after", (r) => rs(r.balance_after), "num"],
        ["Ref", (r) => `<span class="mono small">${esc(r.ref)}</span>`]], "No ledger entries.")}</div>
      <div class="card"><h3>Sessions</h3>${simpleTable(d.sessions, [["Started", (r) => when(r.created_at)], ["Mode", (r) => esc(r.mode)],
        ["Lang", (r) => esc(r.lang)], ["Queries", (r) => num(r.query_count), "num"],
        ["", (r) => `<button class="secondary small" data-sid="${esc(r.id)}">Messages</button>`]], "No sessions.")}
        <div id="msgs"></div></div>
      <div class="card"><h3>Recent traces</h3>${traceTable(d.traces, 500)}</div>
      <div class="grid two">
        <div class="card"><h3>Refunds</h3>${simpleTable(d.refunds, [["When", (r) => when(r.created_at)], ["Status", (r) => pill(r.status)],
          ["Amount", (r) => rs(r.amount_units), "num"], ["Reason", (r) => esc(r.reason)]], "No refunds.")}</div>
        <div class="card"><h3>Support tickets</h3>${simpleTable(d.tickets, [["When", (r) => when(r.created_at)], ["Status", (r) => pill(r.status)],
          ["Category", (r) => esc(r.category)], ["Message", (r) => esc(r.message)]], "No tickets.")}</div>
      </div>
      <div class="card"><h3>Payments</h3>${simpleTable(d.payments, [["When", (r) => when(r.created_at)], ["Provider", (r) => esc(r.provider)],
        ["Amount", (r) => rs(r.amount_units), "num"], ["Status", (r) => pill(r.status)], ["Id", (r) => `<span class="mono small">${esc(r.id)}</span>`]], "No payments.")}</div>`;
    wireRows(el);
    el.querySelectorAll("button[data-sid]").forEach((b) => {
      b.onclick = async () => {
        const m = await api("/api/admin/sessions/" + encodeURIComponent(b.dataset.sid) + "/messages");
        $("#msgs").innerHTML = `<h3 style="margin-top:14px">Session <span class="mono small">${esc(b.dataset.sid)}</span></h3>` +
          (m.messages.map((x) => `<div class="bubble ${x.role === "user" ? "user" : "assistant"}">${esc(x.text)}
            <div class="meta">${esc(x.role)} · ${when(x.created_at)}${x.charged_units ? " · charged " + rs(x.charged_units) : ""}
            ${x.trace_id ? ` · <a href="#/trace/${encodeURIComponent(x.trace_id)}">trace</a>` : ""}</div></div>`).join("") || '<p class="muted">No messages.</p>');
      };
    });
    $("#adj").onsubmit = async (e) => {
      e.preventDefault();
      const units = Math.round(Number(e.target.rs.value) * 100), reason = e.target.reason.value.trim();
      if (!units) return toast("Enter a non-zero amount", true);
      const ok = await confirmBox("Adjust wallet", `<p>${units > 0 ? "Credit" : "Debit"} <b>${rs(Math.abs(units))}</b> ${units > 0 ? "to" : "from"}
        <b>${esc(u.name || u.id)}</b>. Balance ${rs(u.balance_units)} → <b>${rs(u.balance_units + units)}</b>.</p><p class="muted">Reason: ${esc(reason)}</p>`,
        units > 0 ? "Credit" : "Debit", units < 0);
      if (!ok) return;
      try {
        const r = await api(`/api/admin/users/${encodeURIComponent(uid)}/adjust`, { method: "POST", body: { delta_units: units, reason } });
        toast("New balance " + rs(r.balance_units));
        route();
      } catch (err) { toast(err.message, true); }
    };
  };

  pages.errors = async function (el) {
    const d = await api("/api/admin/errors?limit=100");
    el.innerHTML = `<h2>Errors</h2>
      <div class="card"><h3>Failed AI queries <span class="muted small">(traces with status=error)</span></h3>${traceTable(d.traces, 500)}</div>
      <div class="card"><h3>Server errors <span class="muted small">(app_errors, unhandled 5xx)</span></h3>
      ${d.app_errors.length ? `<div class="table-wrap"><table><thead><tr><th>When</th><th>Path</th><th>Type</th><th>Message</th><th>User</th><th></th></tr></thead><tbody>
      ${d.app_errors.map((e, i) => `<tr><td>${when(e.created_at)}</td><td class="mono">${esc(e.method || "")} ${esc(e.path)}</td>
        <td class="err-text">${esc(e.error_type)}</td><td>${esc(e.message)}</td>
        <td class="mono">${e.uid ? `<a href="#/user/${encodeURIComponent(e.uid)}">${esc(e.uid)}</a>` : "–"}</td>
        <td><details><summary>traceback</summary><pre>${esc(e.traceback)}</pre></details></td></tr>`).join("")}</tbody></table></div>` : '<p class="muted">No server errors recorded.</p>'}</div>`;
    wireRows(el);
  };

  pages.refunds = async function (el, args, query) {
    const status = query.status || "requested";
    const d = await api("/api/admin/refunds?" + qs({ status }));
    el.innerHTML = `<div class="toolbar"><h2 style="margin:0;flex:1">Refunds</h2>
      <label>Status<select id="rs">${["requested", "approved", "rejected", "all"].map((s) => `<option ${s === status ? "selected" : ""}>${s}</option>`).join("")}</select></label></div>
      <div class="card">${d.refunds.length ? `<div class="table-wrap"><table><thead><tr><th>Requested</th><th>User</th><th>Ref</th><th class="num">Amount</th>
        <th>Reason</th><th>Status</th><th>Decision</th></tr></thead><tbody>
        ${d.refunds.map((r) => `<tr><td>${when(r.created_at)}</td>
          <td class="mono"><a href="#/user/${encodeURIComponent(r.uid)}">${esc(r.uid)}</a></td>
          <td class="mono small">${r.ref ? `<a href="#/trace/${encodeURIComponent(r.ref)}">${esc(r.ref)}</a>` : "–"}</td>
          <td class="num">${rs(r.amount_units)}</td><td>${esc(r.reason)}</td><td>${pill(r.status)}</td>
          <td>${r.status === "requested" ? `<div class="row-actions"><button class="ok" data-id="${esc(r.id)}" data-d="approve" data-amt="${r.amount_units || 0}">Approve</button>
            <button class="danger" data-id="${esc(r.id)}" data-d="reject">Reject</button></div>`
            : `<span class="small muted">${esc(r.decided_by || "")} ${r.decided_at ? when(r.decided_at) : ""}</span>`}</td></tr>`).join("")}
        </tbody></table></div>` : '<p class="muted">Nothing here.</p>'}</div>`;
    $("#rs").onchange = (e) => { location.hash = "#/refunds?status=" + e.target.value; };
    el.querySelectorAll("button[data-id]").forEach((b) => {
      b.onclick = async () => {
        const approve = b.dataset.d === "approve", amt = Number(b.dataset.amt);
        const ok = await confirmBox(approve ? "Approve refund" : "Reject refund",
          `${approve ? `<p>Credit <b>${rs(amt)}</b> back to the user's wallet.</p>
            <label class="small muted">Amount (₹, optional partial)<input id="ramt" type="number" step="0.01" value="${amt / 100}"></label>` : ""}
           <label class="small muted" style="display:block;margin-top:8px">Note<textarea id="rnote"></textarea></label>`,
          approve ? "Approve" : "Reject", !approve);
        if (!ok) return;
        const body = { decision: b.dataset.d, note: $("#rnote").value };
        if (approve && $("#ramt").value) body.amount_units = Math.round(Number($("#ramt").value) * 100);
        try { await api("/api/admin/refunds/" + encodeURIComponent(b.dataset.id), { method: "POST", body }); toast("Refund " + (approve ? "approved" : "rejected")); route(); }
        catch (err) { toast(err.message, true); }
      };
    });
  };

  pages.support = async function (el, args, query) {
    const status = query.status || "open";
    const d = await api("/api/admin/support?" + qs({ status }));
    el.innerHTML = `<div class="toolbar"><h2 style="margin:0;flex:1">Support inbox</h2>
      <label>Status<select id="ss">${["open", "resolved", "all"].map((s) => `<option ${s === status ? "selected" : ""}>${s}</option>`).join("")}</select></label></div>
      <div class="card">${d.tickets.map((t) => `<div class="ticket">
        <div>${pill(t.status)} <b>${esc(t.category)}</b> · <a class="mono" href="#/user/${encodeURIComponent(t.uid)}">${esc(t.uid)}</a>
          <span class="muted small">${when(t.created_at)}</span></div>
        <div class="bubble user">${esc(t.message)}</div>
        ${(t.replies || []).map((r) => `<div class="bubble assistant">${esc(r.message || r.text)}<div class="meta">${esc(r.admin || r.from || "")} · ${when(r.created_at)}</div></div>`).join("")}
        <form data-id="${esc(t.id)}"><textarea name="message" placeholder="Reply to the user…" required></textarea>
          <div class="row-actions" style="margin-top:6px"><label class="small"><input type="checkbox" name="resolve" ${t.status === "open" ? "checked" : ""}> Mark resolved</label>
          <span style="flex:1"></span><button>Send reply</button></div></form></div>`).join("") || '<p class="muted">Inbox zero.</p>'}</div>`;
    $("#ss").onchange = (e) => { location.hash = "#/support?status=" + e.target.value; };
    el.querySelectorAll("form[data-id]").forEach((f) => {
      f.onsubmit = async (e) => {
        e.preventDefault();
        try {
          await api(`/api/admin/support/${encodeURIComponent(f.dataset.id)}/reply`, { method: "POST",
            body: { message: f.message.value.trim(), resolve: f.resolve.checked } });
          toast("Reply sent"); route();
        } catch (err) { toast(err.message, true); }
      };
    });
  };

  const FLAG_META = {
    opus_enabled: ["Claude Opus reasoning", "Kill switch for the Opus stage. Off = queries cannot be answered by Opus.", "bool"],
    voice_cloud_enabled: ["Cloud speech (STT/TTS)", "Off = only on-device speech; saves Google Speech cost.", "bool"],
    query_price_units: ["Query price", "What the user pays per answered query.", "rs"],
    cost_ceiling_units: ["Cost ceiling per query", "Max provider cost per query, enforced before calling Opus. Must be below the price.", "rs"],
    maintenance_message: ["Maintenance message", "When set, the app shows this and blocks paid queries. Leave empty for normal operation.", "text"],
  };

  pages.flags = async function (el) {
    const d = await api("/api/admin/flags");
    const f = d.flags;
    el.innerHTML = `<h2>Kill switches &amp; pricing</h2>
      <form class="card" id="ff">
        ${Object.entries(FLAG_META).map(([k, [label, desc, type]]) => `<div class="flag-row">
          <div><b>${label}</b><div class="desc">${desc}</div><div class="mono small muted">${k}</div></div>
          <div>${type === "bool" ? `<label><input type="checkbox" name="${k}" ${f[k] ? "checked" : ""}> enabled</label>`
            : type === "rs" ? `<label>₹ <input type="number" name="${k}" step="0.01" min="0" value="${(f[k] / 100).toFixed(2)}" style="width:120px"></label> <span class="muted small">(${num(f[k])} paise)</span>`
            : `<textarea name="${k}" maxlength="500">${esc(f[k])}</textarea>`}</div></div>`).join("")}
        <p class="row-actions" style="justify-content:flex-end;margin-top:14px"><button>Review changes</button></p>
        <p class="muted small">Every instance caches flags for up to ${d.cache_seconds}s, so changes take up to a minute to reach all servers.</p>
      </form>`;
    $("#ff").onsubmit = async (e) => {
      e.preventDefault();
      const form = e.target, changed = {};
      Object.entries(FLAG_META).forEach(([k, [, , type]]) => {
        let v = type === "bool" ? form[k].checked : type === "rs" ? Math.round(Number(form[k].value) * 100) : form[k].value.trim();
        if (v !== f[k]) changed[k] = v;
      });
      if (!Object.keys(changed).length) return toast("No changes");
      const fmt = (k, v) => FLAG_META[k][2] === "rs" ? rs(v) : FLAG_META[k][2] === "bool" ? (v ? "on" : "OFF") : `"${esc(v)}"`;
      const risky = changed.opus_enabled === false || (changed.maintenance_message || "") !== "" || "query_price_units" in changed;
      const ok = await confirmBox("Apply flag changes", `<table><thead><tr><th>Flag</th><th>Now</th><th>New</th></tr></thead><tbody>
        ${Object.entries(changed).map(([k, v]) => `<tr><td>${FLAG_META[k][0]}</td><td>${fmt(k, f[k])}</td><td><b>${fmt(k, v)}</b></td></tr>`).join("")}</tbody></table>
        ${risky ? '<p class="err-text small">This affects every user immediately.</p>' : ""}`, "Apply", risky);
      if (!ok) return;
      try { await api("/api/admin/flags", { method: "PUT", body: changed }); toast("Flags updated"); route(); }
      catch (err) { toast(err.message, true); }
    };
  };

  pages.audit = async function (el) {
    const d = await api("/api/admin/audit?limit=200");
    const short = (o) => o == null ? "–" : esc(JSON.stringify(o)).slice(0, 300);
    el.innerHTML = `<h2>Audit log</h2><div class="card">${d.audit.length ? `<div class="table-wrap"><table><thead><tr><th>When</th><th>Admin</th>
      <th>Action</th><th>Target</th><th>Before</th><th>After</th><th>Reason</th></tr></thead><tbody>
      ${d.audit.map((a) => `<tr><td>${when(a.created_at)}</td><td>${esc(a.admin)}</td><td><b>${esc(a.action)}</b></td>
        <td class="mono small">${esc(a.target)}</td><td class="mono small">${short(a.before)}</td><td class="mono small">${short(a.after)}</td>
        <td>${esc(a.reason)}</td></tr>`).join("")}</tbody></table></div>` : '<p class="muted">No admin actions yet.</p>'}</div>`;
  };

  // ---------- router ----------
  // Each navigation renders into a fresh container; a slow page that finishes
  // after the user moved on writes into a detached node and is discarded.
  async function route() {
    if (!state.token) return;
    const raw = location.hash.replace(/^#\/?/, "") || "overview";
    const [path, search] = raw.split("?");
    const parts = path.split("/").map(decodeURIComponent);
    const name = pages[parts[0]] ? parts[0] : "overview";
    const query = Object.fromEntries(new URLSearchParams(search || ""));
    const tab = { trace: "traces", user: "users" }[name] || name;
    document.querySelectorAll("#tabs a").forEach((a) => a.classList.toggle("active", a.dataset.page === tab));
    destroyCharts();
    const el = document.createElement("div");
    el.innerHTML = '<div class="spinner">Loading…</div>';
    $("#page").replaceChildren(el);
    try {
      await pages[name](el, parts.slice(1), query);
    } catch (e) {
      if (e.message !== "unauthorized") el.innerHTML = `<div class="card err-text">Failed to load: ${esc(e.message)}</div>`;
    }
  }

  // ---------- boot ----------
  window.addEventListener("hashchange", () => route());
  $("#google-btn").onclick = googleSignIn;
  $("#token-btn").onclick = () => useToken($("#token-input").value.trim()).catch((e) => { $("#login-err").textContent = e.message; });
  $("#logout-btn").onclick = () => signOut("");
  setInterval(() => { if (state.token) refreshBanner(); }, 5 * 60 * 1000);

  let saved = null;
  try { saved = sessionStorage.getItem(TOKEN_KEY); } catch (e) { /* ignore */ }
  if (saved) useToken(saved).catch(() => signOut(""));
  else signOut("");
})();
