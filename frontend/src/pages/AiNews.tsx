import { useState } from "react";
import { api, waitJob } from "../api";
import PickCard from "../components/PickCard";
import { Badge, Empty, Loading, Panel, Spin, useToast } from "../components/ui";
import { ago } from "../format";
import type { Digest, Rec } from "../types";

type Filter = "ALL" | "BUY" | "WATCH" | "AVOID";

export default function AiNews({ digest, setDigest, loading, onOpen }: {
  digest: Digest | null; setDigest: (d: Digest) => void; loading: boolean; onOpen: (s: string) => void;
}) {
  const toast = useToast();
  const [filter, setFilter] = useState<Filter>("ALL");
  const [sendTg, setSendTg] = useState(false);
  const [running, setRunning] = useState<number | null>(null);

  async function scan() {
    setRunning(0);
    try {
      const { job } = await api.scanNews(sendTg);
      setDigest(await waitJob<Digest>(job, setRunning));
      toast("News scan complete");
    } catch (e) {
      toast(`Scan failed: ${(e as Error).message}`);
    }
    setRunning(null);
  }

  const picks = digest?.picks ?? [];
  const count = (r: Rec[]) => picks.filter((p) => r.includes(p.recommendation)).length;
  const shown = picks.filter((p) => filter === "ALL" || p.recommendation === filter || (filter === "AVOID" && p.recommendation === "SELL"));

  return (
    <>
      <div className="toolbar">
        <button className="primary" onClick={scan} disabled={running !== null}>
          {running !== null ? <><Spin /> Scanning… {running}s</> : "🔎 Scan news now"}
        </button>
        <label className="chk"><input type="checkbox" checked={sendTg} onChange={(e) => setSendTg(e.target.checked)} /> also send to Telegram</label>
        <span className="spacer" />
        <div className="seg">
          {(["ALL", "BUY", "WATCH", "AVOID"] as Filter[]).map((f) => (
            <button key={f} className={filter === f ? "active" : ""} onClick={() => setFilter(f)}>
              {{ ALL: "All", BUY: "🟢 Buy", WATCH: "👀 Watch", AVOID: "🟠 Avoid / 🔴 Sell" }[f]}
            </button>
          ))}
        </div>
      </div>

      {loading && !digest ? <Loading /> : !picks.length ? (
        <Panel><Empty>No AI news scan yet. Press <b>Scan news now</b> — it reads market news, Google News and NSE/BSE filings, then asks the open-source LLM what to buy or avoid and why.</Empty></Panel>
      ) : (
        <>
          <Panel title="🌡️ Market mood" extra={<span className="muted">{digest?.at && `scanned ${ago(digest.at)} · `}{digest?.scanned} items · AI: {digest?.source}</span>}>
            <div>{digest?.mood || "—"}</div>
            <div style={{ marginTop: ".5rem", display: "flex", gap: "1rem", flexWrap: "wrap" }}>
              <span><Badge value="BUY" /> {count(["BUY"])}</span><span><Badge value="WATCH" /> {count(["WATCH"])}</span>
              <span><Badge value="AVOID" /> {count(["AVOID"])}</span><span><Badge value="SELL" /> {count(["SELL"])}</span>
            </div>
          </Panel>
          <div className="picks">
            {shown.length ? shown.map((p, i) => <PickCard key={`${p.symbol}-${i}`} p={p} onOpen={onOpen} />) : <Empty>Nothing in this category.</Empty>}
          </div>
        </>
      )}
    </>
  );
}
