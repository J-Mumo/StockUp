# StockUp — Buffett-Style Stock Analysis Platform
## Unified Architecture & Implementation Plan

---

## Overview

StockUp is a web application that tracks Kenyan stock market prices and provides Warren Buffett-style investment analysis. It fetches historical and daily prices from the NSE via yfinance (with web scraping as fallback), calculates intrinsic values using DCF/EPV/Book Value methods, manages user portfolios, and provides buy/sell/hold recommendations with margin of safety alerts.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.12+, FastAPI, SQLAlchemy 2.x, Alembic |
| **Frontend** | React 18+ with TypeScript, Vite, TailwindCSS |
| **Database** | PostgreSQL 16 - native local install |
| **Cache / Broker** | Redis - native local install |
| **Task Queue** | Celery with Redis broker, Celery Beat scheduler |
| **Data Sources** | yfinance - primary, BeautifulSoup4 scraper - fallback |
| **Auth** | JWT via python-jose + passlib |
| **Charts** | Recharts for React |
| **API Docs** | FastAPI built-in OpenAPI / Swagger UI |
| **Testing** | pytest, httpx for async tests, factory-boy |
| **Dev Automation** | Makefile or PowerShell scripts for common commands |

---

## System Architecture

```mermaid
graph TB
    subgraph External Data
        YF[yfinance API - Primary]
        NSE[afx.kwayisi.org - Fallback Scraper]
    end

    subgraph Scheduled Jobs - Celery
        FETCH[Daily Price Fetcher]
        CALC[Intrinsic Value Calculator]
        ALERT[Alert Generator]
    end

    subgraph Backend - FastAPI
        API[REST API Routers]
        AUTH[JWT Authentication]
        ORM[SQLAlchemy Models]
        SCRAPER[Data Adapter Layer]
        VALUATION[Valuation Engine]
        RECOMMEND[Recommendation Engine]
    end

    subgraph Data Layer - Native Local
        PG[(PostgreSQL)]
        REDIS[(Redis)]
    end

    subgraph Frontend - React - Built After Backend MVP
        DASH[Dashboard]
        PORT[Portfolio Manager]
        ANAL[Analysis Views]
        ALERTS_UI[Alerts Panel]
        STOCK[Stock Detail + Charts]
    end

    YF -->|price data| SCRAPER
    NSE -->|fallback scrape| SCRAPER
    SCRAPER --> ORM
    ORM --> PG

    FETCH -->|triggers| SCRAPER
    CALC -->|reads prices + financials| PG
    CALC -->|uses| VALUATION
    CALC -->|writes valuations| PG
    ALERT -->|reads valuations vs holdings| PG
    ALERT -->|creates notifications| PG

    REDIS -->|task broker| FETCH
    REDIS -->|task broker| CALC
    REDIS -->|task broker| ALERT

    DASH -->|HTTP| API
    PORT -->|HTTP| API
    ANAL -->|HTTP| API
    ALERTS_UI -->|HTTP| API
    STOCK -->|HTTP| API

    API --> AUTH
    API --> ORM
    API --> VALUATION
    API --> RECOMMEND
```

---

## Data Flow

```mermaid
sequenceDiagram
    participant Beat as Celery Beat
    participant Fetcher as Price Fetcher Task
    participant YF as yfinance
    participant Scraper as NSE Scraper - Fallback
    participant DB as PostgreSQL
    participant ValEngine as Valuation Engine
    participant AlertSvc as Alert Service
    participant User as User via React

    Beat->>Fetcher: Trigger daily price fetch
    Fetcher->>YF: Request latest NSE prices
    alt yfinance succeeds
        YF-->>Fetcher: Price data
    else yfinance fails
        Fetcher->>Scraper: Fallback to web scraping
        Scraper-->>Fetcher: Scraped price data
    end
    Fetcher->>DB: Idempotent upsert prices

    Beat->>ValEngine: Trigger valuation recalculation
    ValEngine->>DB: Read prices + financial statements
    ValEngine->>ValEngine: Compute DCF + EPV + Book Value
    ValEngine->>DB: Store valuation snapshots with explanations

    Beat->>AlertSvc: Evaluate margin of safety thresholds
    AlertSvc->>DB: Read user alerts config + valuations
    AlertSvc->>DB: Create triggered alert records

    User->>DB: View dashboard, portfolio, alerts via API
```

