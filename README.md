# StockUp 📈

**Buffett-style stock analysis and tracking platform for the Kenyan market.**

StockUp helps you track NSE (Nairobi Securities Exchange) stock prices, calculate intrinsic values using Warren Buffett's investment principles, manage your portfolio, and receive alerts on margin of safety opportunities.

## Features

- 📊 **Daily Price Tracking** — Automated fetching of NSE stock prices from multiple sources
- 🧮 **Intrinsic Value Engine** — DCF, EPV, and Book Value calculations with weighted composite
- 📈 **Portfolio Management** — Track buys/sells, weighted average cost basis, P&L, and performance
- 🔔 **Smart Alerts** — Margin of safety triggers, price-above/below alerts with auto-evaluation
- 📋 **Financial Analysis** — Manual entry of company financials with saved analysis snapshots
- 🎯 **Buy/Sell Recommendations** — Buffett-style Strong Buy → Strong Sell ratings
- 👀 **Watchlists** — Track companies of interest with notes and current prices
- 🖥️ **React Dashboard** — Full SPA frontend with charts, portfolio tracking, and company analysis

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic |
| Database | PostgreSQL 16 |
| Cache/Broker | Redis |
| Task Queue | Celery (solo pool on Windows, prefork in production) |
| Data Sources | Marketscreener (historical primary), NSE scraper (afx.kwayisi.org), yfinance, CSV archive |
| Frontend | React 18 + TypeScript + Vite + TailwindCSS v4 + Recharts |
| Deployment | Docker Compose on a single Azure VM (Ubuntu 24.04), API exposed via SSH tunnel |

## Quick Start

### Prerequisites

- Python 3.12+
- PostgreSQL 16
- Redis (`winget install Redis.Redis` on Windows)
- Node.js 18+ (for frontend)

### 1. Backend Setup

```bash
# Create virtual environment
python -m venv backend/venv

# Install dependencies
backend\venv\Scripts\pip.exe install -r backend\requirements.txt

# Configure environment
copy backend\.env.example backend\.env
# Edit .env with your database credentials

# Run database migrations
cd backend && venv\Scripts\alembic.exe upgrade head

# Seed NSE market and companies
cd backend && venv\Scripts\python.exe -m cli.commands seed-nse

# Backfill historical prices (Marketscreener first, then scraper/yfinance fallback)
cd backend && venv\Scripts\python.exe -m cli.commands backfill-prices

# Optional: purge old kenyanstocks price rows and rebuild from Marketscreener
cd backend && venv\Scripts\python.exe -m cli.commands rebuild-marketscreener-prices
```

### 2. Frontend Setup

```bash
cd frontend
npm install
```

---

## Starting All Servers

You need **4 terminals** to run the full stack. First activate the Python virtual environment:

```bash
# Activate virtual environment (do this in each backend terminal)
cd backend
venv\Scripts\activate
```

### Terminal 1: Redis

```bash
# Windows (if installed via winget)
redis-server

# Or if Redis is at C:\Redis:
C:\Redis\redis-server.exe
```

### Terminal 2: Backend API

```bash
cd backend
venv\Scripts\activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Terminal 3: Celery Worker (background tasks)

```bash
cd backend
venv\Scripts\activate
celery -A tasks.celery_app worker --pool=solo --loglevel=info
```

### Terminal 4: Frontend Dev Server

```bash
cd frontend
npm run dev
```

### Access Points

| Service | URL |
|---------|-----|
| Frontend App | http://localhost:3000 |
| Backend API | http://localhost:8000 |
| Swagger Docs | http://localhost:8000/docs |
| ReDoc | http://localhost:8000/redoc |
| Health Check | http://localhost:8000/health |

---

## CLI Commands

```bash
cd backend

# Seed NSE market and companies
venv\Scripts\python.exe -m cli.commands seed-nse

# Backfill prices using production source order
venv\Scripts\python.exe -m cli.commands backfill-prices

# Backfill a specific company
venv\Scripts\python.exe -m cli.commands backfill-prices --ticker SCOM

