/* StockPilot terminal — vanilla JS + TradingView lightweight-charts (Apache-2.0). */
"use strict";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const LWC = window.LightweightCharts;
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const C = { up: css("--up"), down: css("--down"), accent: css("--accent"), info: css("--info"), muted: css("--muted"),
            line: css("--line"), text: css("--text-2"), bg: css("--bg"), warn: css("--warn") };

const S = { tab: "news", news: [], insights: {}, sel: null, wireF: "all", actF: "all", patterns: [], patSel: null,
            patName: "", strategies: [], charts: {}, bt: null, race: null, anim: 0 };

// ── helpers ────────────────────────────────────────────────
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const nf = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2, minimumFractionDigits: 2 });
const inr = v => v == null ? "—" : "₹" + nf.format(v);
const num = (v, d = 2) => v == null ? "—" : Number(v).toFixed(d);
const pct = (v, d = 2) => v == null ? "—" : (v > 0 ? "+" : "") + Number(v).toFixed(d) + "%";
const cls = v => v > 0 ? "up" : v < 0 ? "down" : "";
const ago = t => { const s = Date.now() / 1000 - t; return s < 60 ? "now" : s < 3600 ? `${Math.floor(s / 60)}m` : s < 86400 ? `${Math.floor(s / 3600)}h` : `${Math.floor(s / 86400)}d`; };
const biasOf = s => ({ positive: "bullish", negative: "bearish" }[s] || s);
// APP_TOKEN support: open the page once as /?token=… (remembered), or enter it when the server asks.
let TOKEN = null;
try { TOKEN = localStorage.getItem("sp.token"); } catch (e) { /* storage blocked */ }
const urlToken = new URLSearchParams(location.search).get("token");
if (urlToken) {
  TOKEN = urlToken;
  try { localStorage.setItem("sp.token", TOKEN); } catch (e) { /* storage blocked */ }
  history.replaceState(null, "", location.pathname);
}
async function api(path, body, retried) {
  const headers = { ...(body ? { "Content-Type": "application/json" } : {}), ...(TOKEN ? { "X-App-Token": TOKEN } : {}) };
  const r = await fetch(path, body ? { method: "POST", headers, body: JSON.stringify(body) } : { headers });
  if (r.status === 401 && !retried) {
    const t = prompt("This StockPilot server is protected. Enter its APP_TOKEN:");
    if (t) {
      TOKEN = t.trim();
      try { localStorage.setItem("sp.token", TOKEN); } catch (e) { /* storage blocked */ }
      return api(path, body, true);
    }
  }
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}
function toast(msg) { const t = $("#toast"); t.textContent = msg; t.classList.add("show"); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("show"), 2600); }

function chart(el, opts = {}) {
  if (S.charts[el.id]) { S.charts[el.id].remove(); }
  const c = LWC.createChart(el, {
    autoSize: true,
    layout: { background: { type: "solid", color: "transparent" }, textColor: C.muted, fontFamily: "JetBrains Mono", fontSize: 11 },
    grid: { vertLines: { color: "rgba(255,255,255,.03)" }, horzLines: { color: "rgba(255,255,255,.04)" } },
    rightPriceScale: { borderColor: C.line }, timeScale: { borderColor: C.line, rightOffset: 4 },
    crosshair: { mode: 0 }, localization: { locale: "en-IN" }, ...opts });
  S.charts[el.id] = c;
  return c;
}
const candleOpts = { upColor: C.up, downColor: C.down, borderVisible: false, wickUpColor: C.up, wickDownColor: C.down };

function spark(vals, w = 100, h = 28) {
  if (!vals?.length) return "";
  const mn = Math.min(...vals), mx = Math.max(...vals), k = (mx - mn) || 1;
  const pts = vals.map((v, i) => `${(i / (vals.length - 1) * w).toFixed(1)},${(h - 2 - (v - mn) / k * (h - 4)).toFixed(1)}`).join(" ");
  const col = vals.at(-1) >= vals[0] ? C.up : C.down;
  return `<svg class="spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true"><polyline points="${pts}" fill="none" stroke="${col}" stroke-width="1.5" stroke-linejoin="round"/></svg>`;
}

// ── tabs ───────────────────────────────────────────────────
$$(".tabs button").forEach(b => b.onclick = () => setTab(b.dataset.tab));
function setTab(t) {
  S.tab = t;
  $$(".tabs button").forEach(b => b.setAttribute("aria-selected", b.dataset.tab === t));
  $$(".desk").forEach(d => d.hidden = d.id !== "desk-" + t);
  if (t === "patterns" && !S.patterns.length) loadPatterns();
  if (t === "algo" && !S.strategies.length) initAlgo();
  try { localStorage.setItem("sp.tab", t); } catch (e) { /* storage blocked */ }
}

