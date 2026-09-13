# Learn Mode — Stocks Education In-Context

## Problem

StockUp already surfaces the vocabulary of professional equity analysis —
DCF Value, EPV, Book Value, Margin of Safety, ROE, D/E, Current Ratio, EPS,
FCF, DPS, P/E, P/B, NPL Ratio, CAR, Cost-to-Income, 4-D scorecard axes
(Valuation / Quality / Trend / Position), Composite Score, and more.

For someone learning to invest, these labels are opaque. Users end up
reading a company page, seeing "DCF Value KES 42.10, EPV Value KES 38.60,
Margin of Safety +12%" and not knowing:

- **What does this number *mean*** in plain English?
- **What does high vs low signal** about the business?
- **What's a healthy range** for this sector?
- **Which metric should I trust more** for this kind of company (bank vs
  industrial)?
- **How does this stock compare** on this metric to peers / sector median?

We want StockUp to be usable as a *learning tool on the go* — every number
you see should be one tap away from a short, sector-aware explanation.

## Goal

Add a **Learn Mode** layer that:

1. Attaches a discoverable "info" affordance to every displayed metric.
2. Reveals a short explanation on hover (desktop) or tap (mobile).
3. Optionally expands into a fuller "learn card" with rule-of-thumb ranges,
   what high/low means, common pitfalls, and a link to peer comparison.
4. Is **sector-aware**: bank users see CAR / NPL context, industrial users
   see FCF / D/E context.
5. Is **contextualised**: when opened on a specific company, the card shows
   *that company's* value alongside the interpretation ("KCB's NPL of 15.2%
   is elevated vs the tier-1 bank median of 8%").
6. Ships as a browsable **`/learn` glossary page** so users can also study
   without opening a company.

Explicit non-goals for v1:

- No interactive quizzes / lessons / progress tracking.
- No video or long-form content — every explanation fits in ≤ 6 lines.
- No new financial models; we only annotate what already exists.

## Scope

- **Frontend-heavy**. All copy lives in the frontend as static content.
- **One thin backend addition** (optional, v1.5): a peer-comparison endpoint
  so the learn card can show "sector median" values. If skipped, we compute
  the median client-side from the existing `/companies` list.
- No DB migrations, no new models, no changes to valuation math.

## Architecture

### 1. Central Metric Registry — single source of truth

**File:** `frontend/src/lib/metrics/registry.ts`

Every metric that appears anywhere in the UI is registered here with a
stable `key`, short label, one-line summary, longer explanation, sector
applicability, and interpretation rules.

```ts
export type MetricSector = 'all' | 'bank' | 'insurance' | 'industrial' | 'reit';

export type MetricUnit = 'currency' | 'percent' | 'ratio' | 'multiple' | 'count' | 'years';

export interface MetricThreshold {
  // Ranges are lower-bound inclusive. verdict maps to a color.
  min: number | null;   // null = -∞
  max: number | null;   // null = +∞
  verdict: 'good' | 'ok' | 'caution' | 'bad';
  note?: string;        // "Below regulatory minimum" etc.
}

export interface MetricDefinition {
  key: string;                        // e.g. 'dcf_value', 'npl_ratio'
  label: string;                      // "DCF Value"
  short_label?: string;               // "DCF" for tight spaces
  unit: MetricUnit;
  sectors: MetricSector[];            // where this metric is meaningful
  category: 'valuation' | 'profitability' | 'solvency' | 'liquidity'
          | 'growth' | 'efficiency' | 'risk' | 'income' | 'scorecard';

  // Learn-mode copy
  one_liner: string;                  // ≤ 90 chars, shown in tooltip
  what_it_measures: string;           // 1-2 sentences
  how_its_calculated: string;         // 1-2 sentences, plain English
  what_high_means: string;
  what_low_means: string;
  watch_outs: string[];               // ["Sensitive to discount rate", ...]
  rule_of_thumb?: string;             // "For NSE banks, a healthy CAR is > 14.5%"

  // Interpretation
  higher_is_better: boolean | 'context'; // 'context' e.g. for P/E
  thresholds?: MetricThreshold[];     // used to color the value

  // Cross-links
  related_metrics?: string[];         // other keys
  learn_more_anchor?: string;         // deep-link into /learn page
}
```