# Backfill only verified Marketscreener companies
venv\Scripts\python.exe -m cli.commands backfill-marketscreener

# Purge kenyanstocks price rows, then rebuild from Marketscreener
venv\Scripts\python.exe -m cli.commands rebuild-marketscreener-prices

# Import historical CSV archive (2007-2025)
venv\Scripts\python.exe -m cli.commands import-csv --dir "C:\path\to\archive"

# Fetch today's prices
venv\Scripts\python.exe -m cli.commands update-prices-daily
```

## Testing

The project uses pytest with transaction-rollback isolation (no test data persists).

```bash
cd backend

# Run all tests (155 unit/integration tests)
venv\Scripts\python.exe -m pytest tests/ -v

# Run specific test files
venv\Scripts\python.exe -m pytest tests/test_price_fetcher.py -v
venv\Scripts\python.exe -m pytest tests/test_portfolio.py -v
venv\Scripts\python.exe -m pytest tests/test_valuation_engine.py -v
venv\Scripts\python.exe -m pytest tests/test_alerts.py -v

# Run with coverage
venv\Scripts\python.exe -m pytest tests/ --cov=app --cov-report=term-missing
```

### Test Suite Summary

| File | Tests | Covers |
|------|-------|--------|
| `test_stocks.py` | 31 | Markets, companies, prices, financials CRUD, valuations |
| `test_price_fetcher.py` | 12 | Upsert idempotency, daily fetch, Marketscreener/scraper/yfinance fallback, backfill |
| `test_valuation_engine.py` | 41 | DCF, EPV, Book Value, composite calculations, edge cases |
| `test_recommendation.py` | 22 | Recommendation engine: all rating levels, quality factors |
| `test_alerts.py` | 19 | Alert CRUD, price/MOS triggering, mark-read, inactive |
| `test_portfolio.py` | 20 | Portfolio CRUD, transactions, holdings with weighted avg, performance, dashboard |
| `test_smoke.py` | 11 | End-to-end smoke tests (requires running server) |

**Total: 155 unit/integration tests passing** ✅

## Project Structure

```
StockUp/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entrypoint
│   │   ├── config.py            # Settings from .env
│   │   ├── database.py          # SQLAlchemy engine
│   │   ├── dependencies.py      # Auth dependencies (JWT)
│   │   ├── models/              # SQLAlchemy models (10 entities)
│   │   ├── routers/             # API route handlers
│   │   │   ├── auth.py          # Registration, login, JWT refresh
│   │   │   ├── stocks.py        # Markets, companies, prices, financials
│   │   │   ├── analysis.py      # Valuations, recommendations, snapshots
│   │   │   ├── portfolio.py     # Portfolio CRUD, transactions, holdings
│   │   │   ├── alerts.py        # Alert CRUD + triggering
│   │   │   ├── watchlists.py    # Watchlist CRUD + items
│   │   │   └── dashboard.py     # Dashboard summary endpoint
│   │   ├── schemas/             # Pydantic request/response models
│   │   ├── services/            # Business logic
│   │   │   ├── valuation_engine.py    # DCF + EPV + Book Value
│   │   │   └── recommendation_engine.py # Buy/Sell ratings
│   │   ├── data/                # Data adapters
│   │   │   ├── marketscreener_adapter.py # Historical OHLCV via verified graphics URLs
│   │   │   ├── kenyanstocks_adapter.py # Legacy price adapter (not used in price backfill)
│   │   │   ├── nse_scraper.py         # afx.kwayisi.org (~10 days)
│   │   │   ├── yfinance_adapter.py    # yfinance fallback
│   │   │   ├── price_fetcher.py       # Orchestrator with priority fallback
│   │   │   └── seed_data.py           # NSE company seeder
│   │   └── utils/               # Security, helpers
│   ├── cli/                     # CLI commands (seed, backfill, import)
│   ├── tasks/                   # Celery background tasks
│   │   ├── celery_app.py        # Celery config + beat schedule
│   │   ├── price_tasks.py       # Daily price fetch + backfill tasks
│   │   ├── valuation_tasks.py   # Valuation recalculation tasks
│   │   └── alert_tasks.py       # Alert evaluation tasks
│   ├── alembic/                 # Database migrations
│   ├── tests/                   # Test suite (155 tests)
│   ├── requirements.txt
│   └── pytest.ini
├── frontend/
│   ├── src/
│   │   ├── pages/               # React pages (9 pages)
│   │   ├── components/          # Layout, Sidebar, ProtectedRoute
│   │   ├── lib/                 # API client + services
│   │   ├── store/               # Zustand auth store
│   │   └── types/               # TypeScript interfaces
│   ├── package.json
│   └── vite.config.ts
├── deploy/
│   ├── setup-vm.sh              # One-shot Azure VM bootstrap
│   └── README.md                # Deployment guide
├── plans/                       # Architecture docs
├── docker-compose.yml           # Production stack (api + worker + beat + postgres + redis)
├── .env.production.example      # Template for production secrets
├── Makefile                     # Dev commands
└── README.md
```

## Data Coverage

| Period | Source | Records |
|--------|--------|---------|
| Jan 2007 → May 6, 2025 | CSV archive import | ~247,788 |
| Historical (broad coverage) | Marketscreener (OHLCV) | rolling |
| Various (recent) | NSE scraper (afx.kwayisi.org) | ~102 |
| **Total** | **69 companies, 19 years** | **~261,097** |

Data sources are used in priority order for backfilling:
1. **Marketscreener** — Primary historical OHLCV source for companies with verified graphics URLs
2. **NSE scraper** (afx.kwayisi.org) — Recent trading days, close-focused coverage
3. **yfinance** — Additional fallback where ticker mapping is available (`.NR` suffix)

## Scheduled Tasks (Celery Beat)

| Task | Schedule | Description |
|------|----------|-------------|
| Daily Price Fetch | 6:00 PM EAT | Fetch current prices for all companies |
| Valuation Recalc | 7:00 PM EAT | Recalculate intrinsic values |
| Alert Evaluation | 7:30 PM EAT | Check and trigger user alerts |

## Deployment

The project runs in production on a single Azure VM (Ubuntu 24.04 LTS, B2s) using
Docker Compose. The API is bound to `127.0.0.1` only and accessed from a developer
laptop via SSH tunnel — there is no public ingress.

### Production stack (`docker-compose.yml`)

| Service | Image | Role |
|---------|-------|------|
| `postgres` | `postgres:16-alpine` | Primary database, persisted to a named volume |
| `redis` | `redis:7-alpine` | Celery broker + result backend |
| `api` | built from `backend/Dockerfile` | FastAPI (auto-runs `alembic upgrade head` on start) |
| `worker` | same image | Celery worker (`--concurrency=2`, prefork pool) |
| `beat` | same image | Celery beat scheduler (EAT timezone) |

The backend image is based on `mcr.microsoft.com/playwright/python:v1.52.0-jammy`
so the Marketscreener adapter's chromium fallback works without extra setup.

### Deployment files

| File | Purpose |
|------|---------|
| `backend/Dockerfile` | Image used by `api`, `worker`, and `beat` |
| `backend/.dockerignore` | Keeps venv, `.env`, and local PDF cache out of the build |
| `docker-compose.yml` | Service definitions (API bound to `127.0.0.1:8000`) |
| `.env.production.example` | Template for production secrets (copy to `.env.production` on the VM) |
| `deploy/setup-vm.sh` | One-shot bootstrap: installs Docker, UFW, unattended-upgrades, `stockup-update` helper |
| `deploy/README.md` | Step-by-step deployment, SSH tunnel, backups, cost control |

### Pushing updates

From your laptop, `git push`. On the VM, run:

```bash
stockup-update
```

That helper (installed by `deploy/setup-vm.sh`) runs `git pull` then
`docker compose up -d --build` in `~/stockup`. Compose only rebuilds layers that
changed, so most updates take seconds.

### Accessing the API from your laptop

```powershell
ssh -i StockUpVM_key.pem -L 8000:localhost:8000 stockup@<vm-public-ip>
```

While that tunnel is open:
- API docs → http://localhost:8000/docs
- Local `npm run dev` in `frontend/` talks to the tunneled API on `localhost:8000`
  (existing CORS config already allows `localhost:5173`).

See `deploy/README.md` for full details including backups, seed/backfill commands,
and cost-control tips.

## Milestones

- [x] **Milestone A**: Foundation + Auth + Database
- [x] **Milestone B**: Price Ingestion + Company Data + Tests
- [x] **Milestone C**: Financials + Valuation Engine + Alerts
- [x] **Milestone D**: Portfolio + Celery Jobs
- [x] **Milestone E**: Frontend Dashboard (React + TypeScript)
- [x] **Data Backfill**: Marketscreener-first historical ingestion with fallback sources

## API Endpoints

### Auth (`/api/auth`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/register` | Register new user |
| POST | `/login` | Login (returns JWT) |
| POST | `/refresh` | Refresh access token |
| GET | `/me` | Current user profile |