// ── status + tape ──────────────────────────────────────────
async function loadStatus() {
  try {
    const s = await api("/api/terminal/status");
    $("#demoBadge").hidden = !s.demo;
    $("#mkt").innerHTML = `<i class="dot ${s.market_open ? "on" : ""}"></i><span>${s.market_open ? "Market open" : "Market closed"} · ${esc(s.ist)} IST</span>`;
    const e = s.engine;
    $("#pipe").innerHTML = `<i class="dot live"></i><span>${e.last_poll ? "news " + ago(e.last_poll) + " ago" : "starting…"} · every ${e.poll_seconds}s</span>`;
    $("#modelFoot").textContent = `sentiment: ${e.model} · events: ${e.backend === "keyword" ? "keyword rules" : e.event_model}${e.llm_thesis ? " · LLM thesis on" : ""}`;
    $("#patEngine").textContent = `candles: ${s.pattern_engine} · charts: pivot geometry`;
  } catch (e) { $("#pipe").innerHTML = `<i class="dot"></i><span>server offline</span>`; }
}
function renderTape(rows) {
  if (!rows?.length) return;
  const one = rows.map(r => `<span><b>${esc(r.symbol)}</b>${nf.format(r.price)} <em class="${cls(r.change_pct)}" style="font-style:normal">${pct(r.change_pct)}</em></span>`).join("");
  $("#tape").innerHTML = one + one;
}

// ═════════════ DESK 1: NEWS ═════════════
function newsItem(n, fresh) {
  const b = biasOf(n.nlp.sentiment), col = b === "bullish" ? C.up : b === "bearish" ? C.down : C.muted;
  const title = n.link ? `<a href="${esc(n.link)}" target="_blank" rel="noopener">${esc(n.title)}</a>` : `<span class="t">${esc(n.title)}</span>`;
  return `<article class="news${fresh ? " fresh" : ""}" data-id="${n.id}">
    <div class="meta"><span>${ago(n.ts)}</span><span class="src">${esc(n.source)}</span>${n.demo ? '<span class="tag ev">sample</span>' : ""}</div>
    ${title}
    <div class="row">
      <span class="tag ${b}">${esc(n.nlp.sentiment.toUpperCase())}</span>
      <span class="conf" title="model confidence ${Math.round(n.nlp.confidence * 100)}%"><i style="width:${n.nlp.confidence * 100}%;background:${col}"></i></span>
      <span class="tag ev">${esc(n.nlp.event)}</span>
      ${n.symbols.map(s => `<button class="tag sym" data-sym="${esc(s)}">${esc(s)}</button>`).join("")}
    </div></article>`;
}
function wireFilter(n) {
  return S.wireF === "all" || (S.wireF === "tagged" ? n.symbols.length : n.nlp.sentiment === S.wireF);
}
function renderWire() {
  const list = S.news.filter(wireFilter);
  $("#wire").innerHTML = list.length ? list.slice(0, 150).map(n => newsItem(n)).join("") : `<div class="empty">No headlines match this filter yet.</div>`;
  $("#wireCount").textContent = `${S.news.length} headlines`;
}
$("#wireFilter").onclick = e => {
  const b = e.target.closest(".chip"); if (!b) return;
  S.wireF = b.dataset.f; $$("#wireFilter .chip").forEach(c => c.classList.toggle("on", c === b)); renderWire();
};
$("#wire").onclick = e => { const b = e.target.closest(".sym"); if (b) selectStock(b.dataset.sym); };

