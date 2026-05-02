# StockUp 📈

**Buffett-style stock analysis and tracking platform for the Kenyan market.**

StockUp helps you track NSE (Nairobi Securities Exchange) stock prices, calculate intrinsic values using Warren Buffett's investment principles, manage your portfolio, and receive alerts on margin of safety opportunities.

## Features

- 📊 **Daily Price Tracking** — Automated fetching of NSE stock prices via yfinance + web scraping fallback
- 🧮 **Intrinsic Value Engine** — DCF, EPV, and Book Value calculations with weighted composite
- 📈 **Portfolio Management** — Track buys/sells, cost basis, P&L, and CAGR
- 🔔 **Smart Alerts** — Margin of safety triggers and custom price alerts
- 📋 **Financial Analysis** — Manual entry of company financials with saved analysis reports
- 🎯 **Buy/Sell Recommendations** — Buffett-style Strong Buy → Strong Sell ratings

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic |
| Database | PostgreSQL 16 |
| Cache/Broker | Redis 5 |
| Task Queue | Celery + Celery Beat |
| Frontend | React 18 + TypeScript + Vite + TailwindCSS *(Phase 2)* |

## Quick Start

### Prerequisites
- Python 3.12+
- PostgreSQL 16
- Redis (C:\Redis on Windows)

### Setup

```bash
# 1. Create virtual environment (already done)
python -m venv backend/venv

# 2. Install dependencies
backend\venv\Scripts\pip.exe install -r backend\requirements.txt

# 3. Configure environment
copy backend\.env.example backend\.env
# Edit .env with your database credentials

# 4. Run database migrations
cd backend && ..\backend\venv\Scripts\alembic.exe upgrade head

# 5. Start Redis
start "" C:\Redis\redis-server.exe

# 6. Start the API server
cd backend && ..\backend\venv\Scripts\uvicorn.exe app.main:app --reload --host 0.0.0.0 --port 8000
```

### API Docs
Once running, visit:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **Health Check**: http://localhost:8000/health

## Project Structure

```
StockUp/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entrypoint
│   │   ├── config.py            # Settings from .env
│   │   ├── database.py          # SQLAlchemy engine
│   │   ├── dependencies.py      # Auth dependencies
│   │   ├── models/              # SQLAlchemy models
│   │   ├── routers/             # API route handlers
│   │   ├── services/            # Business logic
│   │   ├── data/                # Data adapters (yfinance, scraper)
│   │   └── utils/               # Security, helpers
│   ├── alembic/                 # Database migrations
│   ├── tasks/                   # Celery background tasks
│   ├── tests/                   # Test suite
│   └── requirements.txt
├── frontend/                    # React app (Milestone E)
├── plans/                       # Architecture docs
├── Makefile                     # Dev commands
└── README.md
```

## Milestones

- [x] **Milestone A**: Foundation + Auth + Database
- [ ] **Milestone B**: Price Ingestion + Company Data
- [ ] **Milestone C**: Financials + Valuation + Alerts
- [ ] **Milestone D**: Portfolio + Celery Jobs
- [ ] **Milestone E**: Frontend Dashboard