---

## Database Schema

### Entity Relationship Diagram

```mermaid
erDiagram
    Market ||--o{ Company : contains
    Company ||--o{ PriceHistory : has
    Company ||--o{ FinancialStatement : has
    Company ||--o{ IntrinsicValue : has
    User ||--o{ Portfolio : owns
    Portfolio ||--o{ PortfolioTransaction : contains
    Company ||--o{ PortfolioTransaction : references
    User ||--o{ Alert : receives
    Company ||--o{ Alert : about
    User ||--o{ Watchlist : has
    Watchlist ||--o{ WatchlistItem : contains
    Company ||--o{ WatchlistItem : references
    User ||--o{ AnalysisSnapshot : creates
    Company ||--o{ AnalysisSnapshot : about

    Market {
        int id PK
        string name
        string code
        string country
        string currency
        boolean is_active
        datetime created_at
        datetime updated_at
    }

    Company {
        int id PK
        int market_id FK
        string name
        string ticker_symbol
        string yfinance_ticker
        string sector
        string industry
        text description
        string website
        bigint shares_outstanding
        boolean is_active
        datetime created_at
        datetime updated_at
    }

    PriceHistory {
        int id PK
        int company_id FK
        date price_date
        decimal open_price
        decimal high_price
        decimal low_price
        decimal close_price
        bigint volume
        decimal change_percent
        string source
        datetime fetched_at
    }

    FinancialStatement {
        int id PK
        int company_id FK
        int fiscal_year
        string period_type
        decimal revenue
        decimal net_income
        decimal earnings_per_share
        decimal book_value_per_share
        decimal total_assets
        decimal total_liabilities
        decimal total_equity
        decimal shareholders_equity
        decimal operating_cash_flow
        decimal capital_expenditures
        decimal free_cash_flow
        decimal dividends_per_share
        decimal return_on_equity
        decimal debt_to_equity
        decimal current_ratio
        text notes
        date report_date
        int entered_by_user_id FK
        datetime created_at
        datetime updated_at
    }

    IntrinsicValue {
        int id PK
        int company_id FK
        date valuation_date
        decimal dcf_value
        decimal epv_value
        decimal book_value_estimate
        decimal weighted_intrinsic_value
        decimal current_market_price
        decimal margin_of_safety_pct
        string recommendation
        string recommendation_reason
        json assumptions
        json calculation_details
        datetime calculated_at
    }

    User {
        int id PK
        string email
        string hashed_password
        string first_name
        string last_name
        boolean is_active
        datetime created_at
        datetime updated_at
    }

    Portfolio {
        int id PK
        int user_id FK
        string name
        text description
        decimal initial_capital
        string currency
        datetime created_at
        datetime updated_at
    }

    PortfolioTransaction {
        int id PK
        int portfolio_id FK
        int company_id FK
        string transaction_type
        decimal quantity
        decimal price_per_share
        decimal total_amount
        decimal fees
        date transaction_date
        text notes
        datetime created_at
    }

    Alert {
        int id PK
        int user_id FK
        int company_id FK
        string alert_type
        string condition
        decimal threshold_value
        boolean is_active
        boolean is_triggered
        boolean is_read
        text message
        datetime triggered_at
        datetime created_at
    }

    Watchlist {
        int id PK
        int user_id FK
        string name
        datetime created_at
    }

    WatchlistItem {
        int id PK
        int watchlist_id FK
        int company_id FK
        decimal target_buy_price
        decimal target_sell_price
        text notes
        datetime added_at
    }

    AnalysisSnapshot {
        int id PK
        int company_id FK
        int user_id FK
        string title
        string analysis_type
        text analysis_text
        json data_snapshot
        json valuation_at_time
        datetime created_at
    }
```

### Key Indexes

| Table | Columns | Purpose |
|-------|---------|---------|
| `price_history` | `company_id, price_date` - unique | Fast date-range lookups, prevent duplicates |
| `price_history` | `price_date` | Date-based queries across all companies |
| `intrinsic_values` | `company_id, valuation_date` | Valuation history lookups |
| `portfolio_transactions` | `portfolio_id, transaction_date` | Portfolio history queries |
| `financial_statements` | `company_id, fiscal_year` | Financial data retrieval |
| `alerts` | `user_id, is_triggered, is_read` | Unread alert queries |
| `companies` | `ticker_symbol` - unique | Ticker lookups |
| `companies` | `yfinance_ticker` - unique | yfinance integration |