function ladder(p) {
  const pts = [p.stop, p.entry_zone[0], p.entry_zone[1], p.target1, p.target2];
  const lo = Math.min(...pts), hi = Math.max(...pts), k = (hi - lo) || 1, x = v => ((v - lo) / k * 92 + 4).toFixed(1) + "%";
  const long = p.side === "long";
  const [rA, rB] = long ? [p.stop, p.entry] : [p.entry, p.stop];
  const [wA, wB] = long ? [p.entry, p.target2] : [p.target2, p.entry];
  return `<div class="ladder" aria-label="stop ${p.stop}, entry ${p.entry}, target ${p.target1}">
    <div class="rail"></div>
    <div class="risk" style="left:${x(rA)};width:calc(${x(rB)} - ${x(rA)})"></div>
    <div class="rew" style="left:${x(wA)};width:calc(${x(wB)} - ${x(wA)})"></div>
    <div class="zone" style="left:${x(p.entry_zone[0])};width:max(4px,calc(${x(p.entry_zone[1])} - ${x(p.entry_zone[0])}))"></div>
    <span class="lt down" style="left:${x(p.stop)}">SL</span><span class="lt" style="left:${x(p.entry)};color:var(--text)">ENTRY</span><span class="lt up" style="left:${x(p.target1)}">T1</span>
    <span class="lb" style="left:${x(p.stop)}">${nf.format(p.stop)}</span><span class="lb" style="left:${x(p.target1)}">${nf.format(p.target1)}</span>
  </div>`;
}
function scoreBar(k, v) {
  const w = Math.abs(v) * 50, col = v >= 0 ? C.up : C.down, left = v >= 0 ? 50 : 50 - w;
  return `<div class="sc"><div class="k"><span>${k}</span><span class="mono ${cls(v)}">${v > 0 ? "+" : ""}${num(v)}</span></div><div class="bar"><i style="left:${left}%;width:${w}%;background:${col}"></i></div></div>`;
}
function card(i) {
  const why = i.reasons.filter(r => r.bias !== "neutral").slice(0, 3);
  return `<button class="card${S.sel === i.symbol ? " sel" : ""}" data-sym="${i.symbol}" id="card-${i.symbol}">
    <div class="hd">
      <div><div class="sym">${esc(i.symbol)}</div><div class="nm">${esc(i.name)}</div></div>
      <span class="tag ${i.action}">${i.action}</span>
      <div class="px"><b>${nf.format(i.price)}</b><small class="${cls(i.change_pct)}">${pct(i.change_pct)}</small></div>
    </div>
    ${ladder(i.plan)}
    <div class="scores">${scoreBar("Tech", i.scores.technical)}${scoreBar("News", i.scores.news)}${scoreBar("Pattern", i.scores.pattern)}</div>
    <div class="why">${why.map(r => `<div><i class="mk ${r.bias}"></i><span>${esc(r.text)}</span></div>`).join("") || '<div><span class="sub">No strong drivers</span></div>'}</div>
  </button>`;
}
function filteredInsights() {
  const all = Object.values(S.insights);
  const ord = { BUY: 0, SELL: 1, WATCH: 2, AVOID: 3, HOLD: 4 };
  return all.filter(i => S.actF === "all" || (S.actF === "news" ? i.news_count > 0 : i.action === S.actF))
            .sort((a, b) => ord[a.action] - ord[b.action] || b.news_count - a.news_count || Math.abs(b.score) - Math.abs(a.score));
}
function renderKpis() {
  const all = Object.values(S.insights), c = a => all.filter(i => i.action === a).length;
  const withNews = all.filter(i => i.news_count);
  const avg = withNews.length ? withNews.reduce((s, i) => s + i.scores.news, 0) / withNews.length : 0;
  const tagged = S.news.filter(n => n.symbols.length).length;
  $("#kpis").innerHTML = [
    ["Buy setups", c("BUY"), "tech + news aligned", "up"], ["Sell setups", c("SELL"), "short / exit candidates", "down"],
    ["On watch", c("WATCH"), "needs confirmation", ""], ["News sentiment", (avg > 0 ? "+" : "") + avg.toFixed(2), `${withNews.length} stocks in the news`, cls(avg)],
    ["Headlines", S.news.length, `${tagged} tagged to NIFTY 50`, ""],
  ].map(([l, v, s, k]) => `<div class="kpi"><div class="l">${l}</div><div class="v ${k}">${v}</div><div class="s">${s}</div></div>`).join("");
}
function renderCards() {
  const list = filteredInsights();
  $("#cards").innerHTML = list.length ? list.map(card).join("") : `<div class="empty">${Object.keys(S.insights).length ? "Nothing in this bucket right now." : '<span class="spin"></span> Building insights for NIFTY 50…'}</div>`;
  renderKpis();
}
$("#actFilter").onclick = e => {
  const b = e.target.closest("button"); if (!b) return;
  S.actF = b.dataset.a; $$("#actFilter button").forEach(x => x.classList.toggle("on", x === b)); renderCards();
};
$("#cards").onclick = e => { const c = e.target.closest(".card"); if (c) selectStock(c.dataset.sym); };

