(() => {
"use strict";

const app = document.getElementById("app");
const S = { data: null, range: "all", charts: [] };
try { S.range = localStorage.getItem("gc-range") || "all"; } catch (e) {}
const RANGES = [["7", "7d"], ["30", "30d"], ["90", "90d"], ["all", "All"]];

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
const gLink = g => `<a href="#/game/${encodeURIComponent(g.key)}">${esc(g.name)}</a>`;

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
const rangeStart = () => S.range === "all" ? "0000-00-00" : addDays(S.data.latest, -(+S.range - 1));

// Per player per game. "Missed" = a day someone in the chat played this game, on/after
// the player's first-ever play of it, that they didn't post.
function statsFor(pid, gk) {
  const d = S.data, g = d.G.get(gk), all = d.byGame.get(gk) || [];
  const mine = all.filter(r => r.p === pid);
  if (!mine.length) return null;
  const start = rangeStart(), first = mine[0].d;
  const rs = mine.filter(r => r.d >= start);
  const active = d.gameDays.get(gk);
  const myDays = new Set(mine.map(r => r.d));
  const missed = active.filter(x => x >= first && x >= start && !myDays.has(x));
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
function renderRange() {
  const el = document.getElementById("range");
  el.innerHTML = RANGES.map(([v, l]) => `<button data-r="${v}" class="${S.range === v ? "on" : ""}">${l}</button>`).join("");
  el.onclick = e => {
    const b = e.target.closest("button"); if (!b) return;
    S.range = b.dataset.r; try { localStorage.setItem("gc-range", S.range); } catch (err) {}
    renderRange(); route();
  };
}
function setNav(v) {
  document.querySelectorAll("#nav a").forEach(a => a.classList.toggle("on", a.dataset.v === v));
}
function killCharts() { S.charts.forEach(c => c.destroy()); S.charts = []; }

// ---------- views
function viewDay(day) {
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
  const roster = d.players.filter(p => (d.byPlayer.get(p.id) || []).some(r => r.d >= recentFrom && r.d <= day));
  const has = new Map(rs.map(r => [r.p + "|" + r.g, r]));
  const everPlayed = (pid, gk) => (d.byGame.get(gk) || []).some(r => r.p === pid && r.d <= day);

  let table = `<p class="muted">Nobody posted a game this day.</p>`;
  if (games.length) {
    table = `<div class="scroll"><table class="day"><thead><tr><th>Game</th>${roster.map(p => `<th class="num">${pLink(p)}</th>`).join("")}</tr></thead><tbody>`;
    for (const gk of games) {
      const g = d.G.get(gk);
      const scores = rs.filter(r => r.g === gk).map(r => r.s);
      const top = scores.reduce((a, b) => better(b, a, g) ? b : a);
      const bottom = scores.reduce((a, b) => better(a, b, g) ? b : a);
      table += `<tr><td>${gLink(g)}</td>`;
      for (const p of roster) {
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

  const feed = rs.slice().sort((a, b) => a.t < b.t ? 1 : -1).slice(0, 24).map(r =>
    `<div class="card"><div class="row small">${pLink(d.P.get(r.p))}<span class="spacer"></span>${gLink(d.G.get(r.g))}</div>
     ${r.raw ? `<pre class="share">${esc(r.raw)}</pre>` : `<div style="margin-top:6px"><b>${esc(r.sd)}</b></div>`}</div>`).join("");

  app.innerHTML = `
    <div class="row" style="margin-bottom:4px">
      <h1>${fmtLong(day)}</h1><span class="spacer"></span>
      <div class="daynav">
        <a class="btn" ${prev ? `href="#/day/${prev}"` : "disabled"} aria-label="Previous day">‹</a>
        <input type="date" id="pick" value="${day}" min="${d.days[0]}" max="${d.latest}">
        <a class="btn" ${next ? `href="#/day/${next}"` : "disabled"} aria-label="Next day">›</a>
      </div>
    </div>
    <p class="sub">${rs.length} result${rs.length === 1 ? "" : "s"} across ${games.length} game${games.length === 1 ? "" : "s"}. Green = best that day, “–” = a regular who didn't post.</p>
    <div class="card">${table}</div>
    ${missing ? `<div class="card"><h2>Missing</h2>${missing}</div>` : ""}
    ${feed ? `<h2>Shares</h2><div class="feed">${feed}</div>` : ""}`;
  document.getElementById("pick").onchange = e => { if (e.target.value) location.hash = "#/day/" + e.target.value; };
}

function viewGames() {
  const d = S.data, start = rangeStart();
  const cards = d.games.map(g => {
    const rs = (d.byGame.get(g.key) || []).filter(r => r.d >= start);
    const players = new Set(rs.map(r => r.p)).size;
    const days = d.gameDays.get(g.key);
    return { g, n: rs.length, players, first: days[0], last: days[days.length - 1] };
  }).sort((a, b) => b.n - a.n);
  app.innerHTML = `<h1>Games</h1><p class="sub">${d.games.length} games spotted in the chat. New ones show up automatically.</p>
    <div class="grid">${cards.map(c => `
      <a class="card" href="#/game/${encodeURIComponent(c.g.key)}">
        <h2 style="margin-bottom:4px">${esc(c.g.name)}</h2>
        <div class="muted small">${c.g.direction === "higher" ? "Higher" : "Lower"} is better · ${esc(c.g.unit)}</div>
        <div class="stats"><div class="stat"><b>${c.n}</b><span>results</span></div><div class="stat"><b>${c.players}</b><span>players</span></div></div>
        <div class="muted small">${fmtDate(c.first, { year: "numeric" })} → ${fmtDate(c.last)}</div>
      </a>`).join("")}</div>`;
}

function viewGame(gk) {
  const d = S.data, g = d.G.get(gk);
  if (!g) { app.innerHTML = `<p>Unknown game.</p>`; return; }
  const start = rangeStart();
  const rows = d.players.map(p => ({ p, s: statsFor(p.id, gk) })).filter(x => x.s && x.s.played)
    .sort((a, b) => better(a.s.avg, b.s.avg, g) ? -1 : better(b.s.avg, a.s.avg, g) ? 1 : b.s.played - a.s.played);
  const days = d.gameDays.get(gk).filter(x => x >= start);
  const recent = (d.byGame.get(gk) || []).filter(r => r.d >= start).slice(-18).reverse();

  app.innerHTML = `
    <h1>${esc(g.name)}</h1>
    <p class="sub">${g.direction === "higher" ? "Higher" : "Lower"} is better · ${days.length} day${days.length === 1 ? "" : "s"} played in range</p>
    <div class="card"><h2>Leaderboard</h2>${rows.length ? `<div class="scroll"><table>
      <thead><tr><th>#</th><th>Player</th><th class="num">Played</th><th class="num">Avg</th><th class="num">Best</th><th class="num">Worst</th><th class="num">Fails</th><th class="num">Missed</th><th class="num">Streak</th></tr></thead>
      <tbody>${rows.map((x, i) => `<tr><td class="muted">${i + 1}</td><td>${pLink(x.p)}</td>
        <td class="num">${x.s.played}</td><td class="num"><b>${fmtNum(x.s.avg, g)}</b></td>
        <td class="num" title="${x.s.best.d}">${esc(x.s.best.sd)} <span class="muted small">${fmtDate(x.s.best.d)}</span></td>
        <td class="num" title="${x.s.worst.d}">${esc(x.s.worst.sd)} <span class="muted small">${fmtDate(x.s.worst.d)}</span></td>
        <td class="num">${x.s.fails}</td><td class="num">${x.s.missed.length}</td><td class="num">${x.s.streak}</td></tr>`).join("")}</tbody>
    </table></div>` : `<p class="muted">No results in this range.</p>`}</div>
    <div class="card"><div class="row"><h2 style="margin:0">Scores over time</h2><span class="spacer"></span>
      <span class="muted small">${g.direction === "higher" ? "" : "Up = better · "}</span>
      <div class="range" id="smooth"><button data-m="avg" class="${S.smooth !== "raw" ? "on" : ""}">7-day avg</button><button data-m="raw" class="${S.smooth === "raw" ? "on" : ""}">Daily</button></div></div>
      <div class="chart-box" style="margin-top:10px"><canvas id="chart" aria-label="${esc(g.name)} scores by player over time" role="img"></canvas></div>
      <details style="margin-top:10px"><summary>Table view</summary><div class="scroll"><table><thead><tr><th>Date</th>${rows.map(x => `<th class="num">${esc(x.p.name)}</th>`).join("")}</tr></thead>
      <tbody>${days.slice().reverse().map(day => `<tr><td>${fmtDate(day)}</td>${rows.map(x => { const r = x.s.rs.find(r => r.d === day); return `<td class="num">${r ? esc(r.sd) : "<span class='muted'>–</span>"}</td>`; }).join("")}</tr>`).join("")}</tbody></table></div></details>
    </div>
    <h2>Recent shares</h2><div class="feed">${recent.map(r => `<div class="card"><div class="row small">${pLink(d.P.get(r.p))}<span class="spacer"></span><a class="muted" href="#/day/${r.d}">${fmtDate(r.d)}</a></div>
      ${r.raw ? `<pre class="share">${esc(r.raw)}</pre>` : `<b>${esc(r.sd)}</b>`}</div>`).join("")}</div>`;

  if (window.Chart && rows.length && days.length) {
    const smooth = S.smooth !== "raw";
    const datasets = rows.map(x => {
      const byDay = new Map(x.s.rs.map(r => [r.d, r]));
      const c = color(x.p.id);
      const data = days.map(day => {
        if (!smooth) return byDay.has(day) ? byDay.get(day).s : null;
        const win = x.s.rs.filter(r => r.d <= day && r.d > addDays(day, -7));
        return win.length ? win.reduce((a, r) => a + r.s, 0) / win.length : null;
      });
      return { label: x.p.name, data, _r: days.map(day => byDay.get(day)),
        borderColor: c, backgroundColor: c, borderWidth: 2, pointRadius: smooth || days.length > 60 ? 0 : 3, pointHoverRadius: 5,
        pointBorderColor: css("--surface"), pointBorderWidth: 1, spanGaps: true, cubicInterpolationMode: "monotone" };
    });
    const grid = css("--line"), ink = css("--text-2");
    S.charts.push(new Chart(document.getElementById("chart"), {
      type: "line",
      data: { labels: days.map(x => fmtDate(x)), datasets },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          y: { reverse: g.direction !== "higher", grid: { color: grid }, ticks: { color: ink, callback: v => fmtNum(v, g) }, border: { display: false } },
          x: { grid: { display: false }, ticks: { color: ink, maxRotation: 0, autoSkipPadding: 16 } },
        },
        plugins: {
          legend: { labels: { color: ink, usePointStyle: true, boxWidth: 8, boxHeight: 8 } },
          tooltip: { callbacks: { label: ctx => {
            const r = ctx.dataset._r[ctx.dataIndex];
            if (smooth) return ctx.raw == null ? null : ` ${ctx.dataset.label}: ${fmtNum(ctx.raw, g)} avg${r ? " (today " + r.sd + ")" : ""}`;
            return r ? ` ${ctx.dataset.label}: ${r.sd}` : null; } } },
        },
      },
    }));
  }
  const sm = document.getElementById("smooth");
  if (sm) sm.onclick = e => { const b = e.target.closest("button"); if (!b) return; S.smooth = b.dataset.m; route(); };
}

function viewPlayers() {
  const d = S.data, start = rangeStart();
  app.innerHTML = `<h1>Players</h1><p class="sub">Anyone who's posted a result. New numbers in the chat appear here after their first share.</p>
    <div class="grid">${d.players.map(p => {
      const rs = (d.byPlayer.get(p.id) || []).filter(r => r.d >= start);
      const days = new Set(rs.map(r => r.d)).size, games = new Set(rs.map(r => r.g)).size;
      const last = (d.byPlayer.get(p.id) || []).slice(-1)[0];
      return `<a class="card" href="#/player/${p.id}"><h2 style="margin-bottom:4px"><span class="dot" style="background:${color(p.id)}"></span>${esc(p.name)}</h2>
        <div class="stats"><div class="stat"><b>${rs.length}</b><span>results</span></div><div class="stat"><b>${days}</b><span>days</span></div><div class="stat"><b>${games}</b><span>games</span></div></div>
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
  const recent = all.filter(r => r.d >= rangeStart()).slice(-12).reverse();
  const firstDay = all[0] && all[0].d;

  app.innerHTML = `
    <h1><span class="dot" style="background:${color(id)};width:12px;height:12px"></span>${esc(p.name)}</h1>
    <p class="sub">Playing since ${firstDay ? fmtDate(firstDay, { year: "numeric" }) : "–"} · ${all.length} results all-time</p>
    <div class="card"><h2>Activity</h2>${heatmap(id)}</div>
    <div class="grid">${per.map(s => `
      <div class="card">
        <div class="row"><h2 style="margin:0">${gLink(s.g)}</h2><span class="spacer"></span><span class="muted small">${s.g.direction === "higher" ? "↑ better" : "↓ better"}</span></div>
        ${s.played ? `<div class="stats"><div class="stat"><b>${s.played}</b><span>played</span></div><div class="stat"><b>${fmtNum(s.avg, s.g)}</b><span>avg</span></div><div class="stat"><b>${s.streak}</b><span>streak</span></div></div>
        <dl class="kv">
          <dt>Best</dt><dd>${esc(s.best.sd)} <a class="muted small" href="#/day/${s.best.d}">${fmtDate(s.best.d)}</a></dd>
          <dt>Worst</dt><dd>${esc(s.worst.sd)} <a class="muted small" href="#/day/${s.worst.d}">${fmtDate(s.worst.d)}</a></dd>
          <dt>Fails</dt><dd>${s.fails}</dd>
        </dl>` : `<p class="muted small">Not played in this range.</p>`}
        ${s.missed.length ? `<details style="margin-top:8px"><summary>Missed ${s.missed.length} day${s.missed.length === 1 ? "" : "s"}</summary>
          <div class="chips" style="margin-top:6px">${s.missed.slice().reverse().map(x => `<a class="chip" href="#/day/${x}">${fmtDate(x)}</a>`).join("")}</div></details>`
          : `<p class="muted small" style="margin:8px 0 0">No missed days in range</p>`}
      </div>`).join("")}</div>
    <h2 style="margin-top:20px">Recent shares</h2>
    <div class="feed">${recent.map(r => `<div class="card"><div class="row small">${gLink(d.G.get(r.g))}<span class="spacer"></span><a class="muted" href="#/day/${r.d}">${fmtDate(r.d)}</a></div>
      ${r.raw ? `<pre class="share">${esc(r.raw)}</pre>` : `<b>${esc(r.sd)}</b>`}</div>`).join("")}</div>`;
  // On narrow screens the heatmap scrolls; start at the most recent weeks.
  const heat = app.querySelector(".heat");
  if (heat) heat.scrollLeft = heat.scrollWidth;
}

// ---------- router
function route() {
  if (!S.data) return;
  killCharts();
  const [, view = "", arg] = (location.hash.slice(1) || "/").split("/");
  const a = arg && decodeURIComponent(arg);
  if (view === "game" && a) { setNav("games"); viewGame(a); }
  else if (view === "games") { setNav("games"); viewGames(); }
  else if (view === "player" && a) { setNav("players"); viewPlayer(a); }
  else if (view === "players") { setNav("players"); viewPlayers(); }
  else { setNav(""); viewDay(view === "day" ? a : null); }
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
  document.title = S.data.title;
  document.getElementById("brand").textContent = S.data.title;
  document.getElementById("foot").textContent = `Updated ${new Date(S.data.generated_at).toLocaleString()} · ${S.data.results.length} results`;
  renderRange();
  window.addEventListener("hashchange", () => { route(); window.scrollTo(0, 0); });
  matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", route);
  route();
}
init();
})();
