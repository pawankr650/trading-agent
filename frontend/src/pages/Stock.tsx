import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { PriceChart } from "../components/Charts";
import { Badge, Loading, Panel, Signed } from "../components/ui";
import { ago, crore, num, pct, safeUrl } from "../format";
import type { Report } from "../types";

export default function Stock({ symbol, setSymbol, watchlist }: { symbol: string; setSymbol: (s: string) => void; watchlist: string[] }) {
  const [input, setInput] = useState(symbol);
  const [useLlm, setUseLlm] = useState(false);
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => { setInput(symbol); }, [symbol]);
  useEffect(() => {
    if (!symbol) return;
    let alive = true;
    setLoading(true); setError(null);
    api.analyze(symbol, useLlm)
      .then((r) => alive && setReport(r))
      .catch((e: Error) => alive && (setError(e.message), setReport(null)))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [symbol, useLlm]);

  const submit = (e: FormEvent) => { e.preventDefault(); if (input.trim()) setSymbol(input.trim().toUpperCase()); };
  const r = report, f = r?.fundamentals ?? {}, rv = r?.llm_review;

  return (
    <>
      <form className="toolbar" onSubmit={submit}>
        <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Symbol e.g. RELIANCE" list="wl" autoComplete="off" required />
        <datalist id="wl">{watchlist.map((s) => <option key={s} value={s} />)}</datalist>
        <label className="chk"><input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} /> AI review</label>
        <button className="primary">Analyze</button>
      </form>

      {!symbol ? <Panel><div className="empty">Type a symbol or click one anywhere in the app.</div></Panel>
        : loading ? <Loading text={`Analyzing ${symbol}…`} />
        : error ? <Panel><div className="empty neg">{error}</div></Panel>
        : r && (
          <>
            <Panel
              title={<span style={{ fontSize: 18 }}>{r.symbol} {f.longName && <span className="muted" style={{ fontWeight: 400 }}>{f.longName}</span>}</span>}
              extra={<div>₹<b>{num(r.price)}</b> (<Signed v={r.change_pct} suffix="%" />) → <Badge value={r.action} /> score <Signed v={r.score} /></div>}
            >
              <div className="muted">
                Tech <Signed v={r.tech_score} /> · Fund <Signed v={r.fund_score} /> · News <Signed v={r.news_score} /> ({r.news_src}) · RSI {num(r.rsi, 0)}
                {r.plan && <> · 🎯 Entry {num(r.plan.entry)} · SL {num(r.plan.stop)} · Target {num(r.plan.target)}</>}
              </div>
              <PriceChart candles={r.candles} plan={r.plan} />
            </Panel>
            <div className="grid3">
              <Panel title="Why (criteria)">
                <ul className="crit">{r.criteria.map((c, i) => <li key={i}>{c}</li>)}</ul>
                {rv && (
                  <>
                    <h2 style={{ marginTop: "1rem" }}>🤖 AI review</h2>
                    <div><Badge value={rv.action} /> {Math.round((rv.confidence || 0) * 100)}% — {rv.rationale}</div>
                  </>
                )}
                <h2 style={{ marginTop: "1rem" }}>News</h2>
                <ul className="list">
                  {r.news.length ? r.news.map((n, i) => (
                    <li key={i}>
                      <a target="_blank" rel="noopener noreferrer" href={safeUrl(n.link)}>{n.title}</a>
                      <div className="src">{n.source} {ago(n.published)}</div>
                    </li>
                  )) : <li className="muted">No recent news</li>}
                </ul>
              </Panel>
              <Panel title="Fundamentals">
                <div className="kv">
                  <div>Sector</div><div>{f.sector ?? "–"}</div>
                  <div>Market cap</div><div>{crore(f.marketCap)}</div>
                  <div>P/E</div><div>{num(f.trailingPE, 1)}</div>
                  <div>P/B</div><div>{num(f.priceToBook, 1)}</div>
                  <div>ROE</div><div>{pct(f.returnOnEquity)}</div>
                  <div>Debt/Equity</div><div>{f.debtToEquity != null ? `${num(f.debtToEquity / 100)}x` : "–"}</div>
                  <div>Revenue growth</div><div>{pct(f.revenueGrowth)}</div>
                  <div>Profit growth</div><div>{pct(f.earningsGrowth)}</div>
                  <div>Net margin</div><div>{pct(f.profitMargins)}</div>
                  <div>Dividend yield</div><div>{f.dividendYield != null ? `${num(f.dividendYield)}%` : "–"}</div>
                </div>
              </Panel>
            </div>
          </>
        )}
    </>
  );
}
