# StockPilot — NSE/BSE signals, AI news scanner & auto-trading (open source, free LLMs)

**Web terminal** — one page, three desks (FastAPI + TradingView Lightweight Charts, no build step):
- **News Intelligence** — RSS + Google News polled continuously → Hugging Face **FinBERT** sentiment + zero-shot **event type** → tagged to NIFTY 50 stocks → live signal board with reasons, buy zone, stop-loss and two exit targets per stock, streamed to the browser.
- **Pattern Scanner** — all NIFTY 50: 61 **TA-Lib** candlestick patterns + chart patterns (double top/bottom, head & shoulders, triangles, wedges, channels, breakouts, golden/death cross) drawn on the chart with support/resistance.
- **Algo Lab** — **backtesting.py** simulations of 7 strategies with animated replay, equity vs buy & hold, drawdown, trade log, auto-tuning (70% train / 30% out-of-sample) and a strategy race ranked by Sharpe.
**AI news scanner** — reads market news (ET, Moneycontrol, Business Standard, Mint, Google News) **and NSE/BSE corporate filings** (order wins, results, dividends, M&A, penalties…). An open-source LLM summarises each item and says **BUY / WATCH / AVOID / SELL**, with its step-by-step reasoning, risks and a chart/fundamental cross-check. Digests go to Telegram.
**System 1 · Notifier** — Telegram alerts with chart, BUY/SELL/HOLD criteria, fundamentals, news and an AI second opinion. Pre-market brief, intraday alerts, end-of-day board, scheduled AI news digests.
**System 2 · Auto-trader** — Same signals → risk manager → AI veto → orders through OpenAlgo (Zerodha, Angel One, Upstox, Dhan, Fyers, …). Paper mode by default.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the design.

## Quick start
```bash
python -m venv .venv && source .venv/bin/activate       # Python 3.11+
pip install -r requirements.txt
cp .env.example .env          # add at least one free LLM key + HF_TOKEN + Telegram bot token/chat id

python -m unittest -v          # offline tests
python -m server.app           # web terminal → http://127.0.0.1:8000   (API docs at /docs)
STOCKPILOT_DEMO=1 python -m server.app   # offline demo: synthetic prices + sample headlines, badged in the UI
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
The page is plain HTML/CSS/JS in `web/static/` — edit and refresh, no build step. Its API lives in `server/terminal.py`.

## News Intelligence — how a stock gets its plan
1. **Poll** every `news.poll_seconds` (120 s): the RSS feeds, a Google News market query, and 5 per-stock queries rotating through the NIFTY 50.
2. **Hugging Face models** score each new headline: `ProsusAI/finbert` sentiment + `facebook/bart-large-mnli` zero-shot event type. They run locally if `transformers` is installed, else through the HF Inference API with `HF_TOKEN`, else keyword rules (the page footer says which).
3. **Tag** headlines to NIFTY 50 stocks by company name and alias.
4. **Score** = 0.45 × technicals + 0.35 × news sentiment (confidence-weighted, 12 h half-life) + 0.20 × recent patterns.
5. **Plan**: buy zone from nearest support / ½ ATR, stop 1.5 × ATR beyond it, T1 at 2R, T2 at the next resistance or 3R. With an LLM key, BUY/SELL calls also get a 2-sentence thesis.

## AI news scanner — how it decides
1. **Collect** RSS headlines + Google News queries + NSE and BSE corporate announcements (routine filings such as trading-window notices are dropped).
2. **Rank** by event type (order wins and results first) and skip anything already analysed.
3. **LLM** (batch of ~12 items per call) returns per stock: summary, event, impact, materiality, recommendation, confidence, horizon, **thinking steps** and risks, plus an overall market mood.
4. **Cross-check** every BUY/WATCH stock with the chart + fundamentals model; a news BUY on a falling chart is downgraded to WATCH.
5. **Deliver** to Telegram (only when something is actionable and above `news_scanner.min_confidence`) and to `GET /api/news/digest` (see `/docs`).

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

Providers are tried in order; a failing one (bad key, retired model, offline) is skipped for 15 minutes and **its own error text is logged**, so `data/*.log` tells you exactly what to fix. Change a model without editing code via `GROQ_MODEL`, `HF_MODEL`, … in `.env`. `POST /api/llm/test` (try it at `/docs`) checks the chain.

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
The web app can trigger scans, paper trades and the kill switch. It listens on `127.0.0.1` by default; before exposing it (`HOST=0.0.0.0`, a VPS, docker port without `127.0.0.1:`) set `APP_TOKEN` in `.env`; the page asks for it once (or open `/?token=YOUR_TOKEN`) and remembers it in that browser.

## Customize
All thresholds live in `config.yaml`: watchlist, weights, buy/sell thresholds, ATR stop, R:R, risk %, product (CNC/MIS), intervals, news-scanner settings. The watchlist can also be edited in the web app (saved to `data/overrides.json`).

> ⚠️ Educational software. Signals and AI summaries are not investment advice; automated trading can lose money. Free data (yfinance/RSS/exchange sites) can be delayed or wrong — use OpenAlgo live data for intraday.