Seed set for v1 (≈ 25 metrics):

- **Valuation:** `dcf_value`, `epv_value`, `book_value_estimate`,
  `weighted_intrinsic_value`, `margin_of_safety_pct`, `pe_ratio`, `pb_ratio`,
  `dividend_yield`, `iv_confidence`.
- **Profitability:** `return_on_equity`, `net_income`, `earnings_per_share`,
  `revenue`.
- **Solvency / Liquidity:** `debt_to_equity`, `current_ratio`,
  `book_value_per_share`.
- **Cash flow:** `operating_cash_flow`, `free_cash_flow`,
  `capital_expenditures`, `dividends_per_share`.
- **Bank-specific:** `npl_ratio`, `capital_adequacy_ratio` (CAR),
  `cost_to_income_ratio`, `cost_of_risk`.
- **Scorecard axes:** `dim_valuation`, `dim_quality`, `dim_trend`,
  `dim_position`, `composite_score`.

Each entry is ~30 lines of TypeScript. Total registry ≈ 800 lines,
kept in one file for grep-ability; can be split by category later.

### 2. Reusable `MetricLabel` component

**File:** `frontend/src/components/learn/MetricLabel.tsx`

Drop-in replacement for the plain `<p className="text-xs text-gray-400">`
labels used across `CompanyDetailPage`, `RecommendationScorecard`,
`DashboardPage`, `PortfolioPage`, and `CompaniesPage` table headers.

```tsx
<MetricLabel metricKey="dcf_value" />
// renders: "DCF Value ⓘ" with a hover/tap-triggered tooltip
```

Props:

- `metricKey: string` (required)
- `value?: number | null` — enables color-coded verdict badge + contextual
  interpretation ("This company's ROE of 22% is above the sector median")
- `sector?: string` — overrides the auto-detected sector context
- `compact?: boolean` — hides the ⓘ icon (still tappable) for dense tables
- `size?: 'sm' | 'md'`

Behaviour:

- **Desktop hover:** floating tooltip with `one_liner` only.
- **Click / long-press:** opens a `LearnCard` (below) as a right-side
  drawer on desktop, bottom-sheet on mobile. Non-blocking; user can dismiss
  and keep browsing.
- Never blocks screen readers — full copy is present as `aria-describedby`
  text, hidden visually until opened.

### 3. `LearnCard` — the expanded explanation

**File:** `frontend/src/components/learn/LearnCard.tsx`

Rendered inside the drawer / bottom-sheet. Layout:

```
┌────────────────────────────────────────┐
│ DCF Value                          ✕   │
│ KES 42.10 · this company               │  ← only if value provided
│ ──────────────────────────────────────  │
│ WHAT IT MEASURES                        │
│ The intrinsic worth of the company      │
│ based on the cash it will generate ...  │
│                                         │
│ HOW IT'S CALCULATED                     │
│ Projects 5-10 years of free cash flow…  │
│                                         │
│ WHAT A HIGH VALUE MEANS                 │
│ …                                       │
│ WHAT A LOW VALUE MEANS                  │
│ …                                       │
│                                         │
│ WATCH-OUTS                              │
│ · Very sensitive to discount rate       │
│ · Not reliable for banks — use EPV      │
│                                         │
│ RULE OF THUMB                           │
│ Compare against Market Price; a DCF     │
│ 20%+ above price = margin of safety.    │
│                                         │
│ RELATED: EPV · Book Value · MOS         │
└────────────────────────────────────────┘
```

- Sections are collapsible on mobile (`WHAT IT MEASURES` open by default).
- "Related" chips are clickable and swap the card content without closing
  the drawer — enables browsing the glossary while staying in place.

### 4. Global "Learn Mode" toggle

**File:** header of `Layout.tsx` (top-right).

- A toggle switch labelled `Learn Mode` (persisted in `localStorage`,
  key `stockup.learn_mode`, default `off`).
