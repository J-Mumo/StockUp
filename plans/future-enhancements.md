# StockUp — Future Enhancements Plan

## Phase 1: Operational Reliability (Priority: High)

### 1.1 Docker Compose Deployment
**Goal:** One-command deployment of the full stack.

- `docker-compose.yml` with services: `api`, `worker`, `beat`, `redis`, `postgres`, `frontend`
- Nginx reverse proxy for frontend + API
- Health checks and restart policies
- Environment variable management via `.env`
- **Effort:** 1 day

### 1.2 Daily Price Auto-Updates (Production)
**Goal:** Prices update automatically every trading day without manual intervention.

- Ensure Celery Beat schedule for `fetch_all_prices` runs Mon-Fri at 5PM EAT (after market close)
- Add retry logic with exponential backoff for transient network failures
- Add dead-letter queue for permanently failed fetches
- Send daily summary email: "X prices updated, Y failed"
- **Effort:** 0.5 day

### 1.3 Data Quality Monitoring
**Goal:** Detect stale/missing data before users notice.

- Admin endpoint `/api/admin/data-health` showing:
  - Companies with no price data in >3 days
  - Companies with no financials
  - Companies with no valuation
  - Last successful fetch timestamps
- Weekly email digest to admin
- **Effort:** 0.5 day

---

## Phase 2: User Experience (Priority: Medium-High)

### 2.1 Historical Valuation Trends
**Goal:** Show how a company's intrinsic value and MoS have changed over time.

- Backend: Query `intrinsic_values` table for a company over time
- Frontend: Line chart on Company Detail page showing IV vs Market Price over 12 months
- Visual "buy zone" overlay (green band below IV line)
- **Effort:** 1 day

### 2.2 Sector Analysis Dashboard
**Goal:** Compare companies within the same sector.

- New page `/sectors/:sectorName`
- Scatter plot: MoS vs ROE for all companies in sector
- Table ranking: Best value picks per sector
- Sector averages for P/E, P/B, ROE
- **Effort:** 1.5 days

### 2.3 Email/Push Notifications for Alerts
**Goal:** Users get notified when alerts trigger, not just in-app.

- Add `notification_channel` field to Alert model (email, push, in-app)
- Celery task sends email via SendGrid/SMTP when alert triggers
- Web push notifications using service worker + VAPID keys
- User preferences page for notification settings
- **Effort:** 2 days

### 2.4 Company Detail Page Enhancements
**Goal:** Richer analysis view per company.

- Financial statements as interactive charts (revenue/profit trend bars)
- Peer comparison table (same sector companies side-by-side)
- Dividend yield history and payout ratio
- Key ratios dashboard (P/E, P/B, D/E, Current Ratio) with traffic-light indicators
- **Effort:** 2 days

---

## Phase 3: Advanced Analytics (Priority: Medium)

### 3.1 Portfolio Optimization Suggestions
**Goal:** Help users build diversified, undervalued portfolios.

- "Portfolio Score" metric based on concentration risk, sector diversity, average MoS
- "Suggested Rebalance" — recommend sells (overvalued) and buys (undervalued)
- Risk-adjusted returns using Sharpe-like ratio
- **Effort:** 2 days

### 3.2 Earnings & Financials Calendar
**Goal:** Track when companies report earnings.

- Scrape/maintain earnings announcement dates
- Calendar view showing upcoming reports
- Auto-refresh financials within 7 days of reported earnings
- **Effort:** 1.5 days

### 3.3 Custom Valuation Parameters
**Goal:** Let advanced users adjust DCF/EPV assumptions per company.

- UI sliders for discount rate, growth rate, projection years
- Real-time IV recalculation as parameters change
- "Save as scenario" feature for comparison
- **Effort:** 1.5 days

### 3.4 Screening & Filtering Tool
**Goal:** Power-user stock screener.

- Multi-criteria filter: MoS > X%, ROE > Y%, D/E < Z, Sector = ..., Price < ...
- Save screen criteria as presets
- Export results to CSV
- **Effort:** 1.5 days

---

## Phase 4: Data & Coverage (Priority: Medium)

### 4.1 Fill Missing shares_outstanding Data
**Goal:** Enable valuations for remaining 26 companies.

- Research alternative sources (Capital Markets Authority reports, annual reports)
- Manual data entry UI for admin users
- Fallback: estimate from market cap / price when available
- **Effort:** 1 day

### 4.2 Dividend Data Integration
**Goal:** Track dividend yields for income investors.

- Scrape dividend history from kenyanstocks.com or NSE announcements
- Add `dividend_yield` to company list response
- Dividend-adjusted total return in portfolio performance
- **Effort:** 1 day

### 4.3 News & Announcements Feed
**Goal:** Surface market-moving news alongside analysis.

- Scrape NSE corporate announcements RSS/page
- Display recent news on Company Detail page
- Highlight companies with recent announcements on Companies page
- **Effort:** 1.5 days

---

## Phase 5: Production Hardening (Priority: Low-Medium)

### 5.1 API Rate Limiting & Caching
- Redis-based rate limiting (100 req/min per user)
- Cache company list and sector list (5-min TTL)
- Cache valuation results until next computation
- **Effort:** 0.5 day

### 5.2 Comprehensive Test Coverage
- Integration tests for all frontend pages (Playwright/Cypress)
- Load testing for API endpoints (locust)
- CI/CD pipeline (GitHub Actions: lint, test, build, deploy)
- **Effort:** 2 days

### 5.3 Mobile App (React Native)
- Share API backend with web frontend
- Push notifications native integration
- Offline portfolio viewing
- **Effort:** 5-7 days

### 5.4 Multi-Market Expansion
- Add support for other African exchanges (Uganda, Tanzania, Rwanda)
- Adapt scraper architecture for different data sources per market
- Currency conversion for cross-market comparison
- **Effort:** 3-5 days

---

## Implementation Priority Matrix

| Phase | Impact | Effort | Start After |
|-------|--------|--------|-------------|
| 1.1 Docker Compose | High | 1 day | Now |
| 1.2 Daily Prices | High | 0.5 day | Phase 1.1 |
| 2.1 Valuation Trends | High | 1 day | Now |
| 2.3 Email Notifications | High | 2 days | Phase 1.1 |
| 2.2 Sector Analysis | Medium | 1.5 days | Phase 2.1 |
| 3.4 Stock Screener | High | 1.5 days | Phase 2 |
| 4.1 Fill shares_outstanding | Medium | 1 day | Now |
| 3.1 Portfolio Optimization | Medium | 2 days | Phase 3 |
| 5.2 Test Coverage + CI/CD | Medium | 2 days | Phase 1.1 |

**Recommended next sprint:** Phase 1 (Docker + Daily Prices) + Enhancement 2.1 (Valuation Trends) + 4.1 (Fill missing data)
