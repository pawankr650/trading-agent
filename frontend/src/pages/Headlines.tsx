import { api } from "../api";
import { Loading, Panel, useAsync } from "../components/ui";
import { EVENT_LABEL, ago, safeUrl } from "../format";

export default function Headlines({ onOpen }: { onOpen: (s: string) => void }) {
  const news = useAsync(() => api.news(60));
  const filings = useAsync(() => api.filings());

  return (
    <div className="grid2">
      <Panel title="📰 Market headlines">
        {news.loading ? <Loading /> : news.error ? <div className="neg">{news.error}</div> : (
          <ul className="list">
            {news.data?.items.length ? news.data.items.map((n, i) => (
              <li key={i}>
                <a target="_blank" rel="noopener noreferrer" href={safeUrl(n.link)}>{n.title}</a>
                <div className="src">{n.source} · {ago(n.published)}</div>
              </li>
            )) : <li className="muted">No headlines (feeds unreachable?)</li>}
          </ul>
        )}
      </Panel>
      <Panel title="🏛️ NSE / BSE filings" extra={<span className="muted">order wins, results, M&amp;A…</span>}>
        {filings.loading ? <Loading /> : filings.error ? <div className="neg">{filings.error}</div> : (
          <ul className="list">
            {filings.data?.items.length ? filings.data.items.slice(0, 80).map((n, i) => (
              <li key={i}>
                {n.symbol && <><a href="#stock" onClick={(e) => { e.preventDefault(); onOpen(n.symbol!); }}><b>{n.symbol}</b></a>{" "}</>}
                <span className="badge b-HOLD">{EVENT_LABEL[n.event ?? "other"] ?? n.event}</span>{" "}
                <a target="_blank" rel="noopener noreferrer" href={safeUrl(n.link)}>{n.title}</a>
                <div className="src">{n.source} · {ago(n.published)}</div>
              </li>
            )) : <li className="muted">No filings (NSE/BSE unreachable from this server?)</li>}
          </ul>
        )}
      </Panel>
    </div>
  );
}
