# StockPilot — NSE/BSE signals, alerts & auto-trading (open source, free LLMs)

**System 1 · Notifier** — Telegram alerts with chart, BUY/SELL/HOLD criteria, fundamentals, NSE/BSE news and an AI second opinion. Pre-market brief, intraday alerts, end-of-day board.
**System 2 · Auto-trader** — Same signals → risk manager → AI veto → orders through OpenAlgo (Zerodha, Angel One, Upstox, Dhan, Fyers, …). Paper mode by default.
**Dashboard** — Streamlit screener, interactive charts, fundamentals, news, trade journal.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the design.

## Quick start (10 minutes)
```bash
python -m venv .venv && source .venv/bin/activate      # Python 3.11+ (3.12 if you use OpenAlgo SDK)
pip install -r requirements.txt
cp .env.example .env        # add at least one free LLM key + Telegram bot token/chat id
python -m unittest -v       # offline tests
python -m notifier.run --once      # one scan → Telegram (or console if Telegram not set)
streamlit run dashboard/app.py     # dashboard at http://localhost:8501
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
| Telegram | @BotFather | free |

## Going live (System 2) — do it in this order
1. Paper-trade for at least 2–4 weeks; review `data/trades.db` in the dashboard.
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
