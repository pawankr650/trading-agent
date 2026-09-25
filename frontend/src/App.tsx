import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import PickCard from "./components/PickCard";
import { Badge, Empty, Kpi, Panel, Signed, useAsync } from "./components/ui";
import { num } from "./format";
import AiNews from "./pages/AiNews";
import Headlines from "./pages/Headlines";
import Screener from "./pages/Screener";
import Settings from "./pages/Settings";
import Stock from "./pages/Stock";
import Trader from "./pages/Trader";
import type { Digest, ScanRow } from "./types";

const TABS = [
  ["home", "Overview"], ["ainews", "AI News"], ["screener", "Screener"], ["stock", "Stock"],
  ["news", "Headlines & Filings"], ["trader", "Auto-trader"], ["settings", "Settings"],
] as const;
type Tab = (typeof TABS)[number][0];
const isTab = (s: string): s is Tab => TABS.some(([t]) => t === s);

function useHashTab(): [Tab, (t: Tab) => void] {
  const read = () => { const h = location.hash.slice(1); return isTab(h) ? h : "home"; };
  const [tab, setTab] = useState<Tab>(read);
  useEffect(() => {
    const on = () => setTab(read());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  const go = useCallback((t: Tab) => { history.replaceState(null, "", `#${t}`); setTab(t); window.scrollTo(0, 0); }, []);
  return [tab, go];
}

export default function App() {
  const [tab, go] = useHashTab();
  const health = useAsync(() => api.health());
  const digest = useAsync(() => api.digest());
  const [useLlm, setUseLlm] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const scan = useAsync(() => api.scan(useLlm, refreshKey > 0), [useLlm, refreshKey]);
  const [symbol, setSymbol] = useState("");

  const open = useCallback((s: string) => { setSymbol(s); go("stock"); }, [go]);
  const h = health.data;
  const rows: ScanRow[] = scan.data?.rows ?? [];
  const llmReady = h?.llm_providers.filter((p) => p.configured).map((p) => p.name) ?? [];

  return (
    <>
      <header className="top">
        <div className="brand">📈 <b>StockPilot</b> <span className="muted">NSE · BSE</span></div>
        <nav>
          {TABS.map(([t, label]) => (
            <button key={t} className={tab === t ? "active" : ""} onClick={() => go(t)}>{label}</button>
          ))}
        </nav>
        <div className="status">
          {health.error ? <span className="neg">API: {health.error}</span> : h && (
            <>
              <span className={`dot ${h.market_open ? "on" : "off"}`} />Market {h.market_open ? "open" : "closed"} ·
              AI: {llmReady.length ? llmReady.join(", ") : <span className="neg">none</span>} ·
              Telegram {h.telegram ? "✓" : "✗"} · Trader <b>{h.trader_mode}</b>{h.kill_switch && " ⛔"}
            </>
          )}
        </div>
      </header>

      <main>
        {tab === "home" && (
          <>
            <div className="cards">
              <Kpi label="Market">{h?.market_open ? "🟢 Open" : "⚪ Closed"}</Kpi>
              <Kpi label="Watchlist">{h?.watchlist.length ?? "–"} stocks</Kpi>
              <Kpi label="AI providers ready">{llmReady.length}</Kpi>
              <Kpi label="Telegram">{h?.telegram ? "✓ connected" : "✗ not set"}</Kpi>
              <Kpi label="Auto-trader">{h?.trader_mode ?? "–"}{h?.kill_switch && " ⛔"}</Kpi>
            </div>
            <div className="grid2">
              <Panel title="🗞️ Latest AI news picks" extra={<button className="link" onClick={() => go("ainews")}>All →</button>}>
                <HomePicks digest={digest.data} onOpen={open} onScan={() => go("ainews")} />
              </Panel>
              <Panel title="🧮 Watchlist signals" extra={<button className="link" onClick={() => go("screener")}>Screener →</button>}>
                {scan.loading ? <Empty>Scanning…</Empty> : !rows.length ? <Empty>No scan yet.</Empty> : (
                  (["BUY", "SELL", "HOLD"] as const).map((a) => {
                    const g = rows.filter((r) => r.action === a);
                    return (
                      <p key={a}>
                        <Badge value={a} />{" "}
                        {g.length ? g.map((r, i) => (
                          <span key={r.symbol}>{i > 0 && " · "}
                            <a href="#stock" onClick={(e) => { e.preventDefault(); open(r.symbol); }}>{r.symbol}</a>
                            {a !== "HOLD" && <> ₹{num(r.price)} (<Signed v={r.score} />)</>}
                          </span>
                        )) : <span className="muted">none</span>}
                      </p>
                    );
                  })
                )}
              </Panel>
            </div>
          </>
        )}
        {tab === "ainews" && (
          <AiNews digest={digest.data} setDigest={(d: Digest) => digest.setData(d)} loading={digest.loading} onOpen={open} />
        )}
        {tab === "screener" && (
          <Screener rows={rows} at={scan.data?.at ?? null} loading={scan.loading} error={scan.error}
            useLlm={useLlm} setUseLlm={setUseLlm} refresh={() => setRefreshKey((k) => k + 1)} onOpen={open} />
        )}
        {tab === "stock" && <Stock symbol={symbol} setSymbol={setSymbol} watchlist={h?.watchlist ?? []} />}
        {tab === "news" && <Headlines onOpen={open} />}
        {tab === "trader" && <Trader onChange={health.reload} />}
        {tab === "settings" && <Settings health={h} onChange={() => { health.reload(); setRefreshKey((k) => k + 1); }} />}
      </main>
      <footer className="muted">Educational software — signals and AI summaries are not investment advice. Free data can be delayed or wrong.</footer>
    </>
  );
}

function HomePicks({ digest, onOpen, onScan }: { digest: Digest | null; onOpen: (s: string) => void; onScan: () => void }) {
  const picks = (digest?.picks ?? []).filter((p) => p.symbol && p.recommendation !== "WATCH").slice(0, 4);
  if (!picks.length) return <Empty>No actionable news picks yet. <button className="link" onClick={onScan}>Run a scan →</button></Empty>;
  return <div className="compact stack">{picks.map((p, i) => <PickCard key={i} p={p} onOpen={onOpen} />)}</div>;
}