async function selectStock(sym) {
  S.sel = sym;
  if (S.tab !== "news") setTab("news");
  $$(".card").forEach(c => c.classList.toggle("sel", c.dataset.sym === sym));
  const el = $("#detail");
  el.innerHTML = `<div class="empty tall"><span class="spin"></span> Loading ${esc(sym)}…</div>`;
  let d;
  try { d = await api("/api/terminal/stock/" + encodeURIComponent(sym)); } catch (e) { el.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  if (S.sel !== sym) return;
  const i = d.insight || {};
  const p = i.plan;
  const groups = { news: "News drivers", technical: "Technical criteria", pattern: "Patterns" };
  el.innerHTML = `
    <div class="dh"><div><div class="sym">${esc(d.symbol)} <span class="tag ${i.action || "HOLD"}" style="vertical-align:3px">${i.action || "—"}</span></div>
      <div class="nm">${esc(d.name)} · ${esc(d.sector)}</div></div>
      <div class="px"><b>${inr(i.price)}</b><span class="${cls(i.change_pct)}">${pct(i.change_pct)}</span></div></div>
    <div class="chart" id="dChart" style="height:280px"></div>
    ${p ? `<div class="plan">
      <div><div class="l">${p.side === "long" ? "Buy zone" : "Sell zone"}</div><div class="v">${nf.format(p.entry_zone[0])}<br>– ${nf.format(p.entry_zone[1])}</div></div>
      <div><div class="l">Stop-loss</div><div class="v down">${nf.format(p.stop)}</div></div>
      <div><div class="l">Target 1</div><div class="v up">${nf.format(p.target1)}</div></div>
      <div><div class="l">Target 2</div><div class="v up">${nf.format(p.target2)}</div></div>
      <div><div class="l">Risk</div><div class="v">${p.risk_pct}%</div></div>
      <div><div class="l">Reward (T1)</div><div class="v">${p.reward_pct}%</div></div>
      <div><div class="l">R : R</div><div class="v">1 : ${p.rr}</div></div>
      <div><div class="l">Confidence</div><div class="v">${Math.round(i.confidence * 100)}%</div></div>
    </div>` : ""}
    ${i.thesis ? `<div class="section"><h3>AI thesis</h3><div class="thesis">${esc(i.thesis)}</div></div>` : ""}
    ${Object.entries(groups).map(([k, label]) => {
      const rs = (i.reasons || []).filter(r => r.kind === k);
      if (!rs.length) return "";
      return `<div class="section"><h3>${label} <span class="sub">${rs.length}</span></h3><div class="reasons">${rs.map(r => `
        <div class="reason"><i class="mk ${r.bias}"></i>${r.link ? `<a href="${esc(r.link)}" target="_blank" rel="noopener">${esc(r.text)}</a>` : `<span>${esc(r.text)}</span>`}
        ${r.event ? `<span class="tag ev">${esc(r.event)}</span>` : ""}</div>`).join("")}</div></div>`;
    }).join("")}
    <div class="section"><h3>Key levels</h3><div class="levels">
      <span>Support ${(d.patterns.levels.support || []).map(v => `<b class="up">${nf.format(v)}</b>`).join(" · ") || "—"}</span>
      <span>Resistance ${(d.patterns.levels.resistance || []).map(v => `<b class="down">${nf.format(v)}</b>`).join(" · ") || "—"}</span>
      <span>RSI <b>${i.rsi ?? "—"}</b></span><span>ATR <b>${i.atr ?? "—"}</b></span></div></div>
    <div class="section"><p class="fine" style="padding:0">Signals are generated automatically from headlines, indicators and patterns. They are not investment advice.</p></div>`;
  const c = chart($("#dChart"));
  const cs = c.addCandlestickSeries(candleOpts); cs.setData(d.candles);
  c.addLineSeries({ color: C.info, lineWidth: 1, priceLineVisible: false, lastValueVisible: false }).setData(d.sma20);
  c.addLineSeries({ color: C.warn, lineWidth: 1, priceLineVisible: false, lastValueVisible: false }).setData(d.sma50);
  if (p) {
    [[p.entry, C.text, "ENTRY", 0], [p.stop, C.down, "SL", 2], [p.target1, C.up, "T1", 2], [p.target2, C.up, "T2", 1]]
      .forEach(([price, color, title, style]) => cs.createPriceLine({ price, color, title, lineWidth: 1, lineStyle: style, axisLabelVisible: true }));
  }
  c.timeScale().setVisibleLogicalRange({ from: d.candles.length - 120, to: d.candles.length + 4 });
}

function onNews(n) {
  if (S.news.some(x => x.id === n.id)) return;
  S.news.unshift(n);
  if (S.news.length > 600) S.news.pop();
  if (wireFilter(n)) {
    $("#wire .empty")?.remove();
    $("#wire").insertAdjacentHTML("afterbegin", newsItem(n, true));
  }
  $("#wireCount").textContent = `${S.news.length} headlines`;
}
function onInsight(i) {
  const prev = S.insights[i.symbol];
  S.insights[i.symbol] = i;
  renderCards();
  const el = $("#card-" + CSS.escape(i.symbol));
  if (el && (!prev || prev.action !== i.action || prev.news_count !== i.news_count)) el.classList.add("pop");
  if (prev && prev.action !== i.action && ["BUY", "SELL"].includes(i.action)) toast(`${i.symbol} → ${i.action}`);
  if (S.sel === i.symbol) selectStock(i.symbol);
}
function connectStream() {
  const es = new EventSource("/api/terminal/stream" + (TOKEN ? "?token=" + encodeURIComponent(TOKEN) : ""));
  es.addEventListener("news", e => onNews(JSON.parse(e.data)));
  es.addEventListener("insight", e => onInsight(JSON.parse(e.data)));
  es.onerror = () => { es.close(); setTimeout(connectStream, 5000); };
}
async function loadNewsDesk() {
  const [news, ins] = await Promise.all([api("/api/terminal/news?limit=300"), api("/api/terminal/insights")]);
  S.news = news; S.insights = Object.fromEntries(ins.map(i => [i.symbol, i]));
  renderWire(); renderCards();
  if (!ins.length) setTimeout(loadNewsDesk, 4000);
}

// ═════════════ DESK 2: PATTERNS ═════════════
async function loadPatterns(refresh = false) {
  $("#patRows").innerHTML = `<div class="empty"><span class="spin"></span> Scanning 50 stocks…</div>`;
  applyPatterns(await api("/api/terminal/patterns" + (refresh ? "?refresh=true" : "")));
}
function applyPatterns(d) {
  S.patterns = d.rows;
  renderTape(d.rows);
  const secs = [...new Set(d.rows.map(r => r.sector))].sort();
  $("#patSector").innerHTML = `<option value="">All sectors</option>` + secs.map(s => `<option>${esc(s)}</option>`).join("");
  renderPatterns();
}
function patNames(r) { return [...r.chart.map(p => p.name), ...r.candles.map(p => p.name)]; }
function renderPatterns() {
  const q = $("#patSearch").value.trim().toLowerCase(), bias = $("#patBias").value, sec = $("#patSector").value;
  const counts = {};
  S.patterns.forEach(r => new Set(patNames(r)).forEach(n => counts[n] = (counts[n] || 0) + 1));
  const top = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 18);
  $("#patChips").innerHTML = `<button class="chip ${S.patName ? "" : "on"}" data-n="">All patterns</button>` +
    top.map(([n, c]) => `<button class="chip ${S.patName === n ? "on" : ""}" data-n="${esc(n)}">${esc(n)}<span class="n">${c}</span></button>`).join("");
  const rows = S.patterns.filter(r => (!q || r.symbol.toLowerCase().includes(q) || r.name.toLowerCase().includes(q)) &&
    (!bias || r.bias === bias) && (!sec || r.sector === sec) && (!S.patName || patNames(r).includes(S.patName)));
  $("#patRows").innerHTML = rows.length ? rows.map(r => `
    <button class="prow${S.patSel === r.symbol ? " sel" : ""}" role="row" data-sym="${r.symbol}">
      <span class="s"><b>${esc(r.symbol)}</b><small>${esc(r.name)}</small></span>
      <span>${spark(r.spark)}</span>
      <span class="px">${nf.format(r.price)}<small class="${cls(r.change_pct)}">${pct(r.change_pct)}</small></span>
      <span><span class="tag ${r.bias}">${r.bias.toUpperCase()}</span></span>
      <span class="pp">${r.chart.map(p => `<span class="tag ${p.bias}">${esc(p.name)}${p.status && p.status !== "forming" ? " · " + esc(p.status) : ""}</span>`).join("")}
        ${r.candles.slice(0, 3).map(p => `<span class="tag ev" title="${esc(p.date)}">${esc(p.name)}</span>`).join("")}
        ${!r.chart.length && !r.candles.length ? '<span class="sub">no fresh pattern</span>' : ""}</span>
    </button>`).join("") : `<div class="empty">No stock matches these filters.</div>`;
}
$("#patChips").onclick = e => { const b = e.target.closest(".chip"); if (!b) return; S.patName = b.dataset.n; renderPatterns(); };
["#patSearch", "#patBias", "#patSector"].forEach(id => $(id).addEventListener("input", renderPatterns));
$("#patRefresh").onclick = () => loadPatterns(true);
$("#patRows").onclick = e => { const r = e.target.closest(".prow"); if (r) selectPattern(r.dataset.sym); };

