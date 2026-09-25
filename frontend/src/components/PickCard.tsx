import { EVENT_LABEL, ago, crore, num, safeUrl } from "../format";
import type { Pick } from "../types";
import { Badge, Signed } from "./ui";

export default function PickCard({ p, onOpen }: { p: Pick; onOpen: (symbol: string) => void }) {
  const t = p.tech;
  const name = p.symbol || p.company || "Market";
  return (
    <article className={`pick ${p.recommendation}`}>
      <h3>
        <Badge value={p.recommendation} />
        {p.symbol ? <a href="#stock" onClick={(e) => { e.preventDefault(); onOpen(p.symbol); }}>{name}</a> : name}
        {p.symbol && p.company && <span className="muted" style={{ fontWeight: 400, fontSize: 13 }}>{p.company}</span>}
      </h3>
      <div className="meta">
        📌 {EVENT_LABEL[p.event] ?? p.event} · impact <b>{p.impact}</b> · materiality {p.materiality} · confidence{" "}
        <b>{Math.round(p.confidence * 100)}%</b>
        {p.horizon && ` · ${p.horizon}`}
        {p.published && ` · ${ago(p.published)}`}
      </div>
      <div>{p.summary}</div>
      {p.thinking.length > 0 && (
        <div style={{ marginTop: ".5rem" }}>
          <b>🧠 Thinking</b>
          <ol>{p.thinking.map((x, i) => <li key={i}>{x}</li>)}</ol>
        </div>
      )}
      {p.risks && <div>⚠️ <b>Risks:</b> {p.risks}</div>}
      {t && (
        <div className="tech">
          📊 ₹{num(t.price)} (<Signed v={t.change_pct} suffix="%" />) · model <Badge value={t.action} /> <Signed v={t.score} /> ·
          tech <Signed v={t.tech_score} /> · fund <Signed v={t.fund_score} /> · RSI {num(t.rsi, 0)}
          {t.mcap ? ` · Mcap ${crore(t.mcap)}` : ""}
          {t.plan && <><br />🎯 Entry {num(t.plan.entry)} · SL {num(t.plan.stop)} · Target {num(t.plan.target)}</>}
        </div>
      )}
      {p.sources.length > 0 && <div className="src">
        🔗{" "}
        {p.sources.slice(0, 3).map((s, i) => (
          <span key={i}>
            {i > 0 && " · "}
            <a target="_blank" rel="noopener noreferrer" href={safeUrl(s.link)} title={s.title}>{s.source || "source"}</a>
          </span>
        ))}
      </div>}
    </article>
  );
}
