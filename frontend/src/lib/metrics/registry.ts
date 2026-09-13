import type { MetricDefinition } from './types';

// Metric registry — single source of truth for Learn Mode copy.
//
// Copy guidelines (see plans/learn-mode.md):
//   1. Plain English, no jargon in the first sentence.
//   2. Concrete over abstract.
//   3. Sector-honest — call out where the metric does NOT apply.
//   4. Show ranges, not thresholds.
//   5. Every "what high means" is paired with a "watch-out".
//
// All percent metrics store values in decimal form (0.15 = 15%) unless the
// unit is `percent_pts`. Thresholds use the same convention.

export const METRICS: Record<string, MetricDefinition> = {
  // ------------------------------------------------------------------ VALUATION
  dcf_value: {
    key: 'dcf_value',
    label: 'DCF Value',
    short_label: 'DCF',
    unit: 'currency',
    sectors: ['all', 'industrial'],
    category: 'valuation',
    one_liner:
      'What a share is worth today based on all the cash the company will generate in the future.',
    what_it_measures:
      'The intrinsic worth of one share, derived from the cash the business is expected to throw off to owners over the next 5–10 years, plus a terminal value beyond that.',
    how_its_calculated:
      'We project future free cash flows using recent growth, discount them back to today using a required rate of return, add a terminal value, then divide by shares outstanding.',
    what_high_means:
      'A DCF well above the market price suggests the stock is undervalued — the market is paying less than the cash the business should generate.',
    what_low_means:
      'A DCF below the market price means you would be paying more today than the future cash flows justify, i.e. the stock looks expensive.',
    watch_outs: [
      'Extremely sensitive to the discount rate and terminal growth assumptions — small changes swing the answer a lot.',
      'Not reliable for banks, insurers, or REITs — their "cash flow" is really regulatory capital and reserves; use EPV or book value instead.',
      'Garbage in, garbage out: if reported cash flows are lumpy, one bad year distorts the projection.',
    ],
    rule_of_thumb:
      'Only trust DCF when 3+ years of stable positive free cash flow exist. Compare against Market Price; a DCF 20%+ above price signals a margin of safety.',
    higher_is_better: 'context',
    related_metrics: ['epv_value', 'weighted_intrinsic_value', 'margin_of_safety_pct', 'free_cash_flow'],
  },

  epv_value: {
    key: 'epv_value',
    label: 'EPV Value',
    short_label: 'EPV',
    unit: 'currency',
    sectors: ['all', 'bank', 'industrial'],
    category: 'valuation',
    one_liner:
      'Earning Power Value — what a share is worth if the company keeps earning at its current sustainable level, forever.',
    what_it_measures:
      'The value of the business assuming no growth — just its current normalised earnings capitalised as a perpetuity.',
    how_its_calculated:
      'We take a normalised earnings figure (averaged across a cycle), divide by a required return, then adjust for excess cash or debt, and divide by shares outstanding.',
    what_high_means:
      'A high EPV vs price says the business already earns enough today to justify the stock even without any growth — a strong margin of safety.',
    what_low_means:
      'A low EPV vs price means you are paying up for future growth that has not been proven yet.',
    watch_outs: [
      'Ignores growth entirely by design — great for mature businesses, unfair to genuine compounders.',
      'The "normalised earnings" step is a judgement call; one-off write-offs or booms can skew it.',
    ],
    rule_of_thumb:
      'EPV is our preferred anchor for banks and cyclical industrials. If DCF >> EPV, the market is paying for growth; if DCF ≈ EPV, the stock is priced on today\'s earnings alone.',
    higher_is_better: 'context',
    related_metrics: ['dcf_value', 'weighted_intrinsic_value', 'return_on_equity'],
  },

  book_value_estimate: {
    key: 'book_value_estimate',
    label: 'Book Value',
    unit: 'currency',
    sectors: ['all', 'bank', 'insurance'],
    category: 'valuation',
    one_liner:
      'Net worth per share — what shareholders would receive if the company were liquidated at balance-sheet values.',
    what_it_measures:
      'Total equity attributable to shareholders divided by shares outstanding — the accounting floor value of one share.',
    how_its_calculated:
      'Total assets minus total liabilities, divided by shares outstanding. Adjusted for intangibles when tangible book is more meaningful.',
    what_high_means:
      'A high book value vs price (low P/B) can indicate a bargain — but only if the assets are real and productive.',
    what_low_means:
      'A low book value vs price means the market is paying a big premium for future earnings, brand, or growth beyond what the accounts show.',
    watch_outs: [
      'Most useful for banks, insurers, and asset-heavy businesses. Meaningless for a software or brand-driven company.',
      'Non-performing loans, stale property valuations, or goodwill can inflate reported book value.',
    ],
    rule_of_thumb:
      'For Kenyan banks, price-to-book below 1.0× has historically flagged deep value, but only when NPL ratios were controlled.',
    higher_is_better: 'context',
    related_metrics: ['book_value_per_share', 'pb_ratio', 'npl_ratio'],
  },

  weighted_intrinsic_value: {
    key: 'weighted_intrinsic_value',
    label: 'Intrinsic Value',
    short_label: 'IV',
    unit: 'currency',
    sectors: ['all'],
    category: 'valuation',
    one_liner:
      'StockUp\'s single best estimate of what a share is worth — a weighted blend of DCF, EPV, and book value.',
    what_it_measures:
      'The composite fair value per share, combining the models that best fit the company\'s sector so no single method dominates.',
    how_its_calculated:
      'A sector-aware weighted average of DCF, EPV, and book value. Banks lean on EPV + book; industrials lean on DCF + EPV. Weights are shown in the Assumptions panel.',
    what_high_means:
      'Intrinsic Value above the current price means StockUp sees the stock as undervalued — the Margin of Safety is positive.',
    what_low_means:
      'Intrinsic Value below the current price signals overvaluation — you would be paying more than fair value.',
    watch_outs: [
      'It is a model output, not a fact. The confidence badge (High / Medium / Low) reflects how much the underlying methods agree.',
      'Big gaps between DCF and EPV are a warning sign — check the individual cards to see why they disagree.',
    ],
    rule_of_thumb:
      'Treat IV as an anchor for decision-making, not a price target. Buy well below IV, trim well above it, avoid mechanical precision.',
    higher_is_better: 'context',
    related_metrics: ['dcf_value', 'epv_value', 'book_value_estimate', 'margin_of_safety_pct', 'iv_confidence'],
  },

  margin_of_safety_pct: {
    key: 'margin_of_safety_pct',
    label: 'Margin of Safety',
    short_label: 'MOS',
    unit: 'percent',
    sectors: ['all'],
    category: 'valuation',
    one_liner:
      'How much cheaper the stock is vs its intrinsic value — your cushion against being wrong.',
    what_it_measures:
      'The discount (positive) or premium (negative) of Intrinsic Value over the current market price, expressed as a percentage of price.',
    how_its_calculated:
      '(Intrinsic Value − Market Price) ÷ Market Price. A +25% MOS means the stock trades 25% below what StockUp thinks it is worth.',
    what_high_means:
      'A large positive MOS gives you room to be wrong on the assumptions and still not overpay. Value investors demand this before buying.',
    what_low_means:
      'A negative or small MOS means the market has already priced in the value StockUp sees — limited upside, more risk if assumptions were optimistic.',
    watch_outs: [
      'A big MOS on a low-quality business is often a trap — check the Quality dimension first.',
      'MOS uses Intrinsic Value, which itself is a model output. Don\'t treat +5% as meaningfully different from +8%.',
    ],
    rule_of_thumb:
      'Classic Graham/Buffett threshold is +25% or better before buying. On the NSE, +30% has historically been a strong entry signal for quality names.',
    higher_is_better: true,
    thresholds: [
      { min: 0.25, max: null, verdict: 'good', note: 'Meaningful discount to fair value.' },
      { min: 0.10, max: 0.25, verdict: 'ok', note: 'Modest discount — verify quality.' },
      { min: -0.10, max: 0.10, verdict: 'caution', note: 'Roughly fairly valued.' },
      { min: null, max: -0.10, verdict: 'bad', note: 'Trading at a premium to fair value.' },
    ],
    related_metrics: ['weighted_intrinsic_value', 'dcf_value', 'epv_value'],
  },

  iv_confidence: {
    key: 'iv_confidence',
    label: 'IV Confidence',
    unit: 'ratio',
    sectors: ['all'],
    category: 'valuation',
    one_liner:
      'How much StockUp\'s valuation methods agree with each other — High, Medium, or Low.',
    what_it_measures:
      'The tightness of the range between the conservative and strong scenarios, expressed as a confidence tier.',
    how_its_calculated:
      'Based on the spread between the low and high scenario values (bear vs bull). A tight spread → High. A wide spread → Low.',
    what_high_means:
      'High confidence means DCF, EPV, and book value all point in the same direction — you can lean on the Intrinsic Value more.',
    what_low_means:
      'Low confidence means the methods disagree materially. Look at each individual model before acting on the composite.',
    watch_outs: [
      'Confidence reflects internal model agreement, not real-world certainty. A confident model can still be wrong.',
    ],
    higher_is_better: true,
    related_metrics: ['weighted_intrinsic_value'],
  },

  pe_ratio: {
    key: 'pe_ratio',
    label: 'P/E Ratio',
    unit: 'multiple',
    sectors: ['all'],
    category: 'valuation',
    one_liner:
      'How many shillings you pay for each shilling of the company\'s current annual earnings.',
    what_it_measures:
      'A quick relative-value check — how expensive the stock is vs its recent earnings power.',
    how_its_calculated:
      'Market Price per share ÷ Earnings Per Share (EPS). A P/E of 12 means you pay KES 12 for every KES 1 the company earns annually.',
    what_high_means:
      'A high P/E signals the market expects strong earnings growth ahead — or that current earnings are temporarily depressed.',
    what_low_means:
      'A low P/E can mean the stock is cheap, or that the market expects earnings to decline. It is not "cheap" on its own.',
    watch_outs: [
      'One-off items can make earnings, and therefore P/E, misleading in a single year.',
      'P/E is meaningless when earnings are negative or near zero.',
      'Cross-sector comparisons are unfair — banks and utilities trade at structurally lower P/Es than tech.',
    ],
    rule_of_thumb:
      'For mature NSE banks, historical P/E has ranged 5–8×. Above 15× is unusual and usually reflects strong growth expectations.',
    higher_is_better: 'context',
    related_metrics: ['pb_ratio', 'earnings_per_share', 'dividend_yield'],
  },

  pb_ratio: {
    key: 'pb_ratio',
    label: 'P/B Ratio',
    unit: 'multiple',
    sectors: ['all', 'bank', 'insurance'],
    category: 'valuation',
    one_liner:
      'How many shillings you pay for each shilling of the company\'s net worth on its balance sheet.',
    what_it_measures:
      'A quick check for asset-heavy businesses — how the market values the accounting book relative to what shareholders technically own.',
    how_its_calculated:
      'Market Price per share ÷ Book Value Per Share. P/B of 1.0 means you pay exactly the accounting net worth.',
    what_high_means:
      'A high P/B means the market expects the company to earn well above its cost of capital on its assets — pricing in profitability, not just assets.',
    what_low_means:
      'A low P/B (below 1.0) can flag a bargain, but often signals that the market doubts the assets are worth their reported value.',
    watch_outs: [
      'Nearly useless for asset-light businesses like software or brand houses.',
      'For banks, a low P/B combined with rising NPLs is a distress signal, not a value signal.',
    ],
    rule_of_thumb:
      'Kenyan tier-1 banks typically trade at P/B between 0.7× and 1.4×. Below 0.6× has historically indicated stress or deep pessimism.',
    higher_is_better: 'context',
    related_metrics: ['book_value_per_share', 'book_value_estimate', 'return_on_equity'],
  },

  dividend_yield: {
    key: 'dividend_yield',
    label: 'Dividend Yield',
    unit: 'percent',
    sectors: ['all'],
    category: 'income',
    one_liner:
      'The annual cash dividend as a percentage of the current share price — your income return.',
    what_it_measures:
      'How much cash a shareholder collects each year, relative to what they pay for the share today.',
    how_its_calculated:
      'Dividends Per Share (last 12 months) ÷ Current Market Price × 100.',
    what_high_means:
      'A high yield delivers strong current income, but can signal that the market expects the dividend to be cut, or the share price to fall.',
    what_low_means:
      'A low yield either reflects a low-payout / growth strategy, or a rich share price. Check the payout ratio.',
    watch_outs: [
      'Trailing yields lag — a dividend cut may already be announced but not yet reflected.',
      'Very high yields (>10%) on cyclical stocks are almost always a warning.',
    ],
    rule_of_thumb:
      'Kenyan blue-chip dividend yields typically range 4–8%. Sustainable payout ratios sit below ~70% of earnings.',
    higher_is_better: 'context',
    thresholds: [
      { min: 0.06, max: null, verdict: 'good' },
      { min: 0.03, max: 0.06, verdict: 'ok' },
      { min: 0.01, max: 0.03, verdict: 'caution' },
      { min: null, max: 0.01, verdict: 'bad', note: 'Very low or no yield.' },
    ],
    related_metrics: ['dividends_per_share', 'pe_ratio'],
  },

  // ------------------------------------------------------------- PROFITABILITY
  return_on_equity: {
    key: 'return_on_equity',
    label: 'Return on Equity',
    short_label: 'ROE',
    unit: 'percent',
    sectors: ['all'],
    category: 'profitability',
    one_liner:
      'How many cents of profit the company makes on each shilling of shareholder money.',
    what_it_measures:
      'The efficiency with which management turns the equity you own into profits — the single best measure of a business\'s quality.',
    how_its_calculated:
      'Net Income ÷ Shareholders\' Equity × 100. An ROE of 20% means the business earns KES 0.20 per year on every KES 1 of equity it employs.',
    what_high_means:
      'Consistently high ROE (>15%) signals a company with a durable competitive advantage — pricing power, scale, or brand.',
    what_low_means:
      'Persistently low ROE (<10%) means management is destroying or barely maintaining shareholder value.',
    watch_outs: [
      'ROE can be juiced by heavy debt — always cross-check Debt-to-Equity.',
      'One-off gains or aggressive write-downs distort a single year. Look at 3–5 year averages.',
      'For banks, extremely high ROE (>25%) is often a red flag for undercapitalisation or risky lending.',
    ],
    rule_of_thumb:
      'Warren Buffett\'s benchmark: businesses that consistently earn 15%+ ROE with low leverage are worth studying.',
    higher_is_better: true,
    thresholds: [
      { min: 0.20, max: null, verdict: 'good', note: 'Excellent capital efficiency.' },
      { min: 0.12, max: 0.20, verdict: 'ok' },
      { min: 0.05, max: 0.12, verdict: 'caution' },
      { min: null, max: 0.05, verdict: 'bad', note: 'Below cost of equity — value destroying.' },
    ],
    related_metrics: ['net_income', 'debt_to_equity', 'earnings_per_share'],
  },

  net_income: {
    key: 'net_income',
    label: 'Net Income',
    unit: 'currency',
    sectors: ['all'],
    category: 'profitability',
    one_liner:
      'The company\'s profit for the year after all costs, interest, and taxes.',
    what_it_measures:
      'The bottom line — what the business actually earned for shareholders during the period.',
    how_its_calculated:
      'Revenue minus all operating expenses, interest, and taxes. What is left belongs to shareholders.',
    what_high_means:
      'Growing net income year-on-year is the most basic sign that the business is compounding value.',
    what_low_means:
      'Falling or negative net income means the business is struggling, or one-off items are dragging the year down.',
    watch_outs: [
      'Non-cash items (depreciation, write-offs) and one-time gains distort net income. Cross-check with Operating Cash Flow.',
      'Accounting is subject to management discretion — a suspiciously smooth trend can hide manipulation.',
    ],
    higher_is_better: true,
    related_metrics: ['revenue', 'operating_cash_flow', 'earnings_per_share', 'return_on_equity'],
  },

  earnings_per_share: {
    key: 'earnings_per_share',
    label: 'Earnings Per Share',
    short_label: 'EPS',
    unit: 'currency',
    sectors: ['all'],
    category: 'profitability',
    one_liner:
      'The company\'s annual profit split across each single share you can own.',
    what_it_measures:
      'How much profit is attributable to one share — the direct input to P/E ratio and per-share valuation.',
    how_its_calculated:
      'Net Income ÷ Weighted Average Shares Outstanding.',
    what_high_means:
      'Rising EPS over time means either profits are growing, share count is shrinking (buybacks), or both — great for owners.',
    what_low_means:
      'Falling EPS signals shrinking profits or dilution from new share issuance.',
    watch_outs: [
      'A company can boost EPS by issuing debt to buy back shares — check the balance sheet.',
      'One-off items make single-year EPS misleading. Prefer trailing 3-year or normalised EPS.',
    ],
    higher_is_better: true,
    related_metrics: ['net_income', 'pe_ratio', 'shares_outstanding'],
  },

  revenue: {
    key: 'revenue',
    label: 'Revenue',
    unit: 'currency',
    sectors: ['all'],
    category: 'growth',
    one_liner:
      'The total sales the company brought in during the year — the top of the income statement.',
    what_it_measures:
      'The scale of the business — how much customers paid it before any costs.',
    how_its_calculated:
      'Sum of all sales / interest income / premiums during the period, depending on the sector.',
    what_high_means:
      'Growing revenue is the foundation of long-term value creation — assuming margins hold up.',
    what_low_means:
      'Stagnant or falling revenue is a red flag; it forces the business to cut costs to protect profits, which is finite.',
    watch_outs: [
      'Revenue growth without matching profit growth means margins are compressing.',
      'Watch for one-off large contracts that inflate a year.',
    ],
    higher_is_better: true,
    related_metrics: ['net_income', 'operating_cash_flow'],
  },

  // -------------------------------------------------------- SOLVENCY / LIQUIDITY
  debt_to_equity: {
    key: 'debt_to_equity',
    label: 'Debt-to-Equity',
    short_label: 'D/E',
    unit: 'ratio',
    sectors: ['all', 'industrial'],
    category: 'solvency',
    one_liner:
      'How much of the company\'s capital comes from lenders vs shareholders.',
    what_it_measures:
      'Financial leverage — how much debt the business uses to fund its assets. Higher = riskier if profits dip.',
    how_its_calculated:
      'Total Debt ÷ Shareholders\' Equity. A D/E of 1.0 means the company borrows exactly as much as its equity base.',
    what_high_means:
      'High D/E amplifies returns in good times but magnifies losses in bad times. Above 2.0 is generally aggressive for a non-bank.',
    what_low_means:
      'Low D/E means a conservative balance sheet — safer, but potentially under-utilising cheap debt.',
    watch_outs: [
      'Banks operate at very high D/E by design — do not compare a bank to an industrial on this metric.',
      'Off-balance-sheet liabilities (leases, guarantees) can hide real leverage.',
    ],
    rule_of_thumb:
      'For NSE industrials, D/E below 1.0× is considered conservative. Above 2.0× warrants close attention to interest coverage.',
    higher_is_better: false,
    thresholds: [
      { min: null, max: 0.5, verdict: 'good' },
      { min: 0.5, max: 1.0, verdict: 'ok' },
      { min: 1.0, max: 2.0, verdict: 'caution' },
      { min: 2.0, max: null, verdict: 'bad', note: 'Aggressive leverage for a non-bank.' },
    ],
    related_metrics: ['current_ratio', 'return_on_equity'],
  },

  current_ratio: {
    key: 'current_ratio',
    label: 'Current Ratio',
    unit: 'ratio',
    sectors: ['all', 'industrial'],
    category: 'liquidity',
    one_liner:
      'Can the company pay its short-term bills using its short-term assets?',
    what_it_measures:
      'Short-term solvency — whether cash, receivables, and inventory cover debts due within a year.',
    how_its_calculated:
      'Current Assets ÷ Current Liabilities. A ratio of 1.5 means KES 1.50 of short-term assets for every KES 1 of short-term debt.',
    what_high_means:
      'A high ratio (>2.0) means comfortable liquidity — but very high ratios can also mean lazy capital sitting idle.',
    what_low_means:
      'Below 1.0 means the company would struggle to pay near-term obligations without borrowing more or selling assets.',
    watch_outs: [
      'Not meaningful for banks — their entire business is a mismatch of short and long liabilities.',
      'Inventory-heavy current assets can be illiquid in a downturn.',
    ],
    rule_of_thumb:
      'For industrials, 1.5–2.5 is a healthy zone. Below 1.0 is a liquidity warning.',
    higher_is_better: 'context',
    thresholds: [
      { min: 1.5, max: 3.0, verdict: 'good' },
      { min: 1.0, max: 1.5, verdict: 'ok' },
      { min: 0.7, max: 1.0, verdict: 'caution' },
      { min: null, max: 0.7, verdict: 'bad', note: 'Liquidity stress likely.' },
      { min: 3.0, max: null, verdict: 'caution', note: 'Possibly lazy capital.' },
    ],
    related_metrics: ['debt_to_equity'],
  },

  book_value_per_share: {
    key: 'book_value_per_share',
    label: 'Book Value / Share',
    short_label: 'BVPS',
    unit: 'currency',
    sectors: ['all', 'bank', 'insurance'],
    category: 'solvency',
    one_liner:
      'The accounting net worth attributable to one share.',
    what_it_measures:
      'Per-share equity — the accounting floor value of what you own.',
    how_its_calculated:
      'Shareholders\' Equity ÷ Shares Outstanding.',
    what_high_means:
      'Rising BVPS year over year signals real retained value creation, especially when combined with high ROE.',
    what_low_means:
      'Falling BVPS suggests losses, write-downs, or heavy dividend / buyback payouts eroding equity.',
    watch_outs: [
      'Book value ignores intangibles like brand and technology.',
      'For banks, watch that BVPS is not being inflated by delayed loan loss recognition.',
    ],
    higher_is_better: true,
    related_metrics: ['book_value_estimate', 'pb_ratio', 'return_on_equity'],
  },

  // ------------------------------------------------------------------ CASH FLOW
  operating_cash_flow: {
    key: 'operating_cash_flow',
    label: 'Operating Cash Flow',
    short_label: 'OCF',
    unit: 'currency',
    sectors: ['all', 'industrial'],
    category: 'profitability',
    one_liner:
      'The actual cash the core business generated during the year, before any investment.',
    what_it_measures:
      'How much cash the operations produced — a reality check against reported profits.',
    how_its_calculated:
      'Net Income adjusted for non-cash items (depreciation, working capital changes) as reported in the cash flow statement.',
    what_high_means:
      'Strong and growing OCF confirms the business is turning profits into real cash — the healthiest sign in finance.',
    what_low_means:
      'When OCF is much lower than net income, the profits are on paper only. This often precedes accounting scandals.',
    watch_outs: [
      'OCF can be temporarily boosted by delaying supplier payments — check the working capital drivers.',
    ],
    rule_of_thumb:
      'Over 3+ years, OCF should track close to or above net income. Persistent gaps are a warning.',
    higher_is_better: true,
    related_metrics: ['free_cash_flow', 'net_income', 'capital_expenditures'],
  },

  free_cash_flow: {
    key: 'free_cash_flow',
    label: 'Free Cash Flow',
    short_label: 'FCF',
    unit: 'currency',
    sectors: ['all', 'industrial'],
    category: 'profitability',
    one_liner:
      'The cash left over after paying for operations and reinvestment — the money truly available to owners.',
    what_it_measures:
      'What the business can pay out as dividends, buy back shares with, pay down debt, or reinvest for growth without external funding.',
    how_its_calculated:
      'Operating Cash Flow − Capital Expenditures.',
    what_high_means:
      'Consistent positive FCF is the single most important sign of a durable, self-funding business.',
    what_low_means:
      'Persistently negative FCF means the company depends on debt or new equity to keep operating — risky unless it is a proven high-growth story.',
    watch_outs: [
      'FCF is the direct input to DCF — errors or lumpiness here distort the valuation heavily.',
      'Not applicable in a clean way to banks and insurers.',
    ],
    rule_of_thumb:
      'FCF growing faster than net income over multiple years is a hallmark of exceptional businesses.',
    higher_is_better: true,
    related_metrics: ['operating_cash_flow', 'capital_expenditures', 'dcf_value'],
  },

  capital_expenditures: {
    key: 'capital_expenditures',
    label: 'Capital Expenditures',
    short_label: 'CapEx',
    unit: 'currency',
    sectors: ['all', 'industrial'],
    category: 'efficiency',
    one_liner:
      'The cash the company spent on long-lived assets — plant, equipment, technology — during the year.',
    what_it_measures:
      'How much the business is reinvesting to maintain and grow its productive capacity.',
    how_its_calculated:
      'Cash outflows for property, plant, equipment, and other long-lived assets, as reported in the cash flow statement.',
    what_high_means:
      'High CapEx can signal growth investment — good if returns follow. Bad if it is just maintenance to stand still.',
    what_low_means:
      'Low CapEx can mean the business is capital-light (great for FCF) or that it is under-investing and will lose competitiveness.',
    watch_outs: [
      'Distinguish maintenance CapEx (to keep the lights on) from growth CapEx. Only growth CapEx adds future earnings.',
    ],
    higher_is_better: 'context',
    related_metrics: ['operating_cash_flow', 'free_cash_flow'],
  },

  dividends_per_share: {
    key: 'dividends_per_share',
    label: 'Dividends / Share',
    short_label: 'DPS',
    unit: 'currency',
    sectors: ['all'],
    category: 'income',
    one_liner:
      'The cash paid out to each share over the year.',
    what_it_measures:
      'The direct income return to shareholders — the concrete cash you receive per share.',
    how_its_calculated:
      'Total dividends declared ÷ Shares Outstanding.',
    what_high_means:
      'A rising DPS shows confidence — management is comfortable returning cash rather than hoarding it.',
    what_low_means:
      'A cut in DPS is a strong negative signal, often signalling stress before it appears in the P&L.',
    watch_outs: [
      'A high DPS funded by debt or asset sales is unsustainable.',
      'Payout ratio (DPS ÷ EPS) above 80% leaves little room for a bad year.',
    ],
    higher_is_better: true,
    related_metrics: ['dividend_yield', 'earnings_per_share', 'free_cash_flow'],
  },

  // --------------------------------------------------------------- BANK METRICS
  npl_ratio: {
    key: 'npl_ratio',
    label: 'NPL Ratio',
    unit: 'percent',
    sectors: ['bank'],
    category: 'risk',
    one_liner:
      'The share of a bank\'s loan book that borrowers have stopped repaying — the core credit-risk indicator.',
    what_it_measures:
      'Loan portfolio quality — the fraction of loans classified as non-performing (typically 90+ days overdue).',
    how_its_calculated:
      'Non-Performing Loans ÷ Gross Loans × 100.',
    what_high_means:
      'A rising or high NPL ratio means the bank is losing money to bad borrowers — future write-offs will hit profits and capital.',
    what_low_means:
      'A low NPL ratio (below ~5%) signals disciplined lending, though it could also mean overly cautious growth.',
    watch_outs: [
      'Banks can delay loan classification to keep NPLs looking low — cross-check with coverage ratio and cost of risk.',
      'Sector-wide shocks (drought, currency crisis) can move all NPLs at once; peer comparison matters.',
    ],
    rule_of_thumb:
      'CBK expects tier-1 banks to hold NPLs below 10%. Above 15% has historically preceded serious equity dilution or state rescue.',
    higher_is_better: false,
    thresholds: [
      { min: null, max: 0.05, verdict: 'good' },
      { min: 0.05, max: 0.10, verdict: 'ok' },
      { min: 0.10, max: 0.15, verdict: 'caution' },
      { min: 0.15, max: null, verdict: 'bad', note: 'Elevated credit-risk stress.' },
    ],
    related_metrics: ['capital_adequacy_ratio', 'cost_of_risk', 'cost_to_income_ratio'],
  },

  capital_adequacy_ratio: {
    key: 'capital_adequacy_ratio',
    label: 'Capital Adequacy',
    short_label: 'CAR',
    unit: 'percent',
    sectors: ['bank'],
    category: 'solvency',
    one_liner:
      'How much capital a bank holds against its risk — its cushion against loan losses.',
    what_it_measures:
      'The bank\'s ability to absorb losses without becoming insolvent. Set by the Central Bank of Kenya (CBK) as a regulatory minimum.',
    how_its_calculated:
      'Total qualifying capital ÷ Risk-Weighted Assets × 100. Combines Tier 1 (core equity) and Tier 2 (supplementary) capital.',
    what_high_means:
      'A high CAR means the bank can weather a serious recession without needing to raise new capital — safer for shareholders.',
    what_low_means:
      'A low CAR forces the bank to slow lending or raise equity, diluting existing shareholders.',
    watch_outs: [
      'CBK\'s minimum is 14.5% total capital (10.5% Tier 1). Banks that hover near this line have limited room to grow.',
      'CAR is calculated on risk-weighted assets — a bank can boost CAR by shifting into safer, lower-yielding assets, which caps future earnings.',
    ],
    rule_of_thumb:
      'For NSE-listed banks, look for CAR sustained above 16% as a comfort zone. Below 14.5% is a regulatory red flag.',
    higher_is_better: true,
    thresholds: [
      { min: 0.18, max: null, verdict: 'good' },
      { min: 0.15, max: 0.18, verdict: 'ok' },
      { min: 0.145, max: 0.15, verdict: 'caution', note: 'Close to CBK floor.' },
      { min: null, max: 0.145, verdict: 'bad', note: 'Below CBK regulatory minimum.' },
    ],
    related_metrics: ['npl_ratio', 'return_on_equity', 'book_value_per_share'],
  },

  cost_to_income_ratio: {
    key: 'cost_to_income_ratio',
    label: 'Cost-to-Income',
    short_label: 'C/I',
    unit: 'percent',
    sectors: ['bank'],
    category: 'efficiency',
    one_liner:
      'The share of a bank\'s income eaten up by operating costs — its efficiency score.',
    what_it_measures:
      'How efficiently the bank turns revenue into profit. Lower means more of every shilling earned reaches shareholders.',
    how_its_calculated:
      'Operating Expenses ÷ Operating Income × 100.',
    what_high_means:
      'A high ratio (>60%) means the bank spends too much on staff, branches, and technology relative to what it earns.',
    what_low_means:
      'A low ratio (<45%) is a hallmark of well-run banks — often the digital-first ones with lean branch networks.',
    watch_outs: [
      'A falling ratio driven by cost-cutting eventually hits a floor. Sustainable efficiency comes from revenue growth outpacing costs.',
    ],
    rule_of_thumb:
      'Top-quartile NSE banks operate below 50%. Above 65% signals structural inefficiency.',
    higher_is_better: false,
    thresholds: [
      { min: null, max: 0.45, verdict: 'good' },
      { min: 0.45, max: 0.55, verdict: 'ok' },
      { min: 0.55, max: 0.65, verdict: 'caution' },
      { min: 0.65, max: null, verdict: 'bad', note: 'Structurally inefficient.' },
    ],
    related_metrics: ['return_on_equity', 'net_income'],
  },

  cost_of_risk: {
    key: 'cost_of_risk',
    label: 'Cost of Risk',
    unit: 'percent',
    sectors: ['bank'],
    category: 'risk',
    one_liner:
      'How much of the loan book the bank set aside for expected losses this year.',
    what_it_measures:
      'The current-year charge for credit losses, as a percentage of loans — the P&L cost of the bank\'s risk-taking.',
    how_its_calculated:
      'Loan Loss Provisions ÷ Average Gross Loans × 100.',
    what_high_means:
      'A spike in cost of risk signals deteriorating loan quality or a proactive clean-up. Either way, it hits profits.',
    what_low_means:
      'Low and stable cost of risk (below 1%) reflects a disciplined lender in a benign credit cycle.',
    watch_outs: [
      'Deliberately low provisioning is a common way to flatter earnings — always sanity-check against NPL trends.',
    ],
    rule_of_thumb:
      'For NSE banks, 1–2% is normal. Above 3% signals a stressed loan book.',
    higher_is_better: false,
    thresholds: [
      { min: null, max: 0.01, verdict: 'good' },
      { min: 0.01, max: 0.02, verdict: 'ok' },
      { min: 0.02, max: 0.03, verdict: 'caution' },
      { min: 0.03, max: null, verdict: 'bad' },
    ],
    related_metrics: ['npl_ratio', 'capital_adequacy_ratio'],
  },

  // ------------------------------------------------------------------ SCORECARD
  dim_valuation: {
    key: 'dim_valuation',
    label: 'Valuation Score',
    unit: 'score',
    sectors: ['all'],
    category: 'scorecard',
    one_liner:
      'Is the price attractive vs intrinsic value? A 0–100 score — higher is cheaper.',
    what_it_measures:
      'One of the four axes of StockUp\'s recommendation scorecard — how much of a discount the current price offers to fair value.',
    how_its_calculated:
      'Derived from Margin of Safety. MOS of −20% → 0, 0% → ~33, +20% → ~67, +40% → 100.',
    what_high_means:
      'A high valuation score means the stock is cheap relative to what StockUp thinks it is worth — a green light for value investors.',
    what_low_means:
      'A low score means the stock is fully or over-priced. Even a great business can be a poor investment at the wrong price.',
    watch_outs: [
      'This axis says nothing about business quality — pair it with the Quality score.',
    ],
    higher_is_better: true,
    thresholds: [
      { min: 75, max: null, verdict: 'good' },
      { min: 60, max: 75, verdict: 'ok' },
      { min: 45, max: 60, verdict: 'caution' },
      { min: null, max: 45, verdict: 'bad' },
    ],
    related_metrics: ['margin_of_safety_pct', 'weighted_intrinsic_value', 'dim_quality'],
  },

  dim_quality: {
    key: 'dim_quality',
    label: 'Quality Score',
    unit: 'score',
    sectors: ['all'],
    category: 'scorecard',
    one_liner:
      'Is the business itself good? A 0–100 score based on sector-aware quality factors.',
    what_it_measures:
      'One of the four axes — how strong, profitable, and resilient the underlying business is, independent of price.',
    how_its_calculated:
      'A blend of ~10 sector-aware factors covering profitability (ROE), balance sheet strength (leverage, CAR for banks), cash conversion, and stability of results.',
    what_high_means:
      'A high quality score marks a durable business — the kind you want to own for years, ideally bought during a valuation dip.',
    what_low_means:
      'A low score flags business risk. A low valuation score on a low quality name is often a value trap.',
    watch_outs: [
      'Quality is backward-looking — new competitive threats may not yet show up in the numbers.',
    ],
    higher_is_better: true,
    thresholds: [
      { min: 75, max: null, verdict: 'good' },
      { min: 60, max: 75, verdict: 'ok' },
      { min: 45, max: 60, verdict: 'caution' },
      { min: null, max: 45, verdict: 'bad' },
    ],
    related_metrics: ['dim_valuation', 'return_on_equity', 'npl_ratio', 'capital_adequacy_ratio'],
  },

  dim_trend: {
    key: 'dim_trend',
    label: 'Trend Score',
    unit: 'score',
    sectors: ['all'],
    category: 'scorecard',
    one_liner:
      'Is the price and business trajectory improving? A 0–100 score capturing momentum.',
    what_it_measures:
      'One of the four axes — whether recent price action and fundamental progress support entering now vs waiting.',
    how_its_calculated:
      'Combines price momentum (recent returns vs longer-term averages), earnings revision direction, and margin trends.',
    what_high_means:
      'A high trend score means the stock is in an uptrend supported by improving fundamentals — riding a wave.',
    what_low_means:
      'A low score indicates a falling knife: price and fundamentals are both weak. Wait for stabilisation before buying, even if valuation looks tempting.',
    watch_outs: [
      'Trend can reverse sharply — never rely on this axis alone.',
    ],
    higher_is_better: true,
    thresholds: [
      { min: 75, max: null, verdict: 'good' },
      { min: 60, max: 75, verdict: 'ok' },
      { min: 45, max: 60, verdict: 'caution' },
      { min: null, max: 45, verdict: 'bad' },
    ],
    related_metrics: ['dim_valuation', 'dim_quality'],
  },

  dim_position: {
    key: 'dim_position',
    label: 'Position Score',
    unit: 'score',
    sectors: ['all'],
    category: 'scorecard',
    one_liner:
      'How this stock fits your existing portfolio — sizing, concentration, and diversification.',
    what_it_measures:
      'One of the four axes — is buying more of this a good idea given what you already own?',
    how_its_calculated:
      'Considers your current weight in this name, sector concentration, and correlation with the rest of the book. Only scored when you hold the security.',
    what_high_means:
      'A high position score means adding to this stock improves portfolio balance — often because your current weight is low.',
    what_low_means:
      'A low score means you may already be over-exposed. Even a great name can be a bad add if it doubles your risk.',
    watch_outs: [
      'This axis is n/a for stocks you do not currently hold.',
    ],
    higher_is_better: true,
    thresholds: [
      { min: 75, max: null, verdict: 'good' },
      { min: 60, max: 75, verdict: 'ok' },
      { min: 45, max: 60, verdict: 'caution' },
      { min: null, max: 45, verdict: 'bad' },
    ],
    related_metrics: ['dim_valuation', 'dim_quality', 'dim_trend'],
  },

  composite_score: {
    key: 'composite_score',
    label: 'Composite Score',
    unit: 'score',
    sectors: ['all'],
    category: 'scorecard',
    one_liner:
      'StockUp\'s single 0–100 verdict combining valuation, quality, trend, and position.',
    what_it_measures:
      'The weighted average of the four scorecard axes, mapped to an action label (Strong Buy → Avoid).',
    how_its_calculated:
      'Default weights: Valuation 40%, Quality 30%, Trend 20%, Position 10%. Position drops out for stocks you do not hold.',
    what_high_means:
      'Scores of 75+ (Strong Buy / Buy) reflect stocks that are cheap, high-quality, trending well, and fit your portfolio.',
    what_low_means:
      'Scores below 30 (Sell / Avoid) show stocks failing on multiple dimensions — usually expensive or deteriorating businesses.',
    watch_outs: [
      'The composite hides which axis is driving the verdict. Always open the scorecard breakdown to see the "why".',
      'The weights are defaults — you can override them per company.',
    ],
    higher_is_better: true,
    thresholds: [
      { min: 75, max: null, verdict: 'good' },
      { min: 60, max: 75, verdict: 'ok' },
      { min: 45, max: 60, verdict: 'caution' },
      { min: null, max: 45, verdict: 'bad' },
    ],
    related_metrics: ['dim_valuation', 'dim_quality', 'dim_trend', 'dim_position'],
  },
};