async function selectPattern(sym) {
  S.patSel = sym;
  $$(".prow").forEach(r => r.classList.toggle("sel", r.dataset.sym === sym));
  const el = $("#patDetail");
  el.innerHTML = `<div class="empty tall"><span class="spin"></span></div>`;
  const d = await api("/api/terminal/stock/" + encodeURIComponent(sym) + "?bars=180");
  const P = d.patterns, first = d.candles[0].time;
  const charts = P.chart.filter(p => !p.points.length || p.points.at(-1).time >= first);
  const candles = P.candlestick.filter(p => p.time >= first);
  el.innerHTML = `
    <div class="dh"><div><div class="sym">${esc(d.symbol)} <span class="tag ${P.bias}" style="vertical-align:3px">${P.bias.toUpperCase()}</span></div>
      <div class="nm">${esc(d.name)} · ${esc(d.sector)} · ${P.bullish} bullish / ${P.bearish} bearish recent signals</div></div>
      <div class="px"><b>${inr(d.candles.at(-1).close)}</b></div></div>
    <div class="chart" id="pChart" style="height:360px"></div>
    <div class="section"><h3>Chart patterns <span class="sub">${charts.length}</span></h3><div class="plist">${charts.map(p => `
      <div class="pitem"><span class="glyph ${p.bias}">${p.bias === "bullish" ? "↑" : p.bias === "bearish" ? "↓" : "↔"}</span>
        <div><div class="n">${esc(p.name)}</div><div class="d">${esc(p.description)}</div></div><span class="st">${esc(p.status)}</span></div>`).join("") || '<span class="sub">None detected in this window.</span>'}</div></div>
    <div class="section"><h3>Candlestick patterns <span class="sub">last 60 sessions · ${esc(P.engine)}</span></h3><div class="plist">${candles.slice().reverse().slice(0, 14).map(p => `
      <div class="pitem"><span class="glyph ${p.bias}">${p.bias === "bullish" ? "↑" : p.bias === "bearish" ? "↓" : "•"}</span>
        <div><div class="n">${esc(p.name)}</div><div class="d">${esc(p.date)} · ${p.bars_ago === 0 ? "today" : p.bars_ago + " bars ago"}</div></div><span class="st">${p.bias}</span></div>`).join("") || '<span class="sub">None.</span>'}</div></div>
    <div class="section"><h3>Support / resistance</h3><div class="levels">
      <span>S ${(P.levels.support || []).map(v => `<b class="up">${nf.format(v)}</b>`).join(" · ") || "—"}</span>
      <span>R ${(P.levels.resistance || []).map(v => `<b class="down">${nf.format(v)}</b>`).join(" · ") || "—"}</span></div></div>`;
  const c = chart($("#pChart"));
  const cs = c.addCandlestickSeries(candleOpts); cs.setData(d.candles);
  c.addLineSeries({ color: "rgba(110,168,254,.55)", lineWidth: 1, priceLineVisible: false, lastValueVisible: false }).setData(d.sma50);
  charts.forEach(p => {
    const col = p.bias === "bullish" ? C.up : p.bias === "bearish" ? C.down : C.warn;
    p.lines.forEach(seg => {
      const pts = seg.filter(x => x.time >= first).sort((a, b) => a.time - b.time);
      if (pts.length === 2 && pts[0].time !== pts[1].time)
        c.addLineSeries({ color: col, lineWidth: 2, lineStyle: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false })
         .setData(pts.map(x => ({ time: x.time, value: x.price })));
    });
    if (["Double Top", "Double Bottom", "Head & Shoulders", "Inverse Head & Shoulders"].includes(p.name)) {
      const pts = p.points.filter(x => x.time >= first);
      if (pts.length > 1) c.addLineSeries({ color: col, lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false })
        .setData(pts.map(x => ({ time: x.time, value: x.price })));
    }
  });
  (P.levels.support || []).slice(0, 2).forEach(v => cs.createPriceLine({ price: v, color: "rgba(46,194,126,.5)", lineWidth: 1, lineStyle: 1, title: "S" }));
  (P.levels.resistance || []).slice(0, 2).forEach(v => cs.createPriceLine({ price: v, color: "rgba(242,92,105,.5)", lineWidth: 1, lineStyle: 1, title: "R" }));
  const short = n => n.split(" ").map(w => w[0]).join("").slice(0, 3).toUpperCase();
  // one marker per bar (strongest directional pattern wins), labels only on the latest few
  const perBar = new Map();
  candles.forEach(p => { const q = perBar.get(p.time); if (!q || (q.bias === "neutral" && p.bias !== "neutral") || p.strength > q.strength) perBar.set(p.time, p); });
  const ms = [...perBar.values()].sort((a, b) => a.time - b.time);
  cs.setMarkers(ms.map((p, k) => ({ time: p.time, position: p.bias === "bearish" ? "aboveBar" : "belowBar",
    color: p.bias === "bullish" ? C.up : p.bias === "bearish" ? C.down : C.muted,
    shape: p.bias === "bullish" ? "arrowUp" : p.bias === "bearish" ? "arrowDown" : "circle", text: k >= ms.length - 6 ? short(p.name) : "" })));
  c.timeScale().fitContent();
}

