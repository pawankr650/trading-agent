import { useState } from "react";
import { api, waitJob } from "../api";
import { EquityCurve } from "../components/Charts";
import { Badge, Empty, Kpi, Loading, Panel, Signed, Spin, useAsync, useToast } from "../components/ui";
import { num } from "../format";
import type { Trade } from "../types";

type Col = keyof Trade;

function TradeTable({ rows, cols }: { rows: Trade[]; cols: Col[] }) {
  return (
    <div className="table-wrap">
      <table>
        <thead><tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr></thead>
        <tbody>
          {rows.map((t) => (
            <tr key={t.id}>
              {cols.map((c) => (
                <td key={c} className={typeof t[c] === "number" ? "num" : ""}>
                  {c === "pnl" ? <Signed v={t.pnl} d={0} /> : c === "side" ? <Badge value={t.side} /> : String(t[c] ?? "")}
                </td>
              ))}
            </tr>
          ))}
          {!rows.length && <tr><td colSpan={cols.length} className="empty">None</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

export default function Trader({ onChange }: { onChange: () => void }) {
  const toast = useToast();
  const { data: d, loading, error, reload } = useAsync(() => api.trader());
  const [running, setRunning] = useState<number | null>(null);

  async function cycle() {
    setRunning(0);
    try {
      const { job } = await api.cycle();
      await waitJob(job, setRunning);
      toast("Paper cycle done");
    } catch (e) { toast((e as Error).message); }
    setRunning(null); reload();
  }
  async function toggleKill(on: boolean) {
    if (on && !confirm("Stop all NEW entries? Open positions are still managed.")) return;
    try { await (on ? api.kill() : api.resume()); toast(on ? "Kill switch ON" : "Kill switch off"); }
    catch (e) { toast((e as Error).message); }
    reload(); onChange();
  }

  const closed = (d?.trades ?? []).filter((t) => t.status === "CLOSED").sort((a, b) => a.id - b.id);

  return (
    <>
      <div className="toolbar">
        <button className="primary" onClick={cycle} disabled={running !== null || d?.mode !== "paper"}
          title={d?.mode !== "paper" ? "Only available in paper mode" : ""}>
          {running !== null ? <><Spin /> Running… {running}s</> : "▶ Run one paper cycle"}
        </button>
        <button className="danger" onClick={() => toggleKill(true)}>⛔ Kill switch</button>
        <button onClick={() => toggleKill(false)}>Resume</button>
      </div>
      {loading && !d ? <Loading /> : error ? <Panel><div className="empty neg">{error}</div></Panel> : d && (
        <>
          <div className="cards">
            <Kpi label="Mode">{d.mode}</Kpi>
            <Kpi label="Capital">₹{num(d.capital, 0)}</Kpi>
            <Kpi label="Open positions">{d.open.length}</Kpi>
            <Kpi label="P&L today"><Signed v={d.stats.today_pnl} d={0} /></Kpi>
            <Kpi label="Total P&L"><Signed v={d.stats.total_pnl} d={0} /></Kpi>
            <Kpi label="Win rate">{d.stats.win_rate === null ? "–" : `${Math.round(d.stats.win_rate * 100)}%`}</Kpi>
            <Kpi label="Kill switch">{d.kill_switch ? "⛔ ON" : "off"}</Kpi>
          </div>
          <Panel title="Open positions"><TradeTable rows={d.open} cols={["symbol", "side", "qty", "entry", "stop", "target", "opened_at", "mode"]} /></Panel>
          <Panel title="Equity curve (closed trades)">{closed.length ? <EquityCurve trades={closed} /> : <Empty>No closed trades yet.</Empty>}</Panel>
          <Panel title="Trade journal">
            <TradeTable rows={d.trades} cols={["id", "symbol", "side", "qty", "entry", "exit", "pnl", "status", "reason_out", "opened_at", "closed_at", "mode"]} />
          </Panel>
        </>
      )}
    </>
  );
}
