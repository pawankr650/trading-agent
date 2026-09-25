# StockPilot — NSE/BSE signals, alerts & auto-trading (open source, free LLMs)

**System 1 · Notifier** — Telegram alerts with chart, BUY/SELL/HOLD criteria, fundamentals, NSE/BSE news and an AI second opinion. Pre-market brief, intraday alerts, end-of-day board.
**System 2 · Auto-trader** — Same signals → risk manager → AI veto → orders through OpenAlgo (Zerodha, Angel One, Upstox, Dhan, Fyers, …). Paper mode by default.
**Web terminal** — one page, three desks (FastAPI + TradingView Lightweight Charts):
- **News Intelligence** — RSS + Google News polled continuously → Hugging Face **FinBERT** sentiment + zero-shot **event type** → tagged to NIFTY 50 stocks → live signal board with reasons, buy zone, stop-loss and two exit targets per stock. Streams to the browser (SSE).
- **Pattern Scanner** — all NIFTY 50: 61 **TA-Lib** candlestick patterns + chart patterns (double top/bottom, head & shoulders, triangles, wedges, channels, breakouts, golden/death cross) drawn on the chart with support/resistance.
- **Algo Lab** — **backtesting.py** simulations of 7 strategies with animated replay, equity vs buy-and-hold, drawdown, trade log, auto-tuning (70% train / 30% out-of-sample) and a strategy race that ranks them by Sharpe.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the design.

## Quick start (10 minutes)
```bash
python -m venv .venv && source .venv/bin/activate      # Python 3.11+ (3.12 if you use OpenAlgo SDK)
pip install -r requirements.txt
cp .env.example .env        # add at least one free LLM key + Telegram bot token/chat id
python -m unittest -v       # offline tests
python -m notifier.run --once      # one scan → Telegram (or console if Telegram not set)
uvicorn web.server:app --port 8000 # web terminal at http://localhost:8000
STOCKPILOT_DEMO=1 uvicorn web.server:app   # offline demo (synthetic data, badged in the UI)
```

### Run continuously
```bash
python -m notifier.run        # System 1
python -m autotrader.run      # System 2 (paper)
# or: docker compose up -d
```

## Free keys
| Service | Where | Free limit (approx.) |
|---|---|---|
| Groq | console.groq.com | 30 req/min, 1,000/day |
| Gemini | aistudio.google.com/apikey | 5–15 req/min |
| OpenRouter | openrouter.ai/keys | 20 req/min, 50/day (`:free` models) |
| Ollama | ollama.com (local) | unlimited, runs on your PC |
| Hugging Face | huggingface.co/settings/tokens → `HF_TOKEN` | free Inference API (FinBERT, BART-MNLI); or run locally with `pip install transformers torch` |
| Telegram | @BotFather | free |

## Going live (System 2) — do it in this order
1. Paper-trade for at least 2–4 weeks; review `data/trades.db`, and backtest your idea in the Algo Lab.
2. Install **OpenAlgo** (github.com/marketcalls/openalgo), connect your broker, create an API key, put it in `.env`.
3. Switch OpenAlgo to **Analyzer mode**, set `autotrader.mode: live` → orders are simulated by OpenAlgo.
4. Register a **static IP** with your broker (SEBI rule from 1 Apr 2026) and log in daily (2FA).
5. Turn Analyzer off, start with small `capital`.

Optional deep check: install TradingAgents and set `tradingagents_confirm: true` (slow, uses many LLM calls).

## Telegram commands
System 1: `/analyze RELIANCE` · `/top` · `/news`
System 2 (needs `TELEGRAM_TRADER_BOT_TOKEN`): `/status` · `/kill` · `/resume`

## Customize
All thresholds live in `config.yaml`: watchlist, weights, buy/sell thresholds, ATR stop, R:R, risk %, product (CNC/MIS), intervals.

> ⚠️ Educational software. Signals are not investment advice; automated trading can lose money. Free data (yfinance/RSS) can be delayed or wrong — use OpenAlgo live data for intraday.
