import type { Digest, Health, Job, NewsItem, Report, ScanRow, TraderState } from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

const TOKEN_KEY = "sp_token";

export function getToken(): string {
  try { return localStorage.getItem(TOKEN_KEY) ?? ""; } catch { return ""; }
}
export function setToken(t: string): void {
  try { localStorage.setItem(TOKEN_KEY, t); } catch { /* private mode — ignore */ }
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers["X-App-Token"] = token;
  const r = await fetch(path, { ...init, headers });
  if (!r.ok) {
    let msg = `HTTP ${r.status}`;
    try { msg = (await r.json()).detail ?? msg; } catch { /* not JSON */ }
    if (r.status === 401) msg = "Enter the APP_TOKEN in Settings";
    throw new ApiError(r.status, msg);
  }
  return r.json() as Promise<T>;
}

const post = <T>(path: string, body?: unknown) =>
  call<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export async function waitJob<T>(id: string, onTick?: (seconds: number) => void): Promise<T> {
  for (let i = 0; i < 600; i++) {
    const j = await call<Job<T>>(`/api/jobs/${id}`);
    if (j.status === "done") return j.result as T;
    if (j.status === "error") throw new Error(j.error ?? "job failed");
    onTick?.(Math.round(Date.now() / 1000 - j.started));
    await new Promise((res) => setTimeout(res, 2000));
  }
  throw new Error("timed out");
}

export const api = {
  health: () => call<Health>("/api/health"),
  scan: (llm: boolean, refresh = false) => call<{ at: number; rows: ScanRow[] }>(`/api/scan?llm=${llm}&refresh=${refresh}`),
  analyze: (sym: string, llm: boolean) => call<Report>(`/api/analyze/${encodeURIComponent(sym)}?llm=${llm}`),
  news: (limit = 60) => call<{ items: NewsItem[] }>(`/api/news?limit=${limit}`),
  filings: () => call<{ items: NewsItem[] }>("/api/filings"),
  digest: () => call<Digest>("/api/news/digest"),
  scanNews: (sendTelegram: boolean) => post<{ job: string }>("/api/news/scan", { only_new: false, send_telegram: sendTelegram }),
  trader: () => call<TraderState>("/api/trader"),
  kill: () => post<{ kill_switch: boolean }>("/api/trader/kill"),
  resume: () => post<{ kill_switch: boolean }>("/api/trader/resume"),
  cycle: () => post<{ job: string }>("/api/trader/cycle"),
  setWatchlist: (symbols: string[]) => call<{ watchlist: string[] }>("/api/watchlist", { method: "PUT", body: JSON.stringify({ symbols }) }),
  testLlm: () => post<{ ok: boolean; reply: string; provider: string | null; seconds: number }>("/api/llm/test"),
  testTelegram: () => post<{ ok: boolean }>("/api/telegram/test"),
};