---

## API Endpoints

### Auth Router - `/api/auth`
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/register` | Register new user |
| POST | `/login` | Login - returns JWT access + refresh tokens |
| POST | `/refresh` | Refresh access token |
| GET | `/me` | Get current user profile |
| PUT | `/me` | Update user profile |

### Stocks Router - `/api/stocks`
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/markets` | List all markets |
| GET | `/markets/{market_id}/companies` | List companies in a market |
| GET | `/companies` | List all companies - search, filter by sector |
| GET | `/companies/{id}` | Company detail with latest price + valuation |
| GET | `/companies/{id}/prices` | Historical prices - query params: start, end, interval |
| GET | `/companies/{id}/financials` | Financial statements for a company |
| POST | `/companies/{id}/financials` | Add financial statement - manual entry |
| PUT | `/companies/{id}/financials/{fid}` | Update financial statement |
| DELETE | `/companies/{id}/financials/{fid}` | Delete financial statement |
| GET | `/companies/{id}/valuations` | Intrinsic value history |
| GET | `/companies/{id}/valuations/latest` | Latest valuation with explanation |

### Portfolio Router - `/api/portfolio`
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | List user portfolios |
| POST | `/` | Create a new portfolio |
| GET | `/{id}` | Portfolio detail with current holdings |
| PUT | `/{id}` | Update portfolio info |
| DELETE | `/{id}` | Delete portfolio |
| POST | `/{id}/transactions` | Record a buy or sell transaction |
| GET | `/{id}/transactions` | Transaction history |
| GET | `/{id}/holdings` | Current holdings with cost basis |
| GET | `/{id}/performance` | Performance metrics: P and L, CAGR, allocation |

