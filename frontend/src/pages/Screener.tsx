import { useMemo, useState } from "react";
import { Badge, Loading, Panel, ScoreBar, Signed } from "../components/ui";
import { ago, num } from "../format";
import type { ScanRow } from "../types";

type Key = "symbol" | "price" | "change_pct" | "action" | "score" | "tech_score" | "fund_score" | "news_score" | "rsi";
const COLS: [Key, string, boolean][] = [
  ["symbol", "Symbol", false], ["price", "Price", true], ["change_pct", "Chg %", true], ["action", "Signal", false],
  ["score", "Score", true], ["tech_score", "Tech", true], ["fund_score", "Fund", true], ["news_score", "News", true], ["rsi", "RSI", true],
];

export default function Screener({ rows, at, loading, error, useLlm, setUseLlm, refresh, onOpen }: {
  rows: ScanRow[]; at: number | null; loading: boolean; error: string | null;
  useLlm: boolean; setUseLlm: (v: boolean) => void; refresh: () => void; onOpen: (s: string) => void;
}) {
  const [sort, setSort] = useState<{ k: Key; dir: 1 | -1 }>({ k: "score", dir: -1 });
  const sorted = useMemo(() => [...rows].sort((a, b) => (a[sort.k] > b[sort.k] ? 1 : a[sort.k] < b[sort.k] ? -1 : 0) * sort.dir), [rows, sort]);

  return (
    <>
      <div className="toolbar">
        <button className="primary" onClick={refresh} disabled={loading}>↻ Rescan</button>
        <label className="chk"><input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} /> use LLM for news sentiment</label>
        <span className="spacer" />
        {at && <span className="muted">updated {ago(new Date(at * 1000).toISOString())}</span>}
      </div>
      <Panel>
        {loading ? <Loading text="Scanning watchlist… (first run can take a minute)" /> : error ? <div className="empty neg">{error}</div> : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  {COLS.map(([k, label, n]) => (
                    <th key={k} className={n ? "num" : ""} onClick={() => setSort({ k, dir: sort.k === k ? (-sort.dir as 1 | -1) : -1 })}>
                      {label}{sort.k === k ? (sort.dir > 0 ? " ▲" : " ▼") : ""}
                    </th>
                  ))}
                  <th className="num">Entry</th><th className="num">Stop</th><th className="num">Target</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((r) => (
                  <tr key={r.symbol} className="click" onClick={() => onOpen(r.symbol)} title={r.headlines.join("\n")}>
                    <td><b>{r.symbol}</b></td><td className="num">{num(r.price)}</td><td className="num"><Signed v={r.change_pct} /></td>
                    <td><Badge value={r.action} /></td><td className="num"><ScoreBar v={r.score} /></td>
                    <td className="num"><Signed v={r.tech_score} /></td><td className="num"><Signed v={r.fund_score} /></td>
                    <td className="num" title={r.news_src}><Signed v={r.news_score} /></td><td className="num">{num(r.rsi, 0)}</td>
                    <td className="num">{num(r.plan?.entry)}</td><td className="num">{num(r.plan?.stop)}</td><td className="num">{num(r.plan?.target)}</td>
                  </tr>
                ))}
                {!sorted.length && <tr><td colSpan={12} className="empty">No data — check the server log (price source unreachable?)</td></tr>}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </>
  );
}
