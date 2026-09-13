import { useMemo, useState, useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { Search, BookOpen } from 'lucide-react';
import { allMetrics } from '../lib/metrics/registry';
import type { MetricCategory, MetricDefinition, MetricSector } from '../lib/metrics/types';
import { useLearnStore } from '../store/learnStore';

// LearnPage — the browsable glossary of every metric StockUp explains.
// Deep-linkable via hash: /learn#npl_ratio auto-opens that metric's card.

const CATEGORY_LABELS: Record<MetricCategory, string> = {
  valuation: 'Valuation',
  profitability: 'Profitability',
  solvency: 'Solvency',
  liquidity: 'Liquidity',
  growth: 'Growth',
  efficiency: 'Efficiency',
  risk: 'Risk',
  income: 'Income',
  scorecard: 'Scorecard',
};

const SECTOR_CHIPS: { key: MetricSector; label: string }[] = [
  { key: 'all', label: 'All sectors' },
  { key: 'bank', label: 'Banks' },
  { key: 'insurance', label: 'Insurance' },
  { key: 'industrial', label: 'Industrials' },
  { key: 'reit', label: 'REITs' },
];

function MetricRow({ metric }: { metric: MetricDefinition }) {
  const open = useLearnStore(s => s.open);
  return (
    <button
      type="button"
      id={metric.key}
      onClick={() => open({ metric })}
      className="w-full text-left p-4 rounded-lg bg-dark-surface border border-dark-border hover:border-primary-500 transition-colors"
    >
      <div className="flex items-baseline justify-between gap-3 mb-1">
        <h3 className="text-base font-semibold text-white">{metric.label}</h3>
        {metric.short_label && metric.short_label !== metric.label && (
          <span className="text-xs text-gray-500">{metric.short_label}</span>
        )}
      </div>
      <p className="text-sm text-gray-400 leading-snug">{metric.one_liner}</p>
      <div className="flex flex-wrap gap-1.5 mt-2">
        {metric.sectors.filter(s => s !== 'all').map(s => (
          <span key={s} className="text-[10px] px-1.5 py-0.5 rounded bg-dark-bg text-gray-400 capitalize">
            {s}
          </span>
        ))}
        {metric.sectors.includes('all') && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-dark-bg text-gray-400">
            all sectors
          </span>
        )}
      </div>
    </button>
  );
}

export default function LearnPage() {
  const [query, setQuery] = useState('');
  const [sector, setSector] = useState<MetricSector>('all');
  const [category, setCategory] = useState<MetricCategory | 'all'>('all');
  const open = useLearnStore(s => s.open);
  const location = useLocation();

  // Deep-link support: /learn#npl_ratio opens the metric card and scrolls to it.
  useEffect(() => {
    const hash = location.hash.replace('#', '');
    if (!hash) return;
    const metric = allMetrics().find(m => m.key === hash);
    if (metric) {
      open({ metric });
      // Delay scroll until after render.
      setTimeout(() => {
        document.getElementById(hash)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }, 50);
    }
  }, [location.hash, open]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return allMetrics().filter(m => {
      if (sector !== 'all' && !m.sectors.includes('all') && !m.sectors.includes(sector)) {
        return false;
      }
      if (category !== 'all' && m.category !== category) return false;
      if (q) {
        return (
          m.label.toLowerCase().includes(q)
          || (m.short_label ?? '').toLowerCase().includes(q)
          || m.one_liner.toLowerCase().includes(q)
          || m.what_it_measures.toLowerCase().includes(q)
        );
      }
      return true;
    });
  }, [query, sector, category]);

  const grouped = useMemo(() => {
    const map = new Map<MetricCategory, MetricDefinition[]>();
    for (const m of filtered) {
      const arr = map.get(m.category) ?? [];
      arr.push(m);
      map.set(m.category, arr);
    }
    return map;
  }, [filtered]);

  const orderedCategories: MetricCategory[] = [
    'scorecard', 'valuation', 'profitability', 'growth',
    'solvency', 'liquidity', 'efficiency', 'risk', 'income',
  ];

  return (
    <div className="max-w-5xl mx-auto">
      <header className="mb-6">
        <div className="flex items-center gap-3 mb-2">
          <BookOpen className="text-primary-400" size={28} />
          <h1 className="text-2xl font-bold text-white">Learn</h1>
        </div>
        <p className="text-gray-400 text-sm max-w-2xl">
          Every metric StockUp shows, explained in plain English. Tap a card for
          the full breakdown — what it measures, how it's calculated, what high
          and low mean, and what to watch out for.
        </p>
      </header>

      {/* Filters */}
      <div className="bg-dark-surface border border-dark-border rounded-lg p-4 mb-6 space-y-3">
        <div className="relative">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
          <input
            type="search"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Search metrics… (e.g. ROE, NPL, cash flow)"
            className="w-full bg-dark-bg border border-dark-border rounded-md pl-9 pr-3 py-2 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-primary-500"
          />
        </div>

        <div>
          <p className="text-[11px] text-gray-500 uppercase tracking-wider mb-1.5">Sector</p>
          <div className="flex flex-wrap gap-1.5">
            {SECTOR_CHIPS.map(chip => (
              <button
                key={chip.key}
                type="button"
                onClick={() => setSector(chip.key)}
                className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${
                  sector === chip.key
                    ? 'bg-primary-600/30 border-primary-500 text-primary-200'
                    : 'bg-dark-bg border-dark-border text-gray-400 hover:text-gray-200'
                }`}
              >
                {chip.label}
              </button>
            ))}
          </div>
        </div>

        <div>
          <p className="text-[11px] text-gray-500 uppercase tracking-wider mb-1.5">Category</p>
          <div className="flex flex-wrap gap-1.5">
            <button
              type="button"
              onClick={() => setCategory('all')}
              className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${
                category === 'all'
                  ? 'bg-primary-600/30 border-primary-500 text-primary-200'
                  : 'bg-dark-bg border-dark-border text-gray-400 hover:text-gray-200'
              }`}
            >
              All
            </button>
            {(Object.keys(CATEGORY_LABELS) as MetricCategory[]).map(cat => (
              <button
                key={cat}
                type="button"
                onClick={() => setCategory(cat)}
                className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${
                  category === cat
                    ? 'bg-primary-600/30 border-primary-500 text-primary-200'
                    : 'bg-dark-bg border-dark-border text-gray-400 hover:text-gray-200'
                }`}
              >
                {CATEGORY_LABELS[cat]}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Results */}
      {filtered.length === 0 ? (
        <div className="text-center py-16 text-gray-500 text-sm">
          No metrics match those filters.
        </div>
      ) : (
        <div className="space-y-8">
          {orderedCategories.map(cat => {
            const list = grouped.get(cat);
            if (!list || list.length === 0) return null;
            return (
              <section key={cat}>
                <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider mb-3">
                  {CATEGORY_LABELS[cat]}
                </h2>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {list.map(m => <MetricRow key={m.key} metric={m} />)}
                </div>
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}