### Analysis Router - `/api/analysis`
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/dashboard` | Dashboard summary: portfolio, top picks, alerts |
| GET | `/recommendations` | All buy/sell/hold recommendations with reasons |
| GET | `/recommendations/{company_id}` | Deep analysis for one company |
| POST | `/snapshots` | Save an analysis snapshot |
| GET | `/snapshots` | List saved snapshots |
| GET | `/snapshots/{id}` | Get snapshot detail |
| DELETE | `/snapshots/{id}` | Delete snapshot |

### Alerts Router - `/api/alerts`
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | List user alerts - filter: active, triggered, read |
| POST | `/` | Create custom alert |
| PUT | `/{id}` | Update alert config |
| PUT | `/{id}/read` | Mark alert as read |
| DELETE | `/{id}` | Delete alert |

### Watchlist Router - `/api/watchlists`
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | List user watchlists |
| POST | `/` | Create watchlist |
| GET | `/{id}` | Watchlist detail with items |
| DELETE | `/{id}` | Delete watchlist |
| POST | `/{id}/items` | Add company to watchlist |
| PUT | `/{id}/items/{iid}` | Update target prices or notes |
| DELETE | `/{id}/items/{iid}` | Remove company from watchlist |

### Admin / CLI Commands
| Command | Description |
|---------|-------------|
| `backfill-prices` | Fetch historical prices for all companies |
| `update-prices-daily` | Fetch today's prices |
| `recalculate-valuations` | Recompute all intrinsic values |
| `seed-nse-companies` | Seed NSE market and company universe |

---

## Project Structure

```
StockUp/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                    # FastAPI app entrypoint
│   │   ├── config.py                  # Settings from .env
│   │   ├── database.py                # SQLAlchemy engine and session
│   │   ├── dependencies.py            # Shared dependencies - get_db, get_current_user
│   │   ├── routers/
│   │   │   ├── __init__.py
│   │   │   ├── auth.py
│   │   │   ├── stocks.py
│   │   │   ├── portfolio.py
│   │   │   ├── analysis.py
│   │   │   ├── alerts.py
│   │   │   └── watchlists.py
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── market.py
│   │   │   ├── company.py
│   │   │   ├── price_history.py
│   │   │   ├── financial_statement.py
│   │   │   ├── intrinsic_value.py
│   │   │   ├── user.py
│   │   │   ├── portfolio.py
│   │   │   ├── alert.py
│   │   │   ├── watchlist.py
│   │   │   └── analysis_snapshot.py
│   │   ├── schemas/                    # Pydantic request/response models
│   │   │   ├── __init__.py
│   │   │   ├── auth.py
│   │   │   ├── stocks.py
│   │   │   ├── portfolio.py
│   │   │   ├── analysis.py
│   │   │   ├── alerts.py
│   │   │   └── watchlists.py
│   │   ├── services/                   # Business logic layer
│   │   │   ├── __init__.py
│   │   │   ├── auth_service.py
│   │   │   ├── stock_service.py
│   │   │   ├── portfolio_service.py
│   │   │   ├── valuation_engine.py     # DCF, EPV, Book Value calculations
│   │   │   ├── recommendation_engine.py # Buy/sell/hold logic
│   │   │   ├── alert_service.py
│   │   │   └── analysis_service.py
│   │   ├── data/                       # Data ingestion layer
│   │   │   ├── __init__.py
│   │   │   ├── yfinance_adapter.py     # Primary data source
│   │   │   ├── nse_scraper.py          # Fallback scraper
│   │   │   ├── price_fetcher.py        # Orchestrates adapters with fallback
│   │   │   └── seed_data.py            # NSE companies seed
│   │   └── utils/
│   │       ├── __init__.py
│   │       ├── security.py             # Password hashing, JWT creation
│   │       └── helpers.py              # Common utilities
│   ├── alembic/                        # Database migrations
│   │   ├── alembic.ini
│   │   ├── env.py
│   │   └── versions/
│   ├── tasks/                          # Celery tasks
│   │   ├── __init__.py
│   │   ├── celery_app.py              # Celery configuration
│   │   ├── price_tasks.py             # Daily price fetch task
│   │   ├── valuation_tasks.py         # Valuation recalculation task
│   │   └── alert_tasks.py            # Alert evaluation task
│   ├── cli/                           # CLI commands
│   │   ├── __init__.py
│   │   └── commands.py               # backfill-prices, seed-nse, etc.
│   ├── tests/
│   │   ├── __init__.py
│   │   ├── conftest.py               # Fixtures: test DB, test client, factories
│   │   ├── test_auth.py
│   │   ├── test_stocks.py
│   │   ├── test_portfolio.py
│   │   ├── test_valuation_engine.py  # Critical: unit tests for math
│   │   ├── test_recommendation.py
│   │   ├── test_alerts.py
│   │   └── test_price_fetcher.py
│   ├── requirements.txt
│   ├── .env.example
│   └── Makefile                      # Common commands
├── frontend/                          # Built after backend MVP - Milestone E
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── tailwind.config.js
│   ├── index.html
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── api/                      # API client using axios or fetch
│   │   │   ├── client.ts             # Base HTTP client with JWT interceptor
│   │   │   ├── auth.ts
│   │   │   ├── stocks.ts
│   │   │   ├── portfolio.ts
│   │   │   ├── analysis.ts
│   │   │   ├── alerts.ts
│   │   │   └── watchlists.ts
│   │   ├── components/
│   │   │   ├── layout/               # Navbar, Sidebar, Footer
│   │   │   ├── charts/               # Price charts, performance graphs
│   │   │   ├── stocks/               # Company cards, tables, detail
│   │   │   ├── portfolio/            # Holdings table, transaction forms
│   │   │   ├── analysis/             # Valuation displays, recommendations
│   │   │   └── common/               # Buttons, inputs, modals, loading
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx
│   │   │   ├── Login.tsx
│   │   │   ├── Register.tsx
│   │   │   ├── Companies.tsx
│   │   │   ├── CompanyDetail.tsx
│   │   │   ├── Portfolio.tsx
│   │   │   ├── PortfolioDetail.tsx
│   │   │   ├── Analysis.tsx
│   │   │   ├── Alerts.tsx
│   │   │   ├── Watchlist.tsx
│   │   │   └── FinancialEntry.tsx
│   │   ├── hooks/                    # Custom React hooks
│   │   ├── store/                    # Zustand or React Context
│   │   ├── types/                    # TypeScript interfaces
│   │   └── utils/                    # Formatters, helpers
│   └── public/
├── scripts/                          # Setup and utility scripts
│   ├── setup_db.ps1                  # Create PostgreSQL database
│   ├── setup_db.sh                   # Linux/Mac version
│   └── smoke_test.py                 # End-to-end daily workflow test
├── .env.example
├── .gitignore
├── README.md
└── plans/
    └── architecture.md               # This file
