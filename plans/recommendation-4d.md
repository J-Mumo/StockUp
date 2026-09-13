# 4-Dimensional Recommendation

## Problem

Today's recommendation collapses everything to one label (Buy/Hold/Sell) driven
primarily by Margin of Safety with a quality gate. This hides *why* the label
was chosen. A cheap-but-declining stock (BAMB) looks identical to a
fairly-valued-but-compounding one (EQTY), and portfolio context is ignored
entirely — the same "Buy" fires whether you already have a 25% weight in that
name or none at all.

## Goal

Return four independent 0-100 scores alongside the existing verdict, so the UI
can show a scorecard and the drivers behind each axis.

## The four dimensions

Each score is 0-100. Higher = more favourable.

### 1. Valuation (40% default weight)

**Question:** Is the price attractive vs intrinsic value?

**Inputs (all already computed):**
- Margin of safety (`intrinsic_valuations.margin_of_safety_pct`)

**Formula:**
```
val = clip((mos + 0.20) / 0.60, 0, 1) * 100
```
So MOS = −20% → 0, MOS = 0% → 33, MOS = +20% → 67, MOS = +40% → 100.

**Drivers surfaced:** MOS, weighted IV, current price.

### 2. Quality (30% default weight)

**Question:** Is the business itself good?

**Inputs:** Existing `QualityAssessment` (10 sector-aware factors that already
roll up into 6 subscores).

**Formula:**
```
qual = quality.score / quality.max_score * 100
```

**Drivers surfaced:** The existing 6 subscores.

### 3. Trend (20% default weight)

**Question:** Is momentum with you or against you?

**Inputs:**
- Price momentum from `price_history`:
    - 6-month return
    - 12-month return
    - 50-day SMA vs 200-day SMA (golden/death cross)
- Fundamental momentum from `financial_statements`:
    - Direction of net income YoY over last 3 pairs
    - Direction of revenue YoY over last 3 pairs

**Formula (4 signals × 25 pts):**
- +25 if 6M return > 0
- +25 if 12M return > 0
- +25 if 50-day SMA ≥ 200-day SMA
- +25 if majority of last 3 NI YoY pairs positive (or last 3 revenue if NI missing)

If price history is missing, drop the two price signals and normalize.

**Drivers surfaced:** each of the above with its value.

### 4. Position (10% default weight, applicable-only)

**Question:** Where are you already?

**Inputs (per user):**
- Current portfolio position (net qty from `portfolio_transactions`)
- Cost basis (weighted-avg buy price)
- Current price
- Portfolio weight vs total portfolio value
- Sector concentration (sum of weights in same sector)

**Formula:**
- If **no position**: dimension is inapplicable — omitted from composite. UI
  shows a neutral "no position" tile.
- If **position exists**:
    - Start at 50 (neutral).
    - +20 if unrealized P/L ≥ 20%
    - +10 if unrealized P/L in 0–20%
    - −10 if unrealized P/L in −20–0%
    - −20 if unrealized P/L ≤ −20%
    - −15 if portfolio weight > 15% (overexposed)
    - −10 if sector concentration > 30%
    - clip 0–100

Position score's *interpretation* is inverted vs the other three. A high
Position score means the current position is healthy and doesn't need action.
A low score means action is warranted (either trim due to concentration or
reassess a losing thesis).

**Drivers surfaced:** current qty, weight, unrealized P/L, sector weight.

## Composite

Composite = weighted mean of the applicable dimensions, using default weights
(Valuation 40, Quality 30, Trend 20, Position 10). If Position is inapplicable
(user isn't in the name), weights re-normalize across the remaining three.

Composite → verdict:

| Composite | Verdict         |
| --------: | --------------- |
| ≥ 75      | Strong Buy      |
| 60–75     | Buy             |
| 45–60     | Accumulate      |
| 30–45     | Hold            |
| 15–30     | Trim            |
| < 15      | Sell / Avoid    |

"Avoid" is the label when Position is inapplicable and composite < 15.
"Sell" is the label when Position is applicable and composite < 15.

## Backward compatibility

- The existing `Recommendation.action` and `.reason` remain unchanged (still
  driven by MOS + quality-gate logic).
- The new payload is **additive** under `Recommendation.dimensions`.
- The composite verdict is exposed separately as `composite_verdict` /
  `composite_score`; the client can choose which to display prominently.

## API shape

```jsonc
// GET /api/analysis/companies/{id}/recommendation
{
  "action": "Buy",                        // existing
  "reason": "…",                          // existing
  "margin_of_safety_pct": 0.34,           // existing
  "quality_score": 8,                     // existing
  "quality_max_score": 10,                // existing
  "quality_factors": [...],               // existing
  "quality_subscores": [...],             // existing
  "sector_kind": "bank",                  // existing

  // NEW
  "dimensions": {
    "valuation":  {"score": 90, "applicable": true, "drivers": [...]},
    "quality":    {"score": 80, "applicable": true, "drivers": [...]},
    "trend":      {"score": 75, "applicable": true, "drivers": [...]},
    "position":   {"score": null, "applicable": false, "drivers": []}
  },
  "composite_score": 83,
  "composite_verdict": "Strong Buy"
}
```

Each driver entry: `{name, value, passed, detail}`.

## Testing plan

- `test_valuation_dimension.py` — MOS = −20/0/20/40% ⇒ 0/33/67/100.
- `test_trend_dimension.py` — synthetic price history + FS series covering
  all-up, all-down, mixed, missing-price cases.
- `test_position_dimension.py` — no-position, held with +25% P/L,
  over-concentrated case, losing position.
- `test_composite.py` — verifies weight re-normalization and verdict tiers.

## Non-goals for this batch

- User-tunable weights (default 40/30/20/10 hard-coded).
- Sector-specific weight profiles (would want banks weighted more on Quality).
- Alerting on dimension crossings.
- Historical dimension trend chart.
- Composite verdict does NOT override the existing `action` — both are
  returned; frontend chooses.
