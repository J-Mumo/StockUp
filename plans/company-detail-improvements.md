# Company Detail Page Improvements

## Overview
Enhance the company detail page (`/companies/:id`) to surface all available financial data, valuation breakdown, and company metadata that the backend already returns but the frontend doesn't display.

## Scope
- **Frontend only** — no backend changes needed (all data already available via API)
- **One file primary**: `frontend/src/pages/CompanyDetailPage.tsx`
- **One type update**: `frontend/src/types/index.ts` (add `CompanyDetail` interface)

## Changes

### 1. Add `CompanyDetail` TypeScript Interface
**File**: `frontend/src/types/index.ts`
- Add `CompanyDetail` interface with: `description`, `website`, `industry`, `shares_outstanding`, `market_id`, `yfinance_ticker`, `latest_valuation`
- Keep existing `Company` interface for list views

### 2. Enhanced Company Header
**Section**: Top of page
- Show company description (collapsible if long)
- Show shares outstanding formatted (e.g., "3.2B shares")
- Show website as clickable link
- Show industry + sector
- Show index membership badge (NSE 20 / NSE 25)

### 3. Valuation Breakdown Panel
**Section**: Replace current 3-card grid with 6-card grid
- **Row 1**: Intrinsic Value (weighted), Margin of Safety, Market Price (existing)
- **Row 2**: DCF Value, EPV Value, Book Value (NEW — from `valuation.dcf_value`, `epv_value`, `book_value_estimate`)
- Color-code each: green if > market price, red if < market price

### 4. Valuation Assumptions Panel
**Section**: Below valuation cards, collapsible
- Display from `valuation.assumptions`: discount rate, growth rate, terminal growth, projection years
- Display from `valuation.calculation_details`: historical FCFs used, weights applied

### 5. Expanded Financial Statements Table
**Section**: Bottom of page
- Add columns: EPS, FCF, OCF, CapEx, Total Equity, BVPS, D/E, Current Ratio, DPS
- Format large numbers: B (billions), M (millions)
- Add horizontal scroll for mobile
- Add explicit Edit icon/button per row instead of linking ROE value
- Show data source badge from `notes` field: "AI", "PDF", "Manual", "Scraped"

### 6. Key Ratios Quick-View
**Section**: Between valuation and financials
- 4-card grid: P/E ratio, P/B ratio, Debt-to-Equity, Dividend Yield
- Computed client-side from latest financial + current price
- P/E = price / EPS, P/B = price / BVPS, D/Y = DPS / price

### 7. FCF & Earnings Trend Mini-Chart
**Section**: Between valuation and financials
- Small bar chart showing Revenue, Net Income, FCF side-by-side for each year
- Reuse Recharts BarChart component already imported
- Immediately shows if company is growing or declining
