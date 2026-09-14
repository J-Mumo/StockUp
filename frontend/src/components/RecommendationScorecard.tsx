import { useState } from 'react';
import type { RecommendationDimensions, DimensionScore, ExpectedReturn } from '../types';
import { useLearnStore } from '../store/learnStore';
import { getMetric } from '../lib/metrics/registry';
import { Info } from 'lucide-react';

/**
 * Four-dimensional recommendation scorecard.
 *
 * Renders one bar per dimension (Valuation / Quality / Trend / Position)
 * plus a composite score + verdict. Each bar is expandable to show the
 * drivers that fed the score.
 */
interface Props {
  dimensions: RecommendationDimensions;
  /** Forward return decomposition from IntrinsicValue.calculation_details. */
  expectedReturn?: ExpectedReturn | null;
}

// Maps a dimension's `name` (as returned by the backend) to the learn-mode
// registry key so the ⓘ button opens the right explanation.
const DIM_METRIC_KEY: Record<string, string> = {
  Valuation: 'dim_valuation',
  Quality: 'dim_quality',
  Trend: 'dim_trend',
  Position: 'dim_position',
};

const verdictColors: Record<string, string> = {
  'Strong Buy': 'bg-emerald-600 text-white',
  Buy: 'bg-emerald-500 text-white',
  Accumulate: 'bg-teal-500 text-white',
  Hold: 'bg-amber-500 text-white',
  Trim: 'bg-orange-500 text-white',
  Sell: 'bg-rose-600 text-white',
  Avoid: 'bg-rose-700 text-white',
};

function scoreColor(score: number | null): string {
  if (score === null) return 'bg-gray-500';
  if (score >= 75) return 'bg-emerald-500';
  if (score >= 60) return 'bg-teal-500';
  if (score >= 45) return 'bg-amber-500';
  if (score >= 30) return 'bg-orange-500';
  return 'bg-rose-500';
}

