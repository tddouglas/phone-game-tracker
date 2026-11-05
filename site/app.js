(() => {
"use strict";

const app = document.getElementById("app");
const S = { data: null, charts: [] };

// ---------- utils
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const addDays = (iso, n) => { const d = new Date(iso + "T12:00:00Z"); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
const fmtDate = (iso, o) => new Date(iso + "T12:00:00Z").toLocaleDateString(undefined, Object.assign({ month: "short", day: "numeric", timeZone: "UTC" }, o || {}));
const fmtLong = iso => fmtDate(iso, { weekday: "long", month: "long", year: "numeric" });
const better = (a, b, g) => g.direction === "higher" ? a > b : a < b;
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
function fmtNum(v, g) {
  if (v == null || isNaN(v)) return "–";
  if (g && g.unit === "seconds") { v = Math.round(v); return Math.floor(v / 60) + ":" + String(v % 60).padStart(2, "0"); }
  return Number.isInteger(v) ? String(v) : v.toFixed(2);
}
function push(m, k, v) { if (!m.has(k)) m.set(k, []); m.get(k).push(v); }
const pLink = p => `<a href="#/player/${p.id}"><span class="dot" style="background:${color(p.id)}"></span>${esc(p.name)}</a>`;
const gIcon = g => g.icon ? `<img class="gicon" src="${esc(g.icon)}" alt="" loading="lazy">` : "";
const gLink = g => `<a href="#/game/${encodeURIComponent(g.key)}">${gIcon(g)}${esc(g.name)}</a>`;
const pct = v => v == null ? "–" : Math.round(v * 100) + "%";
function delta(v) {
  if (v == null) return "";
  return `<span class="delta ${v > 0 ? "up" : v < 0 ? "down" : ""}">${v > 0 ? "▲ " + v : v < 0 ? "▼ " + -v : "–"}</span>`;
}
function table(cols, rows) {
  return `<div class="scroll"><table><thead><tr>${cols.map(([l, c]) => `<th class="${c || ""}">${l}</th>`).join("")}</tr></thead>
    <tbody>${rows.map(r => `<tr class="${r.cls || ""}">${r.cells.map((x, i) => `<td class="${cols[i][1] || ""}">${x}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}
// A share as a chat bubble: header row (who or what, plus date) above the message.
function shareCard(r, head, game) {
  return `<div class="msg"><div class="row small head">${head}<span class="spacer"></span><a class="muted" href="#/day/${r.d}">${fmtDate(r.d)}</a></div>
    <div class="bubble">${game ? `<div class="small game">${gLink(game)}</div>` : ""}${r.raw ? `<pre class="share">${esc(r.raw)}</pre>` : `<b>${esc(r.sd)}</b>`}</div></div>`;
}

// Player colors: fixed slot per player (alphabetical), never re-assigned by filter.
function color(pid) {
  const i = S.data.players.findIndex(p => p.id === pid);
  return i >= 0 && i < 8 ? css("--s" + (i + 1)) : css("--muted");
}

// ---------- data
function prep(d) {
  d.P = new Map(d.players.map(p => [p.id, p]));
  d.G = new Map(d.games.map(g => [g.key, g]));
  d.results.sort((a, b) => a.d < b.d ? -1 : a.d > b.d ? 1 : (a.t < b.t ? -1 : 1));
  d.days = [...new Set(d.results.map(r => r.d))].sort();
  d.latest = d.days[d.days.length - 1];
  d.byGame = new Map(); d.byPlayer = new Map(); d.byDay = new Map();
  for (const r of d.results) { push(d.byGame, r.g, r); push(d.byPlayer, r.p, r); push(d.byDay, r.d, r); }
  d.gameDays = new Map([...d.byGame].map(([k, rs]) => [k, [...new Set(rs.map(r => r.d))].sort()]));
}

// ---------- ratings (precomputed by gamechat/ratings.py; cumulative)
const R = () => S.data.ratings || { days: [], overall: {}, games: {}, power: [], h2h: {}, extras: {} };
// No results in the last 14 days: still listed, but greyed out.
const idle = pid => { const rs = S.data.byPlayer.get(pid) || []; return !rs.length || rs[rs.length - 1].d < addDays(S.data.latest, -13); };
// Settled ratings first, then provisional; each by rating.
const byRating = (a, b) => (a.e.prov - b.e.prov) || (b.e.r - a.e.r);
const rowCls = x => (x.e.prov ? "prov " : "") + (idle(x.p.id) ? "idle" : "");
const overallRows = () => Object.entries(R().overall).map(([id, e]) => ({ p: S.data.P.get(id), e })).filter(x => x.p).sort(byRating);
const ratingCell = e => `<b class="${e.prov ? "prov" : ""}" title="${e.n} rated day${e.n === 1 ? "" : "s"}${e.prov ? " · provisional" : ""}">${e.r}</b>`;

function ratingChart(id, rows, spark) {
  const days = R().days;
  if (!window.Chart || !days.length || !rows.length) return;
  const opts = spark ? { pointRadius: 0 } : {};
  lineChart(id, days, rows.map(x => line(x.p.name, x.e.hist, color(x.p.id), days.length, opts)), { fmt: v => Math.round(v), spark });
}

// Per player per game. "Missed" = a day someone in the chat played this game, on/after
// the player's first-ever play of it, that they didn't post.
function statsFor(pid, gk) {
  const d = S.data, g = d.G.get(gk), all = d.byGame.get(gk) || [];
  const mine = all.filter(r => r.p === pid);
  if (!mine.length) return null;
  const rs = mine, first = mine[0].d;
  const active = d.gameDays.get(gk);
  const myDays = new Set(mine.map(r => r.d));
  const missed = active.filter(x => x >= first && !myDays.has(x));
  let streak = 0;
  for (let i = active.length - 1; i >= 0 && myDays.has(active[i]); i--) streak++;
  const out = { g, played: rs.length, missed, streak, rs, first };
  if (!rs.length) return out;
  let best = rs[0], worst = rs[0], sum = 0, fails = 0;
  for (const r of rs) {
    sum += r.s; if (r.f) fails++;
    if (better(r.s, best.s, g)) best = r;
    if (better(worst.s, r.s, g)) worst = r;
  }
  return Object.assign(out, { avg: sum / rs.length, best, worst, fails });
}

// ---------- chrome
function setNav(v) {
  document.querySelectorAll("#nav a").forEach(a => a.classList.toggle("on", a.dataset.v === v));
}
function killCharts() { S.charts.forEach(c => c.destroy()); S.charts = []; }
function line(label, data, c, n, extra) {
  return Object.assign({ label, data, borderColor: c, backgroundColor: c, borderWidth: 2, pointRadius: n > 60 ? 0 : 3, pointHoverRadius: 5,
    pointBorderColor: css("--surface"), pointBorderWidth: 1, spanGaps: true, cubicInterpolationMode: "monotone" }, extra);
}
// o: { fmt, reverse, label (tooltip callback), spark (no legend / x axis) }
function lineChart(id, days, datasets, o) {
  const grid = css("--line"), ink = css("--text-2");
  S.charts.push(new Chart(document.getElementById(id), {
    type: "line",
    data: { labels: days.map(x => fmtDate(x)), datasets },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      // Let points at the min/max draw a few px past the plot edge instead of being cut in half
      layout: { padding: { top: 6, bottom: 6 } },
      datasets: { line: { clip: 6 } },
      interaction: { mode: "index", intersect: false },
      scales: {
        y: { reverse: !!o.reverse, grid: { color: grid }, ticks: { color: ink, callback: o.fmt, maxTicksLimit: o.spark ? 4 : 11 }, border: { display: false } },
        x: { display: !o.spark, grid: { display: false }, ticks: { color: ink, maxRotation: 0, autoSkipPadding: 16 } },
      },
      plugins: {
        legend: { display: !o.spark, labels: { color: ink, usePointStyle: true, boxWidth: 8, boxHeight: 8 } },
        tooltip: { backgroundColor: css("--surface-2"), titleColor: css("--text"), bodyColor: css("--text"), borderColor: css("--line"), borderWidth: 1,
          callbacks: { label: o.label || (ctx => ctx.raw == null ? null : ` ${ctx.dataset.label}: ${o.fmt(ctx.raw)}`) } },
      },
    },
  }));
}

// Overall rating for each of the last 14 calendar days, ending at the latest rated day.
function weeklyRatings() {
  const rt = R();
  if (!rt.days.length) return { weeks: [], rows: [] };
  const weeks = [];
  for (let i = 0, x = rt.days[rt.days.length - 1]; i < 14 && x >= rt.days[0]; i++, x = addDays(x, -1)) weeks.unshift(x);
  const at = (hist, day) => { let v = null; rt.days.forEach((x, i) => { if (x <= day && hist[i] != null) v = hist[i]; }); return v; };
  const rows = overallRows().map(x => ({ ...x, w: weeks.map(day => at(x.e.hist, day)) }));
  return { weeks, rows };
}

// ---------- views
function viewHome(day) {
  const d = S.data;
  day = day || d.latest;
  const rs = d.byDay.get(day) || [];
  const idx = d.days.indexOf(day);
  const prev = idx > 0 ? d.days[idx - 1] : d.days.filter(x => x < day).pop();
  const next = idx >= 0 ? d.days[idx + 1] : d.days.find(x => x > day);

  const counts = new Map();
  rs.forEach(r => counts.set(r.g, (counts.get(r.g) || 0) + 1));
  const games = [...counts.keys()].sort((a, b) => counts.get(b) - counts.get(a) || d.G.get(a).name.localeCompare(d.G.get(b).name));
  const recentFrom = addDays(day, -13);
  // Grid shows everyone; the Missing list only nags people active in the last 2 weeks.
  const roster = d.players.filter(p => (d.byPlayer.get(p.id) || []).some(r => r.d >= recentFrom && r.d <= day));
  const has = new Map(rs.map(r => [r.p + "|" + r.g, r]));
  const everPlayed = (pid, gk) => (d.byGame.get(gk) || []).some(r => r.p === pid && r.d <= day);

  let table = `<p class="muted">Nobody posted a game this day.</p>`;
  if (games.length) {
    table = `<div class="scroll"><table class="day"><thead><tr><th>Game</th>${d.players.map(p => `<th class="num">${pLink(p)}</th>`).join("")}</tr></thead><tbody>`;
    for (const gk of games) {
      const g = d.G.get(gk);
      const scores = rs.filter(r => r.g === gk).map(r => r.s);
      const top = scores.reduce((a, b) => better(b, a, g) ? b : a);
      const bottom = scores.reduce((a, b) => better(a, b, g) ? b : a);
      table += `<tr><td>${gLink(g)}</td>`;
      for (const p of d.players) {
        const r = has.get(p.id + "|" + gk);
        if (r) {
          const cls = scores.length > 1 && r.s === top ? "best" : scores.length > 2 && r.s === bottom ? "worst" : "";
          table += `<td class="cell"><span class="pill ${cls}" title="${esc(r.raw || r.sd)}">${esc(r.sd)}</span></td>`;
        } else {
          table += everPlayed(p.id, gk) ? `<td class="cell miss" title="Didn't post">–</td>` : `<td class="cell"></td>`;
        }
      }
      table += `</tr>`;
    }
    table += `</tbody></table></div>`;
  }

  const missing = roster.map(p => {
    const m = games.filter(gk => !has.has(p.id + "|" + gk) && everPlayed(p.id, gk));
    return m.length ? `<div class="row small" style="margin:4px 0">${pLink(p)} <span class="muted">missed</span> ${m.map(gk => `<span class="chip">${esc(d.G.get(gk).name)}</span>`).join(" ")}</div>` : "";
  }).join("");

  // Latest shares across all days, newest first.
  const strip = d.results.slice(-24).reverse().map(r => shareCard(r, pLink(d.P.get(r.p)), d.G.get(r.g))).join("");

  const wk = weeklyRatings();

  app.innerHTML = `
    <h2>Recent games</h2>
    <div class="strip">${strip}</div>
    <div class="card" id="daily">
      <div class="row" style="margin-bottom:4px">
        <h2 style="margin:0">${fmtLong(day)}</h2><span class="spacer"></span>
        <div class="daynav">
          <a class="btn" ${prev ? `href="#/day/${prev}"` : "disabled"} aria-label="Previous day">‹</a>
          <input type="date" id="pick" value="${day}" min="${d.days[0]}" max="${d.latest}">
          <a class="btn" ${next ? `href="#/day/${next}"` : "disabled"} aria-label="Next day">›</a>
        </div>
      </div>
      <p class="muted small" style="margin:0 0 10px">${rs.length} result${rs.length === 1 ? "" : "s"} across ${games.length} game${games.length === 1 ? "" : "s"}. Green = best that day, “–” = played this game before but didn't post.</p>
      ${table}
    </div>
    ${wk.rows.length ? `<div class="card"><h2>Rating trend <span class="muted small" style="font-weight:400">· past 2 weeks</span></h2>
      <div class="chart-box"><canvas id="wchart" aria-label="Overall rating by player, day by day" role="img"></canvas></div>
      <p class="muted small" style="margin:10px 0 0">Overall rating at the end of each day.</p></div>` : ""}
    ${missing ? `<div class="card"><h2>Missing Today</h2>${missing}</div>` : ""}`;
  document.getElementById("pick").onchange = e => { if (e.target.value) location.hash = "#/day/" + e.target.value; };

  if (window.Chart && wk.weeks.length && wk.rows.length) {
    lineChart("wchart", wk.weeks, wk.rows.map(x => line(x.p.name, x.w, color(x.p.id), wk.weeks.length)), { fmt: v => Math.round(v), label: ctx => {
      if (ctx.raw == null) return null;
      const before = ctx.dataset.data[ctx.dataIndex - 1];
      return ` ${ctx.dataset.label}: ${Math.round(ctx.raw)}${before != null ? ` (${ctx.raw >= before ? "+" : ""}${Math.round(ctx.raw - before)} day)` : ""}`;
    } });
  }
}

function viewGames() {
  const d = S.data;
  const cards = d.games.map(g => {
    const rs = d.byGame.get(g.key) || [];
    const players = new Set(rs.map(r => r.p)).size;
    const days = d.gameDays.get(g.key);
    return { g, n: rs.length, players, first: days[0], last: days[days.length - 1] };
  }).sort((a, b) => b.n - a.n);
  app.innerHTML = `<h1>Games</h1><p class="sub">${d.games.length} games spotted in the chat. New ones show up automatically.</p>
    <div class="grid">${cards.map(c => `
      <a class="card" href="#/game/${encodeURIComponent(c.g.key)}">
        <h2 style="margin-bottom:4px">${gIcon(c.g)}${esc(c.g.name)}</h2>
        <div class="muted small">${c.g.direction === "higher" ? "Higher" : "Lower"} is better · ${esc(c.g.unit)}</div>
        <div class="stats"><div class="stat"><b>${c.n}</b><span>results</span></div><div class="stat"><b>${c.players}</b><span>players</span></div></div>
        <div class="muted small">${fmtDate(c.first, { year: "numeric" })} → ${fmtDate(c.last)}</div>
      </a>`).join("")}</div>`;
}

function viewGame(gk) {
  const d = S.data, g = d.G.get(gk);
  if (!g) { app.innerHTML = `<p>Unknown game.</p>`; return; }
  const gr = R().games[gk] || {};
  const byAvg = (a, b) => better(a.s.avg, b.s.avg, g) ? -1 : better(b.s.avg, a.s.avg, g) ? 1 : b.s.played - a.s.played;
  const rows = d.players.map(p => ({ p, s: statsFor(p.id, gk), e: gr[p.id] })).filter(x => x.s && x.s.played)
    .sort((a, b) => a.e && b.e ? byRating(a, b) : a.e || b.e ? (a.e ? -1 : 1) : byAvg(a, b));
  const rated = Object.entries(gr).map(([id, e]) => ({ p: d.P.get(id), e })).filter(x => x.p).sort(byRating);
  const days = d.gameDays.get(gk);
  const recent = (d.byGame.get(gk) || []).slice(-18).reverse();

  app.innerHTML = `
    <h1>${gIcon(g)}${esc(g.name)}${g.url ? ` <a class="muted small" href="${esc(g.url)}" target="_blank" rel="noopener">play ↗</a>` : ""}</h1>
    <p class="sub">${g.direction === "higher" ? "Higher" : "Lower"} is better · ${days.length} day${days.length === 1 ? "" : "s"} played</p>
    <div class="card"><h2>Leaderboard</h2>${rows.length ? `<div class="scroll"><table>
      <thead><tr><th>#</th><th>Player</th><th class="num">Rating</th><th class="num">7d</th><th class="num">Played</th><th class="num">Avg</th><th class="num">Best</th><th class="num">Worst</th><th class="num">Fails</th><th class="num">Missed</th><th class="num">Streak</th></tr></thead>
      <tbody>${rows.map((x, i) => `<tr class="${idle(x.p.id) ? "idle" : ""}"><td class="muted">${i + 1}</td><td>${pLink(x.p)}</td>
        <td class="num">${x.e ? ratingCell(x.e) : "<span class='muted'>–</span>"}</td><td class="num">${x.e ? delta(x.e.d7) : ""}</td>
        <td class="num">${x.s.played}</td><td class="num"><b>${fmtNum(x.s.avg, g)}</b></td>
        <td class="num" title="${x.s.best.d}">${esc(x.s.best.sd)} <span class="muted small">${fmtDate(x.s.best.d)}</span></td>
        <td class="num" title="${x.s.worst.d}">${esc(x.s.worst.sd)} <span class="muted small">${fmtDate(x.s.worst.d)}</span></td>
        <td class="num">${x.s.fails}</td><td class="num">${x.s.missed.length}</td><td class="num">${x.s.streak}</td></tr>`).join("")}</tbody>
    </table></div>
    <p class="muted small" style="margin:10px 0 0">Ranked by rating (all-time Elo from head-to-head results each day). <i>Italic</i> = provisional, under 5 rated days.</p>` : `<p class="muted">No results yet.</p>`}</div>
    <div class="card"><div class="row"><h2 style="margin:0">Scores over time</h2><span class="spacer"></span>
      <span class="muted small">${g.direction === "higher" ? "" : "Up = better · "}</span>
      <div class="range" id="smooth"><button data-m="avg" class="${S.smooth !== "raw" ? "on" : ""}">7-day avg</button><button data-m="raw" class="${S.smooth === "raw" ? "on" : ""}">Daily</button></div></div>
      <div class="chart-box" style="margin-top:10px"><canvas id="chart" aria-label="${esc(g.name)} scores by player over time" role="img"></canvas></div>
      <details style="margin-top:10px"><summary>Table view</summary><div class="scroll"><table><thead><tr><th>Date</th>${rows.map(x => `<th class="num">${esc(x.p.name)}</th>`).join("")}</tr></thead>
      <tbody>${days.slice().reverse().map(day => `<tr><td>${fmtDate(day)}</td>${rows.map(x => { const r = x.s.rs.find(r => r.d === day); return `<td class="num">${r ? esc(r.sd) : "<span class='muted'>–</span>"}</td>`; }).join("")}</tr>`).join("")}</tbody></table></div></details>
    </div>
    ${rated.length ? `<div class="card"><h2>Rating over time</h2>
      <div class="chart-box"><canvas id="rchart" aria-label="${esc(g.name)} ratings by player over time" role="img"></canvas></div></div>` : ""}
    <h2>Recent shares</h2><div class="feed">${recent.map(r => shareCard(r, pLink(d.P.get(r.p)))).join("")}</div>`;

  if (window.Chart && rows.length && days.length) {
    const smooth = S.smooth !== "raw";
    const datasets = rows.map(x => {
      const byDay = new Map(x.s.rs.map(r => [r.d, r]));
      const c = color(x.p.id);
      // Days the player didn't play stay null so the line breaks there instead of bridging.
      const data = days.map(day => {
        if (!byDay.has(day)) return null;
        if (!smooth) return byDay.get(day).s;
        const win = x.s.rs.filter(r => r.d <= day && r.d > addDays(day, -7));
        return win.reduce((a, r) => a + r.s, 0) / win.length;
      });
      // A lone day between gaps has no segment, so give it a dot or it vanishes.
      const base = smooth || days.length > 60 ? 0 : 3;
      const pointRadius = ctx => { const i = ctx.dataIndex; return data[i] != null && data[i - 1] == null && data[i + 1] == null ? 4 : base; };
      return line(x.p.name, data, c, days.length, { _r: days.map(day => byDay.get(day)), spanGaps: false, pointRadius });
    });
    lineChart("chart", days, datasets, { reverse: g.direction !== "higher", fmt: v => fmtNum(v, g), label: ctx => {
      const r = ctx.dataset._r[ctx.dataIndex];
      if (smooth) return ctx.raw == null ? null : ` ${ctx.dataset.label}: ${fmtNum(ctx.raw, g)} avg${r ? " (today " + r.sd + ")" : ""}`;
      return r ? ` ${ctx.dataset.label}: ${r.sd}` : null; } });
  }
  if (rated.length) ratingChart("rchart", rated);
  const sm = document.getElementById("smooth");
  if (sm) sm.onclick = e => { const b = e.target.closest("button"); if (!b) return; S.smooth = b.dataset.m; route(); };
}

function viewRankings() {
  const d = S.data, rt = R(), ov = overallRows(), field = rt.extras.field || {};
  if (!ov.length) {
    app.innerHTML = `<h1>Rankings</h1><p class="sub">Ratings start once two people play the same game on the same day.</p>`;
    return;
  }
  const power = rt.power.filter(x => d.P.has(x.p)).map(x => ({ cls: idle(x.p) ? "idle" : "", cells: [
    `${x.rank} ${x.prev_rank == null ? `<span class="delta">new</span>` : delta(x.prev_rank - x.rank)}`,
    pLink(d.P.get(x.p)), `<b>${x.power}</b>`, pct(x.form), ratingCell(rt.overall[x.p])] }));
  const overall = ov.map((x, i) => ({ cls: rowCls(x), cells: [
    `<span class="muted">${i + 1}</span>`, pLink(x.p), ratingCell(x.e), delta(x.e.d7),
    pct(field[x.p.id] && field[x.p.id].pct), x.e.n] }));

  // Superlatives need enough days that one lucky week doesn't win them.
  const settled = Object.entries(field).filter(([id, f]) => d.P.has(id) && f.days >= 10);
  const pick = (xs, f) => xs.length ? xs.reduce((a, b) => f(b) > f(a) ? b : a) : null;
  const steady = pick(settled.filter(([, f]) => f.sd != null), ([, f]) => -f.sd);
  const top = pick(settled, ([, f]) => f.pct);
  const imp = (rt.extras.most_improved || []).find(x => x.delta > 0 && d.P.has(x.p));
  const hot = rt.power[0];
  const tile = (name, label) => `<div class="stat"><b>${esc(name)}</b><span>${label}</span></div>`;
  const tiles = [
    hot && tile(d.P.get(hot.p).name, `in form · ${pct(hot.form)} last 2 wks`),
    imp && tile(d.P.get(imp.p).name, `most improved · ▲ ${imp.delta} in 14d`),
    top && tile(d.P.get(top[0]).name, `best vs field · ${pct(top[1].pct)}`),
    steady && tile(d.P.get(steady[0]).name, `most consistent`),
  ].filter(Boolean).join("");
  const upsets = (rt.extras.upsets || []).filter(u => d.P.has(u.w) && d.P.has(u.l) && d.G.has(u.g)).slice(0, 5);

  app.innerHTML = `
    <h1>Rankings</h1>
    <p class="sub">All-time ratings from every head-to-head result.</p>
    <div class="card"><h2>Power rankings</h2>${power.length
      ? table([["#"], ["Player"], ["Power", "num"], ["Form", "num"], ["Rating", "num"]], power)
      : `<p class="muted">Nobody has 3+ game days in the last two weeks.</p>`}
      <p class="muted small" style="margin:10px 0 0">Half rating, half recent form (share of head-to-heads won, last games weighted most). Needs 3+ game days in the last 2 weeks. Arrows = change since a week ago.</p></div>
    ${tiles ? `<div class="card"><div class="stats" style="margin:0">${tiles}</div></div>` : ""}
    <div class="card"><h2>Overall rating</h2>
      ${table([["#"], ["Player"], ["Rating", "num"], ["7d", "num"], ["Vs field", "num"], ["Days", "num"]], overall)}
      <p class="muted small" style="margin:10px 0 0">Each game's Elo, weighted by how much you've played it. Games with few results count less. <i>Italic</i> = provisional, under 10 rated days. Greyed = no results in 2 weeks.</p></div>
    <div class="card"><h2>Rating over time</h2>
      <div class="chart-box"><canvas id="rchart" aria-label="Overall rating by player over time" role="img"></canvas></div></div>
    ${upsets.length ? `<div class="card"><h2>Biggest upsets</h2>${upsets.map(u => `<div class="row small" style="margin:4px 0">
      ${pLink(d.P.get(u.w))} <span class="muted">beat</span> ${pLink(d.P.get(u.l))} <span class="muted">in</span> ${gLink(d.G.get(u.g))}
      <span class="spacer"></span><span class="muted">${pct(u.e)} chance · <a href="#/day/${u.d}">${fmtDate(u.d)}</a></span></div>`).join("")}</div>` : ""}`;
  ratingChart("rchart", ov);
}

function viewPlayers() {
  const d = S.data;
  app.innerHTML = `<h1>Players</h1><p class="sub">Anyone who's posted a result. New numbers in the chat appear here after their first share.</p>
    <div class="grid wide">${d.players.map(p => {
      const rs = d.byPlayer.get(p.id) || [];
      const days = new Set(rs.map(r => r.d)).size, games = new Set(rs.map(r => r.g)).size;
      const last = (d.byPlayer.get(p.id) || []).slice(-1)[0];
      return `<a class="card" href="#/player/${p.id}"><h2 style="margin-bottom:4px"><span class="dot" style="background:${color(p.id)}"></span>${esc(p.name)}</h2>
        <div class="stats row3"><div class="stat"><b>${rs.length}</b><span>results</span></div><div class="stat"><b>${days}</b><span>days</span></div><div class="stat"><b>${games}</b><span>games</span></div></div>
        <div class="muted small">Last played ${last ? fmtDate(last.d) : "–"}</div></a>`;
    }).join("")}</div>`;
}

function heatmap(pid) {
  const d = S.data, end = d.latest;
  const counts = new Map();
  (d.byPlayer.get(pid) || []).forEach(r => counts.set(r.d, (counts.get(r.d) || 0) + 1));
  let startDay = addDays(end, -181);
  const pad = new Date(startDay + "T12:00:00Z").getUTCDay();
  let cells = "<i class='pad'></i>".repeat(pad);
  for (let x = startDay; x <= end; x = addDays(x, 1)) {
    const n = counts.get(x) || 0;
    const l = n === 0 ? "" : n === 1 ? "l1" : n <= 2 ? "l2" : n <= 4 ? "l3" : "l4";
    cells += `<i class="${l}" title="${fmtDate(x)}: ${n} game${n === 1 ? "" : "s"}"></i>`;
  }
  return `<div class="heat">${cells}</div><div class="muted small" style="margin-top:6px">Last 26 weeks · darker = more games that day</div>`;
}

function viewPlayer(id) {
  const d = S.data, p = d.P.get(id);
  if (!p) { app.innerHTML = `<p>Unknown player.</p>`; return; }
  const per = d.games.map(g => statsFor(id, g.key)).filter(Boolean).sort((a, b) => b.played - a.played);
  const all = (d.byPlayer.get(id) || []);
  const recent = all.slice(-12).reverse();
  const firstDay = all[0] && all[0].d;
  const rt = R(), ov = overallRows(), o = rt.overall[id], f = (rt.extras.field || {})[id];
  const pw = rt.power.find(x => x.p === id);
  const h2h = Object.entries(rt.h2h[id] || {}).filter(([opp]) => d.P.has(opp))
    .map(([opp, [w, l, t]]) => ({ opp: d.P.get(opp), w, l, t, n: w + l + t })).sort((a, b) => b.n - a.n);
  const ratingCard = o ? `<div class="card"><h2>Rating</h2>
    <div class="stats">
      <div class="stat"><b class="${o.prov ? "prov" : ""}">${o.r} ${delta(o.d7)}</b><span>rating · 7d</span></div>
      <div class="stat"><b>#${ov.findIndex(x => x.p.id === id) + 1}</b><span>of ${ov.length} overall</span></div>
      <div class="stat"><b>${pw ? "#" + pw.rank : "–"}</b><span>power rank</span></div>
      ${f ? `<div class="stat"><b>${pct(f.pct)}</b><span>vs field</span></div>` : ""}
    </div>
    <div class="chart-box spark"><canvas id="rchart" aria-label="${esc(p.name)} overall rating over time" role="img"></canvas></div>
    ${h2h.length ? `<details style="margin-top:10px"><summary>Head-to-head</summary>
      ${table([["Opponent"], ["W", "num"], ["L", "num"], ["T", "num"], ["Win %", "num"]],
        h2h.map(x => ({ cells: [pLink(x.opp), x.w, x.l, x.t, pct((x.w + 0.5 * x.t) / x.n)] })))}</details>` : ""}
  </div>` : "";

  app.innerHTML = `
    <h1><span class="dot" style="background:${color(id)};width:12px;height:12px"></span>${esc(p.name)}</h1>
    <p class="sub">Playing since ${firstDay ? fmtDate(firstDay, { year: "numeric" }) : "–"} · ${all.length} results all-time</p>
    ${ratingCard}
    <div class="card"><h2>Activity</h2>${heatmap(id)}</div>
    <div class="grid">${per.map(s => { const e = (rt.games[s.g.key] || {})[id]; return `
      <div class="card">
        <div class="row"><h2 style="margin:0">${gLink(s.g)}</h2><span class="spacer"></span><span class="muted small">${s.g.direction === "higher" ? "↑ better" : "↓ better"}</span></div>
        ${s.played ? `<div class="stats">${e ? `<div class="stat"><b class="${e.prov ? "prov" : ""}">${e.r}</b><span>rating</span></div>` : ""}<div class="stat"><b>${s.played}</b><span>played</span></div><div class="stat"><b>${fmtNum(s.avg, s.g)}</b><span>avg</span></div><div class="stat"><b>${s.streak}</b><span>streak</span></div></div>
        <dl class="kv">
          <dt>Best</dt><dd>${esc(s.best.sd)} <a class="muted small" href="#/day/${s.best.d}">${fmtDate(s.best.d)}</a></dd>
          <dt>Worst</dt><dd>${esc(s.worst.sd)} <a class="muted small" href="#/day/${s.worst.d}">${fmtDate(s.worst.d)}</a></dd>
          <dt>Fails</dt><dd>${s.fails}</dd>
        </dl>` : `<p class="muted small">Not played yet.</p>`}
        ${s.missed.length ? `<details style="margin-top:8px"><summary>Missed ${s.missed.length} day${s.missed.length === 1 ? "" : "s"}</summary>
          <div class="chips" style="margin-top:6px">${s.missed.slice().reverse().map(x => `<a class="chip" href="#/day/${x}">${fmtDate(x)}</a>`).join("")}</div></details>`
          : `<p class="muted small" style="margin:8px 0 0">No missed days</p>`}
      </div>`; }).join("")}</div>
    <h2 style="margin-top:20px">Recent shares</h2>
    <div class="feed">${recent.map(r => shareCard(r, gLink(d.G.get(r.g)))).join("")}</div>`;
  // On narrow screens the heatmap scrolls; start at the most recent weeks.
  const heat = app.querySelector(".heat");
  if (heat) heat.scrollLeft = heat.scrollWidth;
  if (o) ratingChart("rchart", [{ p, e: o }], true);
}

// ---------- router
function route() {
  if (!S.data) return;
  killCharts();
  const [, view = "", arg] = (location.hash.slice(1) || "/").split("/");
  const a = arg && decodeURIComponent(arg);
  if (view === "rankings") { setNav("rankings"); viewRankings(); }
  else if (view === "game" && a) { setNav("games"); viewGame(a); }
  else if (view === "games") { setNav("games"); viewGames(); }
  else if (view === "player" && a) { setNav("players"); viewPlayer(a); }
  else if (view === "players") { setNav("players"); viewPlayers(); }
  else { setNav(""); viewHome(view === "day" ? a : null); }
}

async function init() {
  try {
    S.data = window.__DATA__ || await (await fetch("data.json", { cache: "no-store" })).json();
  } catch (e) {
    app.innerHTML = `<h1>No data yet</h1><p class="sub">Run <code>python3 -m gamechat sync</code> on the Mac to generate <code>data.json</code>.</p>`;
    return;
  }
  if (!S.data.results.length) { app.innerHTML = `<h1>No results yet</h1>`; return; }
  prep(S.data);
  if (window.Chart) Chart.defaults.font.family = css("--body");
  document.title = S.data.title;
  document.getElementById("brand").textContent = S.data.title;
  document.getElementById("foot").textContent = `Updated ${new Date(S.data.generated_at).toLocaleString()} · ${S.data.results.length} results`;
  // Day links land on the daily grid, below the recent-games strip.
  const go = () => {
    route();
    const daily = document.getElementById("daily");
    if (daily && location.hash.startsWith("#/day/")) daily.scrollIntoView(); else window.scrollTo(0, 0);
  };
  window.addEventListener("hashchange", go);
  matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", route);
  go();
}
init();
})();