- When ON:
  - All `MetricLabel` components render the ⓘ icon inline (always visible).
  - Numbers get a subtle color badge (good / ok / caution / bad) based on
    `thresholds`.
  - A one-liner appears under each `MetricLabel` without any interaction.
- When OFF: metrics render as today, but the ⓘ still appears on hover of
  the label text (progressive disclosure).

### 5. `/learn` glossary page

**File:** `frontend/src/pages/LearnPage.tsx`, routed at `/learn`.

- Left sidebar: metric categories (Valuation, Profitability, …).
- Center: a searchable / filterable list of all metrics from the registry.
  Each entry shows the label, one-liner, and expands to the full `LearnCard`.
- Sector filter chips at the top: `All · Bank · Insurance · Industrial · REIT`.
- Empty state on mobile: search bar prominent, list virtualized.
- Deep-linkable: `/learn#npl_ratio` scrolls to and opens that metric.

### 6. Sector-aware peer context (light backend touch)

Optional, but a big usability win. Two options:

**Option A — client-side (v1):** the `CompaniesPage` already loads every
company with `latest_valuation`. Extend the list DTO with the metrics we
need (`return_on_equity`, `npl_ratio`, etc.) so `LearnCard` can compute
sector medians on the fly.

**Option B — server-side (v1.5):** add
`GET /api/analysis/metrics/{metric_key}/stats?sector=Banking` returning
`{median, p25, p75, min, max, sample_size}`. Cheap query, cached for 24h.

Recommendation: ship v1 with A, promote to B once we have >50 companies.

## User-Facing Copy — writing guidelines

Copy in `registry.ts` is the biggest chunk of new work. Ground rules:

1. **Plain English, no jargon in the first sentence.** If we must use a
   term of art, link it via `related_metrics`.
2. **Concrete over abstract.** Instead of "measures profitability", write
   "shows how many cents of profit the company makes on each shilling of
   shareholder money".
3. **Sector-honest.** For every bank metric, explicitly note that it does
   not apply to industrials, and vice-versa. Prevents users from
   misreading e.g. a bank's D/E ratio.
4. **Show ranges, not thresholds.** "Kenyan tier-1 banks typically report
   CAR between 15–19%. Below 14.5% is the regulatory floor."
5. **Name the trade-off.** Every "what high means" has a matching
   "…but watch out for" line, so users don't fall for a single-number story.

## Rollout plan

1. **Foundations** — build `registry.ts` skeleton with the 25-metric seed
   set (types + empty copy), `MetricLabel`, `LearnCard`, drawer/bottom-sheet
   primitive, and the `Layout.tsx` toggle.
2. **Wire hotspot #1: `CompanyDetailPage`** — replace every metric label
   in the valuation cards, key ratios, financial statements table, and
   scorecard drivers. This alone unlocks 80% of the value.
3. **Wire hotspots #2–4:** `DashboardPage`, `PortfolioPage`,
   `CompaniesPage` (headers + row cells), `RecommendationScorecard` axes.
4. **Write copy** — fill `registry.ts` for all 25 metrics. Review with a
   test user unfamiliar with finance; iterate until the "one-liner alone"
   is enough for basic comprehension.
5. **Ship `/learn` page** — reuses the same `LearnCard`, adds routing,
   sidebar, search.
6. **v1.5:** add threshold-based color badges, the peer-median endpoint,
   and per-metric mini charts (historical distribution across the market)
   inside `LearnCard`.

## Success signals

- New users can open a company page, tap any number, and understand
  what it says about the business without leaving StockUp.
- Bank vs industrial confusion drops — no more comparing a bank's D/E
  to an industrial's.
- The `/learn` page becomes a legitimate reference — measure via time on
  page and search queries.
- Learn Mode toggle usage: >30% of new-user sessions enable it in week 1.

## Open questions

- Should Learn Mode default to ON for brand-new accounts (age < 7 days)?
- Do we want to translate copy to Swahili once English is stable?
- Should `LearnCard` include a "record this as a goal" shortcut for
  metrics like ROE / NPL so users can track their thesis?
