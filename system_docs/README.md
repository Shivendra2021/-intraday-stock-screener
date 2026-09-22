# 📖 MarketMind Pro — System Documentation & Architecture Overview

Welcome to the comprehensive system documentation for **MarketMind Pro** (Intraday Stock Screener & Algorithmic Research Engine for Indian Equities - NSE/BSE).

This directory contains the complete technical breakdown of the entire platform, structured into distinct frontend, backend, and operational audit specifications.

---

## 📂 Documentation Directory

| Document | Description |
| :--- | :--- |
| **[BACKEND_ARCHITECTURE.md](BACKEND_ARCHITECTURE.md)** | Deep-dive into the Python backend: dual engines (Quant V3 vs Legacy V2), scheduler, 16-worker universe scanner, AI debate brain, reinforcement learning (LinUCB & PPO), data persistence (`quant.db` & `history.db`), broker feeds, and Telegram broadcaster. |
| **[FRONTEND_ARCHITECTURE.md](FRONTEND_ARCHITECTURE.md)** | Deep-dive into the user interface: Waitress/Flask WSGI on port 5001, Quant V3 7-tab modern workspace, Legacy V2 monitoring console, stock inspection charts, API telemetry contracts, and control security. |
| **[MISSING_COMPONENTS_AND_ROADMAP.md](MISSING_COMPONENTS_AND_ROADMAP.md)** | Comprehensive audit of all currently missing, broken, or unconfigured components (Python `.venv` path corruption, missing `data/history.db`, empty `.env` API keys, empty `tests/e2e` suite, stale lock files), accompanied by a step-by-step fix roadmap. |

---

## 🏛️ High-Level System Architecture

```mermaid
flowchart TD
    subgraph DataSources["External Data Feeds"]
        YF["Yahoo Finance (5m / Daily)"]
        NSE["NSE Public Portal & Archives"]
        Dhan["DhanHQ Broker API"]
        Angel["Angel One SmartAPI"]
        News["NewsAPI & TheNewsAPI"]
        Macro["FRED & Finnhub"]
    end

    subgraph BackendCore["Backend Engine (Python 3.14)"]
        Scheduler["APScheduler (6 Market Phases)"]
        Supervisor["Automation Supervisor & Recovery"]
        Scanner["Universe Scanner (Small & Midcaps)"]
        QuantEng["Quant V3 Engine (+7% / +10% Probabilities)"]
        AIBrain["AI Reviewer & Dual-Brain Debate"]
        RL["Reinforcement Learning (LinUCB & PPO)"]
        Alerts["Telegram Broadcaster (HTML Sanitized)"]
    end

    subgraph Persistence["Storage Layer (data/)"]
        QuantDB[("quant.db<br/>5m Candles & Fills")]
        HistoryDB[("history.db<br/>Trades & Patterns")]
        CacheJSON["news_cache.json & states"]
    end

    subgraph Frontend["Web Dashboard (localhost:5001)"]
        FlaskWaitress["Waitress WSGI + Flask Backend"]
        QuantUI["Quant V3 Modern Workspace (7 Tabs)"]
        LegacyUI["Legacy Monitoring Dashboard (/legacy)"]
    end

    DataSources --> BackendCore
    BackendCore --> Persistence
    Persistence --> Frontend
    BackendCore --> Alerts
    Frontend -.->|Trigger Actions| BackendCore
```

---

## ⚡ Quick Reference

* **Main Scheduler Process:** `python main.py`
* **Web Dashboard:** `python dashboard/app.py` (accessible at `http://localhost:5001`)
* **Quant Administration CLI:** `python tools/quant.py [status|audit|prepare|learn]`
* **Database Locations:** `data/quant.db` (Quant V3) and `data/history.db` (Legacy & Paper Records)
* **Configuration:** `config.py` and `.env`