```

---

## Intrinsic Value Calculation Methods

### 1. Discounted Cash Flow - DCF
The core Buffett valuation method:

$$V = \sum_{t=1}^{n} \frac{FCF_t}{(1 + r)^t} + \frac{FCF_n \times (1 + g)}{(r - g) \times (1 + r)^n}$$

Where:
- $FCF_t$ = Free Cash Flow in year $t$ - projected from historical trend
- $r$ = Discount rate - typically 10-15% for Kenyan market
- $g$ = Terminal growth rate - typically 2-4%
- $n$ = Projection period - typically 10 years

**Conservative approach**: Use lower growth rates and higher discount rates to build in natural margin of safety.

### 2. Earnings Power Value - EPV

$$EPV = \frac{\text{Adjusted Normalized Earnings}}{\text{Cost of Capital}}$$

Uses normalized, sustainable earnings rather than projecting growth. Better for stable, mature companies. Adjustments include removing one-time items and averaging earnings over 5+ years.

### 3. Book Value Analysis

$$\text{Book Value Per Share} = \frac{\text{Total Equity}}{\text{Shares Outstanding}}$$

Compare market price to book value. Buffett looks for companies trading near or below book value with strong ROE consistently above 15%.

### 4. Weighted Intrinsic Value

$$\text{Weighted IV} = w_1 \times DCF + w_2 \times EPV + w_3 \times BV$$

Default weights: $w_1 = 0.5$ - DCF, $w_2 = 0.3$ - EPV, $w_3 = 0.2$ - Book Value

Weights are configurable per company. For companies with volatile cash flows, EPV may be weighted higher.

### 5. Margin of Safety

$$\text{MOS} = 1 - \frac{\text{Market Price}}{\text{Intrinsic Value}}$$

A positive MOS means the stock is undervalued. Alert when MOS exceeds user-defined threshold - default 30%.

---

## Recommendation Engine Logic

| Condition | Recommendation | Reason |
|-----------|---------------|--------|
| MOS > 30% AND ROE > 15% AND D/E < 0.5 | **Strong Buy** | Undervalued, high quality, low debt |
| MOS > 30% AND ROE > 15% | **Buy** | Undervalued with high returns |
| MOS > 30% | **Buy** | Undervalued |
| MOS 10-30% AND ROE > 15% | **Accumulate** | Fairly valued but high quality |
| MOS 0-10% | **Hold** | Fairly valued |
| MOS -10% to 0% | **Hold / Trim** | Slightly overvalued |
| MOS < -10% AND < -20% | **Sell** | Overvalued |
| MOS < -20% | **Strong Sell** | Significantly overvalued |

### Additional Quality Factors
Each recommendation includes an explanation payload:
- Debt-to-equity ratio trend - prefer < 0.5
- Consistent earnings growth over 5+ years
- Dividend history and payout consistency
- Free cash flow trend - positive and growing
- Return on equity consistency
- Current ratio for liquidity

---

## Scheduled Jobs

| Job | Schedule | Description |
|-----|----------|-------------|
| `fetch_daily_prices` | Daily at 6:00 PM EAT - after NSE close at 3PM | Fetch latest prices via yfinance + fallback |
| `recalculate_valuations` | Daily at 7:00 PM EAT | Recompute intrinsic values for all companies |
| `evaluate_alerts` | Daily at 7:30 PM EAT | Check MOS thresholds and trigger alerts |
| `backfill_prices` | On demand via CLI | Backfill historical price data |

### Retry Policy
- Each task retries up to 3 times with exponential backoff
- Failed tasks logged to `task_run_log` table for monitoring
- Idempotent upsert logic prevents duplicate price records

---

## Configuration - .env

```
# Database
DATABASE_URL=postgresql://stockup:stockup@localhost:5432/stockup

# Redis
REDIS_URL=redis://localhost:6379/0

# JWT
JWT_SECRET_KEY=your-secret-key-here
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7

# App
APP_NAME=StockUp
APP_ENV=development
APP_DEBUG=true
APP_PORT=8000

# Data Sources
YFINANCE_ENABLED=true
SCRAPER_ENABLED=true
SCRAPER_BASE_URL=https://afx.kwayisi.org/ngse/

