# StockPilot — Architecture

A web app and two background systems share one analysis core. Everything is open source and runs on free tiers.

```
                ┌────────────────────── DATA LAYER (free) ───────────────────────┐
                │ yfinance (.NS/.BO OHLCV + fundamentals)   OpenAlgo (live quotes) │
                │ RSS: ET · Moneycontrol · Business Std · Mint · Google News       │
                │ NSE + BSE corporate filings (order wins, results, M&A, …)        │
                └───────────────────────────────┬──────────────────────────────────┘
                                                │
                ┌────────────────────── CORE (core/) ────────────────────────────┐
                │ indicators.py  SMA20/50/200 · RSI · MACD · ATR · Bollinger ·    │
                │                Supertrend · volume surge  → technical score     │
                │ fundamentals.py ROE · D/E · growth · margin · P/E → fund score  │
                │ news.py + llm.py  headlines → sentiment (LLM, keyword fallback) │
                │ analysis.py  0.50·tech + 0.25·fund + 0.25·news → BUY/SELL/HOLD  │
                │              + ATR trade plan (entry · stop · target, 1:2 R:R)  │
                │ news_scanner.py  news+filings → LLM → BUY/WATCH/AVOID + reasons │
                │ llm.py   Groq → Cerebras → HF → OpenRouter → Ollama (open-src)  │
                └───────────────┬──────────────────────────────┬─────────────────┘
                                │                              │
      ┌──────── SYSTEM 1: notifier/ ───────┐    ┌──────── SYSTEM 2: autotrader/ ─────────┐
      │ 08:45 pre-market news + board      │    │ every 5 min in market hours:           │
      │ 09:15–15:30 scan every 15 min,     │    │ 1 manage positions (SL/TGT/square-off) │
      │   alert when a signal flips        │    │ 2 risk gate (kill, daily loss, slots)  │
      │ 15:45 end-of-day board             │    │ 3 signals from core                    │
      │ Telegram: chart PNG + criteria +   │    │ 4 AI veto (LLM / TradingAgents)        │
      │   fundamentals + news + AI view    │    │ 5 size → order → SL-M → journal → TG   │
      │ /analyze SYM · /top · /news        │    │ Paper broker  |  OpenAlgo (30+ brokers)│
      └────────────────────────────────────┘    │ /status · /kill · /resume             │
                                                 └────────────────────────────────────────┘
   WEB APP: server/app.py (FastAPI REST, /docs)  +  frontend/ (React + TypeScript, Vite)
            Overview · AI News · Screener · Stock charts · Headlines & Filings · Auto-trader · Settings
```

## Why these open-source pieces

| Need | Choice | Why |
|---|---|---|
| Broker execution (India) | **OpenAlgo** (AGPL, self-hosted) | One API for 30+ Indian brokers, Analyzer/sandbox mode, Telegram, TradingView webhooks, MCP server for AI agents |
| Deep AI analysis (optional) | **TradingAgents** (Apache-2.0) | Multi-agent LLM "trading firm" — analysts, bull/bear debate, risk manager; supports Gemini, OpenRouter, Ollama |
| Free LLMs | Groq, Google AI Studio (Gemini), OpenRouter `:free` models, Ollama | All OpenAI-compatible, no card needed; chain falls back on rate-limit |
| Prices / fundamentals | yfinance | Free, covers NSE (.NS) and BSE (.BO) |
| News | Public RSS feeds | No keys, no scraping |
| Alerts | Telegram Bot API | Free, instant, supports images & commands |
| Web app | FastAPI + React/TypeScript (Vite) + lightweight-charts | Typed API, fast UI, one process serves both |
| News LLM | Open-weight models (Llama, gpt-oss, Qwen, DeepSeek) via OpenAI-compatible APIs | Free tiers, swap models via env vars |

## Safety design (System 2)
- **Paper mode by default**; live requires `mode: live` + OpenAlgo key. Test in OpenAlgo Analyzer mode first.
- Rule engine decides; **LLM can only veto**, never originate a trade.
- Risk per trade 1% of capital, max 20% per stock, max 5 positions, 2% daily-loss kill switch, `/kill` command, entry cut-off 14:45, MIS square-off 15:10.
- Protective **SL-M order at the broker** right after entry, so a crash of the bot doesn't leave positions unprotected.
- Order rate limiter at 5/s (SEBI retail-algo threshold is 10/s).

## SEBI retail-algo rules (from 1 Apr 2026)
Broker APIs now require a registered app mapped to a **whitelisted static IP**, **daily 2FA login**, **≤10 orders/sec**, and market orders are converted to **Market Price Protection** orders. Third-party algo platforms must be empanelled with the broker. Self-hosted, personal-use setups (like this) should run on a machine/VPS with a static IP registered with your broker and log in to OpenAlgo each morning.