// ═════════════ DESK 3: ALGO LAB ═════════════
async function initAlgo() {
  S.strategies = await api("/api/terminal/strategies");
  if (!S.patterns.length) applyPatterns(await api("/api/terminal/patterns"));
  const syms = S.patterns;
  $("#btSym").innerHTML = syms.map(r => `<option value="${r.symbol}">${r.symbol} · ${esc(r.name)}</option>`).join("");
  $("#btSym").value = syms.find(r => r.symbol === "RELIANCE") ? "RELIANCE" : syms[0].symbol;
  $("#btStrat").innerHTML = S.strategies.map(s => `<option value="${s.id}">${esc(s.label)}</option>`).join("");
  $("#btStrat").value = "ema_atr";
  renderParams();
  runBacktest();
}
function renderParams(values) {
  const s = S.strategies.find(x => x.id === $("#btStrat").value);
  $("#btDoc").textContent = `${s.family} · ${s.doc}`;
  const v = values || s.params;
  $("#btParams").innerHTML = Object.keys(s.params).map(k => `<label class="field"><span>${esc(k.replace("_", " "))}</span>
    <input type="number" step="any" data-p="${k}" value="${v[k]}"></label>`).join("");
}
$("#btStrat").onchange = () => renderParams();
$("#btForm").onsubmit = e => { e.preventDefault(); runBacktest(); };
$("#btRace").onclick = runRace;

