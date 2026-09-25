import { useEffect, useState } from "react";
import { api, getToken, setToken } from "../api";
import { Panel, Spin, useToast } from "../components/ui";
import type { Health } from "../types";

export default function Settings({ health, onChange }: { health: Health | null; onChange: () => void }) {
  const toast = useToast();
  const [wl, setWl] = useState("");
  const [token, setTok] = useState(getToken());
  const [llmOut, setLlmOut] = useState<React.ReactNode>("");
  const [tgOut, setTgOut] = useState("");

  useEffect(() => { if (health) setWl(health.watchlist.join("\n")); }, [health]);

  async function saveWl() {
    const symbols = wl.split(/[\s,]+/).map((s) => s.trim().toUpperCase()).filter(Boolean);
    try { await api.setWatchlist(symbols); toast("Watchlist saved"); onChange(); }
    catch (e) { toast((e as Error).message); }
  }
  async function testLlm() {
    setLlmOut(<Spin />);
    try {
      const r = await api.testLlm();
      setLlmOut(r.ok ? `✓ ${r.provider} replied "${r.reply}" in ${r.seconds}s` : "✗ no provider answered — see the server log for each provider's error");
    } catch (e) { setLlmOut((e as Error).message); }
  }
  async function testTg() {
    try { const r = await api.testTelegram(); setTgOut(r.ok ? "✓ sent" : "✗ failed"); }
    catch (e) { setTgOut((e as Error).message); }
  }

  return (
    <div className="grid2">
      <Panel title="Watchlist">
        <p className="muted">One NSE symbol per line. Saved to <code>data/overrides.json</code> (config.yaml stays untouched).</p>
        <textarea rows={14} value={wl} onChange={(e) => setWl(e.target.value)} />
        <button className="primary" onClick={saveWl}>Save watchlist</button>
      </Panel>
      <Panel title="AI (open-source LLMs)">
        <p className="muted">Tried in order; the first one that works wins. Add keys in <code>.env</code>, override models with <code>*_MODEL</code> env vars.</p>
        <div className="table-wrap">
          <table>
            <thead><tr><th>#</th><th>Provider</th><th>Model</th><th>Key</th></tr></thead>
            <tbody>
              {health?.llm_providers.map((p, i) => (
                <tr key={p.name}><td>{i + 1}</td><td>{p.name}</td><td><code>{p.model}</code></td><td>{p.configured ? "✓" : <span className="muted">—</span>}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
        <p><button onClick={testLlm}>Test LLM</button> <span className="muted">{llmOut}</span></p>
        <h2 style={{ marginTop: "1.5rem" }}>Telegram</h2>
        <p><button onClick={testTg}>Send test message</button> <span className="muted">{tgOut}</span></p>
        <h2 style={{ marginTop: "1.5rem" }}>Access token</h2>
        <p className="muted">Only needed when the server sets <code>APP_TOKEN</code>. Stored in this browser only.</p>
        <input type="password" value={token} onChange={(e) => setTok(e.target.value)} placeholder="APP_TOKEN" />{" "}
        <button onClick={() => { setToken(token); toast("Token saved"); onChange(); }}>Save</button>
      </Panel>
    </div>
  );
}