### Stocks (`/api/stocks`)
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/markets` | — | List all markets |
| GET | `/markets/{id}/companies` | — | Companies in a market |
| GET | `/companies` | — | List/search/filter companies |
| GET | `/companies/sectors` | — | Unique sector names |
| GET | `/companies/{id}` | — | Company detail + latest price/valuation |
| GET | `/companies/{id}/prices` | — | Historical prices (date range, limit) |
| GET | `/companies/{id}/financials` | — | Financial statements |
| POST | `/companies/{id}/financials` | JWT | Add financial statement |
| PUT | `/companies/{id}/financials/{fid}` | JWT | Update financial |
| DELETE | `/companies/{id}/financials/{fid}` | JWT | Delete financial |
| GET | `/companies/{id}/valuations` | — | Valuation history |
| GET | `/companies/{id}/valuations/latest` | — | Latest valuation |

### Analysis (`/api/analysis`)
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/compute` | JWT | Compute valuation for a company |
| GET | `/recommendation/{company_id}` | JWT | Get buy/sell recommendation |
| GET | `/snapshots` | JWT | List saved analysis snapshots |
| POST | `/snapshots` | JWT | Save analysis snapshot |
| GET | `/snapshots/{id}` | JWT | Get snapshot detail |
| DELETE | `/snapshots/{id}` | JWT | Delete snapshot |

