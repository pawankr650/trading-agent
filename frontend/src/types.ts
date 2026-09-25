// Shapes returned by the FastAPI backend (server/app.py)

export type Signal = "BUY" | "SELL" | "HOLD";
export type Rec = "BUY" | "WATCH" | "AVOID" | "SELL";

export interface Plan { entry: number; stop: number; target: number }

export interface Provider { name: string; model: string; configured: boolean }

export interface Health {
  time_ist: string;
  market_open: boolean;
  llm_enabled: boolean;
  llm_providers: Provider[];
  llm_last_used: string | null;
  telegram: boolean;
  trader_mode: string;
  kill_switch: boolean;
  watchlist: string[];
  auth_required: boolean;
}

export interface Fundamentals {
  marketCap?: number | null; trailingPE?: number | null; priceToBook?: number | null;
  returnOnEquity?: number | null; debtToEquity?: number | null; revenueGrowth?: number | null;
  earningsGrowth?: number | null; profitMargins?: number | null; dividendYield?: number | null;
  sector?: string | null; longName?: string | null;
}

export interface NewsItem {
  title: string; link: string; source: string; published: string | null;
  summary?: string; symbol?: string; company?: string; category?: string; event?: string;
}

export interface ScanRow {
  symbol: string; price: number; change_pct: number; action: Signal; score: number;
  tech_score: number; fund_score: number; news_score: number; news_src: string; rsi: number;
  plan: Plan | null; criteria: string[]; fundamentals: Fundamentals; headlines: string[];
}

export interface Candle {
  t: number; o: number; h: number; l: number; c: number; v: number;
  sma20: number | null; sma50: number | null; sma200: number | null; rsi: number | null;
}

export interface LlmReview { action: string; confidence: number; rationale: string }

export interface Report extends Omit<ScanRow, "headlines"> {
  news: NewsItem[]; candles: Candle[]; llm_review?: LlmReview | null;
}

export interface TechCheck {
  price: number; change_pct: number; action: Signal; score: number; tech_score: number;
  fund_score: number; rsi: number; plan: Plan | null; mcap: number | null; criteria: string[];
}

export interface Pick {
  symbol: string; company: string; event: string; summary: string; impact: string; materiality: string;
  recommendation: Rec; confidence: number; horizon: string; thinking: string[]; risks: string;
  sources: { title: string; link: string; source: string }[]; published: string | null;
  tech?: TechCheck; verdict_note?: string;
}

export interface Digest { picks: Pick[]; mood: string; source: string; scanned: number; at: string | null }

export interface Trade {
  id: number; mode: string; symbol: string; side: "BUY" | "SELL"; qty: number; entry: number; stop: number;
  target: number; status: "OPEN" | "CLOSED"; exit: number | null; pnl: number | null; reason_in: string;
  reason_out: string | null; opened_at: string; closed_at: string | null;
}

export interface TraderState {
  mode: string; capital: number; product: string; kill_switch: boolean; open: Trade[]; trades: Trade[];
  stats: { closed: number; win_rate: number | null; total_pnl: number; today_pnl: number };
}

export interface Job<T> { id: string; kind: string; status: "running" | "done" | "error"; started: number; result: T | null; error?: string }