function DimensionRow({ dim }: { dim: DimensionScore }) {
  const [open, setOpen] = useState(false);
  const width = dim.applicable && dim.score !== null ? `${dim.score}%` : '0%';
  const color = scoreColor(dim.score);
  const openLearn = useLearnStore(s => s.open);
  const metricKey = DIM_METRIC_KEY[dim.name];
  const metric = metricKey ? getMetric(metricKey) : undefined;

  return (
    <div className="border border-dark-border rounded-lg overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full text-left px-3 py-2 hover:bg-dark-bg transition-colors"
      >
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-sm font-medium text-gray-200 inline-flex items-center gap-1.5">
            {dim.name}
            {metric && (
              <span
                role="button"
                tabIndex={0}
                onClick={(e) => {
                  e.stopPropagation();
                  openLearn({ metric, value: dim.applicable ? dim.score : null });
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.stopPropagation();
                    openLearn({ metric, value: dim.applicable ? dim.score : null });
                  }
                }}
                aria-label={`Learn about ${metric.label}`}
                className="text-gray-500 hover:text-primary-400 transition-colors cursor-help"
                title={metric.one_liner}
              >
                <Info size={12} />
              </span>
            )}
          </span>
          <span className={`text-sm font-bold ${dim.applicable ? 'text-white' : 'text-gray-500'}`}>
            {dim.applicable && dim.score !== null ? `${dim.score}` : 'n/a'}
          </span>
        </div>
        <div className="w-full h-2 bg-dark-bg rounded-full overflow-hidden">
          <div
            className={`h-full ${color} transition-all`}
            style={{ width }}
          />
        </div>
      </button>
      {open && dim.drivers.length > 0 && (
        <div className="px-3 py-2 bg-dark-bg/50 border-t border-dark-border">
          <ul className="space-y-1.5">
            {dim.drivers.map((d, i) => (
              <li key={i} className="text-xs">
                <div className="flex items-center justify-between">
                  <span className={
                    d.passed === true ? 'text-emerald-400'
                      : d.passed === false ? 'text-rose-400'
                      : 'text-gray-400'
                  }>
                    {d.passed === true ? '✓ ' : d.passed === false ? '✗ ' : '· '}
                    {d.name}
                  </span>
                </div>
                {d.detail && (
                  <div className="text-gray-500 pl-4">{d.detail}</div>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/** Business vs Valuation vs Expected-Return three-tile summary. */
function ThreeStageSummary({
  businessScore,
  valuationScore,
  expectedReturn,
}: {
  businessScore: number | null;
  valuationScore: number | null;
  expectedReturn?: ExpectedReturn | null;
}) {
  const tile = (
    label: string,
    score: number | null,
    subtitle: string,
  ) => {
    const bar = scoreColor(score);
    const applicable = score !== null;
    return (
      <div className="flex-1 p-3 rounded-lg border border-dark-border bg-dark-surface/40">
        <div className="flex items-baseline justify-between mb-1">
          <span className="text-xs uppercase tracking-wide text-gray-400">{label}</span>
          <span className={`text-lg font-bold ${applicable ? 'text-white' : 'text-gray-500'}`}>
            {applicable ? score : 'n/a'}
          </span>
        </div>
        <div className="w-full h-1.5 bg-dark-bg rounded-full overflow-hidden mb-1">
          <div
            className={`h-full ${bar} transition-all`}
            style={{ width: applicable ? `${score}%` : '0%' }}
          />
        </div>
        <p className="text-[10px] text-gray-500 leading-tight">{subtitle}</p>
      </div>
    );
  };

  // Expected return tile: shows the base scenario's annualised return as
  // a %, colour-coded against a rough Kenya 10y T-bond hurdle (~14%). The
  // subtitle collapses bear/bull into a compact range.
  const erTile = () => {
    const base = expectedReturn?.scenarios.base
      ?? expectedReturn?.scenarios.conservative
      ?? null;
    const applicable = base !== null;
    // We deliberately eyeball the bond hurdle rather than pull it live —
    // this is a heuristic, not a screening filter.
    const BOND_HURDLE = 0.14;
    const returnColor = (r: number | null): string => {
      if (r === null) return 'text-gray-500';
      if (r >= BOND_HURDLE) return 'text-emerald-400';
      if (r >= 0.10) return 'text-teal-400';
      if (r >= 0.05) return 'text-amber-400';
      if (r >= 0) return 'text-orange-400';
      return 'text-rose-400';
    };
    const bear = expectedReturn?.scenarios.bear
      ?? expectedReturn?.scenarios.conservative
      ?? null;
    const bull = expectedReturn?.scenarios.bull
      ?? expectedReturn?.scenarios.strong
      ?? null;
    const horizon = expectedReturn?.horizon_years ?? 5;
    return (
      <div className="flex-1 p-3 rounded-lg border border-dark-border bg-dark-surface/40">
        <div className="flex items-baseline justify-between mb-1">
          <span className="text-xs uppercase tracking-wide text-gray-400">
            Expected Return
          </span>
          <span className={`text-lg font-bold ${returnColor(base?.annualized_return ?? null)}`}>
            {applicable ? `${(base!.annualized_return * 100).toFixed(1)}%` : 'n/a'}
          </span>
        </div>
        {applicable && bear && bull ? (
          <p className="text-[10px] text-gray-400 leading-tight mb-1">
            {horizon}y annualised · range{' '}
            <span className="text-rose-400">{(bear.annualized_return * 100).toFixed(1)}%</span>
            {' → '}
            <span className="text-emerald-400">{(bull.annualized_return * 100).toFixed(1)}%</span>
          </p>
        ) : (
          <p className="text-[10px] text-gray-500 leading-tight mb-1">
            {horizon}y annualised
          </p>
        )}
        <p className="text-[10px] text-gray-500 leading-tight">
          Buy-and-hold return vs T-bond ~{(BOND_HURDLE * 100).toFixed(0)}%
        </p>
      </div>
    );
  };

  return (
    <div className="mb-3 flex flex-col md:flex-row gap-2">
      {tile('Business', businessScore, 'How good is the company? (Quality + Trend)')}
      {tile('Valuation', valuationScore, 'How attractive at today\u2019s price?')}
      {erTile()}
    </div>
  );
}

export default function RecommendationScorecard({ dimensions, expectedReturn }: Props) {
  const composite = dimensions.composite_score;
  const verdict = dimensions.composite_verdict;
  const verdictClass = (verdict && verdictColors[verdict]) || 'bg-gray-600 text-white';
  const openLearn = useLearnStore(s => s.open);
  const compositeMetric = getMetric('composite_score');

  return (
    <div className="mt-4 p-4 bg-dark-bg rounded-lg">
      <div className="flex items-center justify-between mb-3">
        <p className="text-sm text-gray-400 inline-flex items-center gap-1.5">
          4-dimension scorecard
          {compositeMetric && (
            <button
              type="button"
              onClick={() => openLearn({ metric: compositeMetric, value: composite })}
              aria-label="Learn about the composite scorecard"
              title={compositeMetric.one_liner}
              className="text-gray-500 hover:text-primary-400 transition-colors"
            >
              <Info size={12} />
            </button>
          )}
        </p>
        {composite !== null && verdict && (
          <div className="flex items-center gap-2">
            <span className={`px-2 py-0.5 rounded text-xs font-semibold ${verdictClass}`}>
              {verdict}
            </span>
            <span className="text-lg font-bold text-white">{composite}</span>
          </div>
        )}
      </div>

      {/* Two-stage Business vs Valuation summary — separates "how good is
          the business" from "how attractive is the price". */}
      {(dimensions.business_score !== null
        || dimensions.valuation_score !== null
        || expectedReturn) && (
        <ThreeStageSummary
          businessScore={dimensions.business_score}
          valuationScore={dimensions.valuation_score}
          expectedReturn={expectedReturn}
        />
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
        <DimensionRow dim={dimensions.valuation} />
        <DimensionRow dim={dimensions.quality} />
        <DimensionRow dim={dimensions.trend} />
        <DimensionRow dim={dimensions.position} />
      </div>
      <p className="text-xs text-gray-500 mt-3">
        Tap any dimension to see the drivers. Position is only scored when you hold the security.
      </p>
    </div>
  );
}
