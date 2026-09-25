# StockPilot — NSE/BSE signals, AI news scanner & auto-trading (open source, free LLMs)

**Web app** — React + TypeScript UI with a FastAPI backend: AI news picks, screener, interactive charts, headlines & exchange filings, auto-trader journal and settings.
**AI news scanner** — reads market news (ET, Moneycontrol, Business Standard, Mint, Google News) **and NSE/BSE corporate filings** (order wins, results, dividends, M&A, penalties…). An open-source LLM summarises each item and says **BUY / WATCH / AVOID / SELL**, with its step-by-step reasoning, risks and a chart/fundamental cross-check. Digests go to Telegram.
**System 1 · Notifier** — Telegram alerts with chart, BUY/SELL/HOLD criteria, fundamentals, news and an AI second opinion. Pre-market brief, intraday alerts, end-of-day board, scheduled AI news digests.
**System 2 · Auto-trader** — Same signals → risk manager → AI veto → orders through OpenAlgo (Zerodha, Angel One, Upstox, Dhan, Fyers, …). Paper mode by default.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the design.

## Quick start
```bash
python -m venv .venv && source .venv/bin/activate       # Python 3.11+
pip install -r requirements.txt
cp .env.example .env          # add at least one free LLM key + Telegram bot token/chat id

# build the web UI once (Node 20.19+ or 22)
cd frontend && npm install && npm run build && cd ..

python -m unittest -v          # offline tests
python -m server.app           # web app  → http://127.0.0.1:8000   (API docs at /docs)
python -m notifier.run --news  # one AI news scan → Telegram (or console if Telegram isn't set)
```

### Run continuously
```bash
python -m server.app          # web app (also refreshes the AI news digest on schedule)
python -m notifier.run        # System 1: Telegram alerts + AI news digests
python -m autotrader.run      # System 2 (paper)
# or everything at once:  docker compose up -d --build   → http://localhost:8000
```

### Developing the UI
```bash
python -m server.app                # backend on :8000
cd frontend && npm run dev          # Vite dev server on :5173 with hot reload, /api proxied to :8000
npm run typecheck                   # TypeScript check
```

## AI news scanner — how it decides
1. **Collect** RSS headlines + Google News queries + NSE and BSE corporate announcements (routine filings such as trading-window notices are dropped).
2. **Rank** by event type (order wins and results first) and skip anything already analysed.
3. **LLM** (batch of ~12 items per call) returns per stock: summary, event, impact, materiality, recommendation, confidence, horizon, **thinking steps** and risks, plus an overall market mood.
4. **Cross-check** every BUY/WATCH stock with the chart + fundamentals model; a news BUY on a falling chart is downgraded to WATCH.
5. **Deliver** to Telegram (only when something is actionable and above `news_scanner.min_confidence`) and to the web app's *AI News* tab.

Tune everything under `news_scanner:` in `config.yaml` (interval, active hours, sources, queries, thresholds).
No LLM key? It still works using keyword sentiment, and says so in the digest.

## Free open-source LLM keys
| Service | Where | Models (examples) |
|---|---|---|
| Groq | console.groq.com/keys | Llama 3.3 70B, gpt-oss-120b, Qwen3 |
| Cerebras | cloud.cerebras.ai | Llama 3.3 70B, gpt-oss-120b |
| Hugging Face | huggingface.co/settings/tokens | Llama, Qwen, DeepSeek (free monthly credits) |
| OpenRouter | openrouter.ai/keys | `:free` Llama / DeepSeek / Qwen models |
| Ollama | ollama.com (local) | anything you pull — unlimited, runs on your PC |
| Gemini (optional, not open-source) | aistudio.google.com/apikey | gemini-2.5-flash |

Providers are tried in order; a failing one (bad key, retired model, offline) is skipped for 15 minutes and **its own error text is logged**, so `data/*.log` tells you exactly what to fix. Change a model without editing code via `GROQ_MODEL`, `HF_MODEL`, … in `.env`. *Settings → Test LLM* in the web app checks the chain.

## Telegram commands
System 1: `/analyze RELIANCE` · `/top` · `/news` · `/scannews` (AI news scan now) · `/help`
System 2 (needs `TELEGRAM_TRADER_BOT_TOKEN`): `/status` · `/kill` · `/resume`

## Going live (System 2) — do it in this order
1. Paper-trade for at least 2–4 weeks; review the journal in the web app (*Auto-trader* tab).
2. Install **OpenAlgo** (github.com/marketcalls/openalgo), connect your broker, create an API key, put it in `.env`.
3. Switch OpenAlgo to **Analyzer mode**, set `autotrader.mode: live` → orders are simulated by OpenAlgo.
4. Register a **static IP** with your broker (SEBI rule from 1 Apr 2026) and log in daily (2FA).
5. Turn Analyzer off, start with small `capital`.

Optional deep check: install TradingAgents and set `tradingagents_confirm: true` (slow, uses many LLM calls).

## Security
The web app can trigger scans, paper trades and the kill switch. It listens on `127.0.0.1` by default; before exposing it (`HOST=0.0.0.0`, a VPS, docker port without `127.0.0.1:`) set `APP_TOKEN` in `.env` and enter it under *Settings* in the UI.

## Customize
All thresholds live in `config.yaml`: watchlist, weights, buy/sell thresholds, ATR stop, R:R, risk %, product (CNC/MIS), intervals, news-scanner settings. The watchlist can also be edited in the web app (saved to `data/overrides.json`).

> ⚠️ Educational software. Signals and AI summaries are not investment advice; automated trading can lose money. Free data (yfinance/RSS/exchange sites) can be delayed or wrong — use OpenAlgo live data for intraday.