export function getMetric(key: string): MetricDefinition | undefined {
  return METRICS[key];
}

export function allMetrics(): MetricDefinition[] {
  return Object.values(METRICS);
}

export function metricsForSector(sector: string | null | undefined): MetricDefinition[] {
  const s = (sector || '').toLowerCase();
  const bucket: 'bank' | 'insurance' | 'industrial' | 'reit' | 'all' =
    s.includes('bank') ? 'bank'
    : s.includes('insur') ? 'insurance'
    : s.includes('reit') || s.includes('real estate') ? 'reit'
    : s ? 'industrial'
    : 'all';
  return allMetrics().filter(m => m.sectors.includes('all') || m.sectors.includes(bucket));
}

export function verdictForValue(
  metric: MetricDefinition,
  value: number | null | undefined,
): { verdict: import('./types').MetricVerdict; note?: string } | null {
  if (value == null || !metric.thresholds || metric.thresholds.length === 0) return null;
  for (const t of metric.thresholds) {
    const geMin = t.min == null || value >= t.min;
    const ltMax = t.max == null || value < t.max;
    if (geMin && ltMax) return { verdict: t.verdict, note: t.note };
  }
  return null;
}

export function formatMetricValue(
  metric: MetricDefinition,
  value: number | null | undefined,
  opts: { currency?: string } = {},
): string {
  if (value == null || Number.isNaN(value)) return '—';
  const currency = opts.currency ?? 'KES';
  switch (metric.unit) {
    case 'currency': {
      const abs = Math.abs(value);
      if (abs >= 1e9) return `${currency} ${(value / 1e9).toFixed(2)}B`;
      if (abs >= 1e6) return `${currency} ${(value / 1e6).toFixed(2)}M`;
      if (abs >= 1e3) return `${currency} ${(value / 1e3).toFixed(2)}K`;
      return `${currency} ${value.toFixed(2)}`;
    }
    case 'percent':
      return `${(value * 100).toFixed(1)}%`;
    case 'percent_pts':
      return `${value.toFixed(1)}%`;
    case 'ratio':
      return value.toFixed(2);
    case 'multiple':
      return `${value.toFixed(2)}×`;
    case 'count':
      return value.toLocaleString();
    case 'years':
      return `${value.toFixed(1)} yr`;
    case 'score':
      return value.toFixed(0);
    default:
      return String(value);
  }
}
