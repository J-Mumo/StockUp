import { useState } from 'react';
import type { RecommendationDimensions, DimensionScore } from '../types';
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

export default function RecommendationScorecard({ dimensions }: Props) {
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