function req() {
  const params = {};
  $$("#btParams input").forEach(i => { if (i.value !== "") params[i.dataset.p] = Number(i.value); });
  return { symbol: $("#btSym").value, strategy: $("#btStrat").value, years: Number($("#btYears").value),
           cash: Number($("#btCash").value), commission: Number($("#btComm").value) / 100, params, optimize: $("#btOpt").checked };
}
async function runBacktest() {
  const b = $("#btRun"); b.disabled = true; b.innerHTML = '<span class="spin"></span> Simulating…';
  try {
    const r = await api("/api/terminal/backtest", req());
    S.bt = r;
    if (r.optimized) { renderParams(r.params); toast("Auto-tuned: " + Object.entries(r.params).map(([k, v]) => `${k}=${v}`).join(", ")); }
    playBacktest(r);
  } catch (e) { toast("Backtest failed: " + e.message); }
  finally { b.disabled = false; b.textContent = "Run simulation"; }
}
function btKpis(st, oos) {
  const alpha = st.return_pct != null && st.buy_hold_pct != null ? st.return_pct - st.buy_hold_pct : null;
  $("#btKpis").innerHTML = [
    ["Total return", pct(st.return_pct), `buy & hold ${pct(st.buy_hold_pct)}`, cls(st.return_pct)],
    ["vs buy & hold", pct(alpha), "excess return", cls(alpha)],
    ["CAGR", pct(st.cagr_pct), `vol ${num(st.vol_pct, 1)}%`, cls(st.cagr_pct)],
    ["Sharpe", num(st.sharpe), `Sortino ${num(st.sortino)}`, ""],
    ["Max drawdown", pct(st.max_dd_pct), `Calmar ${num(st.calmar)}`, "down"],
    ["Win rate", st.win_rate == null ? "—" : num(st.win_rate, 1) + "%", `${st.trades ?? 0} trades · PF ${num(st.profit_factor)}`, ""],
    ["Final equity", st.final_equity == null ? "—" : "₹" + Math.round(st.final_equity).toLocaleString("en-IN"), `exposure ${num(st.exposure_pct, 0)}%`, ""],
  ].map(([l, v, s, k]) => `<div class="kpi"><div class="l">${l}</div><div class="v ${k}">${v}</div><div class="s">${s}</div></div>`).join("") +
  (oos ? `<div class="kpi" style="grid-column:1/-1"><div class="l">Out-of-sample check (last 30%, unseen by the tuner)</div>
     <div class="s" style="font-size:13px;color:var(--text-2)">Return <b class="${cls(oos.stats.return_pct)}">${pct(oos.stats.return_pct)}</b> vs buy &amp; hold ${pct(oos.stats.buy_hold_pct)} · Sharpe ${num(oos.stats.sharpe)} · Max DD ${pct(oos.stats.max_dd_pct)} · ${oos.stats.trades ?? 0} trades</div></div>` : "");
}
function tradeLog(trades) {
  $("#tradeSub").textContent = `${trades.length} trades`;
  const d = t => new Date(t * 1000).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "2-digit" });
  $("#trades").innerHTML = trades.length ? `<table><thead><tr><th>Entry</th><th>Exit</th><th class="r">Buy</th><th class="r">Sell</th><th class="r">Qty</th><th class="r">P&amp;L</th><th class="r">Ret</th></tr></thead><tbody>
    ${trades.slice().reverse().map(t => `<tr><td>${d(t.entry_time)}</td><td>${d(t.exit_time)}</td><td class="r">${nf.format(t.entry)}</td><td class="r">${nf.format(t.exit)}</td>
      <td class="r">${t.size}</td><td class="r ${cls(t.pnl)}">${Math.round(t.pnl).toLocaleString("en-IN")}</td><td class="r ${cls(t.ret_pct)}">${pct(t.ret_pct, 1)}</td></tr>`).join("")}</tbody></table>`
    : `<div class="empty">No trades were triggered in this window.</div>`;
}
function playBacktest(r) {
  cancelAnimationFrame(S.anim);
  $("#btTitle").textContent = `${r.symbol} · ${r.label}`;
  btKpis(r.stats, r.out_of_sample);
  tradeLog(r.trades);
  const pc = chart($("#btPrice")), ec = chart($("#btEquity"));
  const cs = pc.addCandlestickSeries(candleOpts);
  const eq = ec.addAreaSeries({ lineColor: C.accent, topColor: "rgba(245,176,65,.25)", bottomColor: "rgba(245,176,65,0)", lineWidth: 2, priceLineVisible: false });
  const bh = ec.addLineSeries({ color: C.muted, lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false });
  const dd = ec.addHistogramSeries({ color: "rgba(242,92,105,.28)", priceScaleId: "dd", priceLineVisible: false, lastValueVisible: false });
  ec.priceScale("dd").applyOptions({ scaleMargins: { top: 0.78, bottom: 0 }, visible: false });
  const marks = r.trades.flatMap(t => [
    { time: t.entry_time, position: "belowBar", color: C.up, shape: "arrowUp", text: "B" },
    { time: t.exit_time, position: "aboveBar", color: t.pnl >= 0 ? C.up : C.down, shape: "arrowDown", text: (t.ret_pct > 0 ? "+" : "") + t.ret_pct.toFixed(1) + "%" },
  ]).sort((a, b) => a.time - b.time);
  const N = r.candles.length, speed = Number($("#btSpeed").value);
  const draw = n => {
    const tEnd = r.candles[n - 1].time;
    cs.setData(r.candles.slice(0, n));
    cs.setMarkers(marks.filter(m => m.time <= tEnd));
    eq.setData(r.equity.slice(0, n)); bh.setData(r.buy_hold.slice(0, n)); dd.setData(r.drawdown.slice(0, n));
    const last = r.equity[n - 1].value;
    $("#btClock").innerHTML = `${new Date(tEnd * 1000).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" })} · equity <b class="${cls(last - r.cash)}">₹${Math.round(last).toLocaleString("en-IN")}</b>`;
  };
  if (!speed) { draw(N); pc.timeScale().fitContent(); ec.timeScale().fitContent(); return; }
  let n = Math.min(40, N);
  const step = () => {
    n = Math.min(N, n + speed);
    draw(n);
    pc.timeScale().fitContent(); ec.timeScale().fitContent();
    if (n < N) S.anim = requestAnimationFrame(step);
  };
  S.anim = requestAnimationFrame(step);
}
async function runRace() {
  const b = $("#btRace"); b.disabled = true; b.innerHTML = '<span class="spin"></span> Racing 7 strategies…';
  try {
    const rows = await api("/api/terminal/compare", req());
    const best = rows.find(r => !r.error);
    $("#raceSub").textContent = `${$("#btSym").value} · ranked by Sharpe`;
    $("#race").innerHTML = `<table><thead><tr><th>Strategy</th><th class="r">Return</th><th class="r">Sharpe</th><th class="r">Max DD</th><th class="r">Win</th><th class="r">Trades</th><th></th></tr></thead><tbody>
      ${rows.map(r => `<tr class="${r === best ? "best" : ""}"><td class="t">${esc(r.label)}${r === best ? ' <span class="tag WATCH">BEST</span>' : ""}<br><span class="sub">${esc(r.family)}</span></td>
        ${r.error ? `<td colspan="5" class="t sub">${esc(r.error)}</td>` : `<td class="r ${cls(r.return_pct)}">${pct(r.return_pct, 1)}</td><td class="r">${num(r.sharpe)}</td><td class="r down">${pct(r.max_dd_pct, 1)}</td>
        <td class="r">${r.win_rate == null ? "—" : num(r.win_rate, 0) + "%"}</td><td class="r">${r.trades ?? 0}</td>`}
        <td class="r"><button class="use" data-id="${r.id}">Simulate</button></td></tr>`).join("")}</tbody></table>`;
  } catch (e) { toast("Race failed: " + e.message); }
  finally { b.disabled = false; b.textContent = "Race all strategies"; }
}
$("#race").onclick = e => {
  const u = e.target.closest(".use"); if (!u) return;
  $("#btStrat").value = u.dataset.id; renderParams(); runBacktest();
};

// ── boot ───────────────────────────────────────────────────
(async function boot() {
  loadStatus(); setInterval(loadStatus, 20000);
  connectStream();
  loadNewsDesk().catch(e => toast(e.message));
  api("/api/terminal/patterns").then(applyPatterns).catch(() => {});
  setInterval(() => $$("#wire .news .meta span:first-child").forEach((s, i) => { const n = S.news.filter(wireFilter)[i]; if (n) s.textContent = ago(n.ts); }), 30000);
  let t = "news"; try { t = localStorage.getItem("sp.tab") || "news"; } catch (e) { /* storage blocked */ }
  setTab(t);
})();