# Scheduled Jobs
PRICE_FETCH_HOUR=18
VALUATION_CALC_HOUR=19
ALERT_EVAL_HOUR=19
ALERT_EVAL_MINUTE=30
```

---

## Milestones and Delivery Order

### Milestone A: Foundation + Auth + Database
1. Create project structure for `backend/`, `frontend/`, `scripts/`, `plans/`
2. Initialize Python project with FastAPI, SQLAlchemy, Alembic, Celery, Redis client, pytest
3. Add `.env`-based configuration
4. Add `requirements.txt` and `Makefile` for common commands
5. Install and configure PostgreSQL locally - create database and user
6. Install and configure Redis locally
7. Build FastAPI app entrypoint with modular routers
8. Implement SQLAlchemy models for all entities
9. Create Alembic migrations
10. Implement JWT auth: register, login, me, refresh
11. Add API error handling and logging middleware
12. Verify connectivity: health endpoint + DB ping + Redis ping
13. Write tests for auth flow

### Milestone B: Price Ingestion + Company Data
14. Seed NSE market and company universe with yfinance ticker mappings
15. Build yfinance adapter for NSE tickers
16. Build fallback NSE scraper adapter
17. Build `price_fetcher.py` orchestrator with fallback logic
18. Implement idempotent upsert logic for prices
19. Add CLI commands: `backfill-prices`, `update-prices-daily`, `seed-nse-companies`
20. Build stocks API endpoints: markets, companies, prices
21. Backfill historical prices for all NSE companies
22. Write tests for price fetcher and stock endpoints

### Milestone C: Financials + Valuation + Alerts
23. Build financial statement model and manual entry API
24. Implement DCF valuation calculator
25. Implement EPV valuation calculator
26. Implement Book Value estimation
27. Build weighted intrinsic value composite
28. Implement margin of safety calculation
29. Store daily valuation snapshots with explanation payloads
30. Build recommendation engine with quality factors
31. Build alerts model and API: create, list, trigger, read, delete
32. Build analysis snapshots API for saving reports
33. Write unit tests for valuation math - critical
34. Write tests for recommendation logic
35. Write tests for alert triggering

### Milestone D: Portfolio + Celery Jobs
36. Build portfolio model and API: create, list, detail
37. Build transaction-based holdings: buy/sell events
38. Implement current holdings with cost basis calculation
39. Implement performance metrics: unrealized/realized P and L, CAGR, allocation
40. Build watchlist model and API
41. Configure Celery with Redis broker
42. Create scheduled tasks: daily price fetch, valuation calc, alert eval
43. Configure Celery Beat scheduler for daily runs
44. Add retry policy and task run logging
45. Build dashboard summary endpoint
46. Write integration tests for portfolio calculations
47. Create end-to-end smoke test script

### Milestone E: Frontend Dashboard
48. Scaffold React + TypeScript + Vite + TailwindCSS app
49. Set up API client with JWT interceptor
50. Build auth flow: Login, Register pages
51. Build Dashboard page: portfolio summary, recommendations, alerts
52. Build Companies page: list with search and filters
53. Build Company Detail page: price chart, financials, valuation, analysis
54. Build Financial Entry page: forms for income, balance sheet, cash flow
55. Build Portfolio page: holdings, transactions, performance charts
56. Build Alerts page: active alerts, alert configuration
57. Build Watchlist page
58. Add error handling and loading states throughout
59. Polish UI, responsive design, final testing

---

## Testing Strategy

| Test Type | Scope | Tools |
|-----------|-------|-------|
| **Unit Tests** | Valuation math, MOS calc, recommendation logic, cost basis | pytest |
| **Integration Tests** | API endpoints + DB operations, auth flows | pytest + httpx + test DB |
| **Task Tests** | Celery tasks including retries and error handling | pytest + celery test utils |
| **Smoke Test** | Full daily workflow end-to-end | Custom script in `scripts/smoke_test.py` |

### Critical Test Cases
- DCF calculation with known inputs produces expected output
- EPV with normalized earnings matches hand-calculated result
- Portfolio P and L after buy + partial sell is correct
- CAGR calculation over known period matches expected
- Alert triggers when MOS crosses threshold
- Price upsert is truly idempotent - no duplicates
- yfinance failure correctly falls back to scraper