### Portfolio (`/api/portfolio`)
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/` | JWT | List portfolios |
| POST | `/` | JWT | Create portfolio |
| GET | `/{id}` | JWT | Get portfolio |
| PUT | `/{id}` | JWT | Update portfolio |
| DELETE | `/{id}` | JWT | Delete portfolio |
| POST | `/{id}/transactions` | JWT | Record buy/sell |
| GET | `/{id}/transactions` | JWT | List transactions |
| GET | `/{id}/holdings` | JWT | Current holdings + cost basis |
| GET | `/{id}/performance` | JWT | P&L, total value, unrealized gains |

### Alerts (`/api/alerts`)
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/` | JWT | List alerts (filter by status) |
| POST | `/` | JWT | Create alert |
| GET | `/{id}` | JWT | Get alert |
| PUT | `/{id}` | JWT | Update alert |
| DELETE | `/{id}` | JWT | Delete alert |
| POST | `/{id}/mark-read` | JWT | Mark alert as read |

### Watchlists (`/api/watchlists`)
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/` | JWT | List watchlists |
| POST | `/` | JWT | Create watchlist |
| GET | `/{id}` | JWT | Get watchlist with items + prices |
| DELETE | `/{id}` | JWT | Delete watchlist |
| POST | `/{id}/items` | JWT | Add company to watchlist |
| PUT | `/{id}/items/{item_id}` | JWT | Update notes/target |
| DELETE | `/{id}/items/{item_id}` | JWT | Remove from watchlist |

### Dashboard (`/api/dashboard`)
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/summary` | JWT | Portfolio summary, alerts, watchlists, top undervalued |
