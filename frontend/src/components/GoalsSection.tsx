import { useEffect, useMemo, useState } from 'react';
import { Target, ChevronDown, ChevronRight, Info } from 'lucide-react';
import { goalsApi } from '../lib/services';
import type { CompanyGoal, GoalCategory, GoalScorecardRow, GoalStatus, CompanyGoalProgress } from '../types';

interface Props {
  companyId: number;
}

const STATUS_META: Record<GoalStatus, { label: string; bg: string; text: string; dot: string }> = {
  achieved: { label: 'Achieved', bg: 'bg-green-900/40 border-green-600', text: 'text-green-300', dot: 'bg-green-500' },
  on_track: { label: 'On track', bg: 'bg-emerald-900/40 border-emerald-600', text: 'text-emerald-300', dot: 'bg-emerald-500' },
  partially_achieved: { label: 'Partial', bg: 'bg-yellow-900/40 border-yellow-600', text: 'text-yellow-300', dot: 'bg-yellow-500' },
  missed: { label: 'Missed', bg: 'bg-red-900/40 border-red-600', text: 'text-red-300', dot: 'bg-red-500' },
  abandoned: { label: 'Abandoned', bg: 'bg-gray-700/60 border-gray-500', text: 'text-gray-300', dot: 'bg-gray-400' },
  no_mention: { label: 'No mention', bg: 'bg-slate-800/60 border-slate-600', text: 'text-slate-400', dot: 'bg-slate-500' },
};

const CATEGORY_COLOR: Record<GoalCategory, string> = {
  financial: 'bg-blue-900/50 text-blue-300 border-blue-700',
  strategic: 'bg-purple-900/50 text-purple-300 border-purple-700',
  esg: 'bg-emerald-900/50 text-emerald-300 border-emerald-700',
  operational: 'bg-orange-900/50 text-orange-300 border-orange-700',
};

const CATEGORY_FILTERS: { value: GoalCategory | 'all'; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'financial', label: 'Financial' },
  { value: 'strategic', label: 'Strategic' },
  { value: 'esg', label: 'ESG' },
  { value: 'operational', label: 'Operational' },
];

function ProgressChip({ p }: { p: CompanyGoalProgress }) {
  const meta = STATUS_META[p.status];
  return (
    <div
      className={`group relative inline-flex items-center gap-1 px-2 py-1 rounded border text-xs ${meta.bg} ${meta.text}`}
      title={`FY${p.assessed_in_fiscal_year} — ${meta.label}`}
    >
      <span className={`w-2 h-2 rounded-full ${meta.dot}`} />
      <span className="font-medium">FY{p.assessed_in_fiscal_year}</span>
      <span className="opacity-75">{meta.label}</span>
      <span className="text-[10px] px-1 rounded bg-black/30 uppercase">{p.assessment_method === 'mechanical' ? 'M' : p.assessment_method === 'llm' ? 'AI' : 'man'}</span>

      {/* Tooltip */}
      <div className="absolute left-0 top-full mt-1 z-20 hidden group-hover:block w-80 p-3 bg-dark-bg border border-dark-border rounded-lg shadow-xl text-left">
        <div className="text-xs font-semibold text-white mb-1">
          FY{p.assessed_in_fiscal_year}: {meta.label}
          <span className="ml-2 opacity-60">({p.confidence} confidence, {p.assessment_method})</span>
        </div>
        {p.actual_value != null && (
          <div className="text-xs text-gray-300 mb-1">Actual: {p.actual_value}</div>
        )}
        {p.narrative && (
          <div className="text-xs text-gray-300 mb-2 whitespace-pre-wrap">{p.narrative}</div>
        )}
        {p.evidence_quote && (
          <blockquote className="text-xs italic text-gray-400 border-l-2 border-gray-600 pl-2 whitespace-pre-wrap">
            "{p.evidence_quote}"
          </blockquote>
        )}
      </div>
    </div>
  );
}

function GoalCard({ goal }: { goal: CompanyGoal }) {
  const [expanded, setExpanded] = useState(false);
  const target =
    goal.target_value != null
      ? `${goal.target_value}${goal.target_unit ? ` ${goal.target_unit}` : ''}${goal.metric_name ? ` (${goal.metric_name})` : ''}`
      : null;

  return (
    <div className="border border-dark-border rounded-lg p-3 bg-dark-bg/40">
      <div className="flex items-start gap-2">
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-gray-400 hover:text-white mt-0.5"
          title={expanded ? 'Collapse' : 'Expand'}
        >
          {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        </button>
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2 mb-1">
            <span className={`text-[10px] uppercase tracking-wide px-2 py-0.5 rounded border ${CATEGORY_COLOR[goal.goal_category]}`}>
              {goal.goal_category}
            </span>
            {target && (
              <span className="text-xs text-gray-400">Target: <span className="text-white font-medium">{target}</span></span>
            )}
            {goal.target_horizon_year && (
              <span className="text-xs text-gray-400">by <span className="text-white">FY{goal.target_horizon_year}</span></span>
            )}
            {goal.source_section && (
              <span className="text-[10px] text-gray-500">[{goal.source_section}]</span>
            )}
          </div>
          <p className="text-sm text-gray-200">{goal.goal_text}</p>

          {/* Progress strip */}
          {goal.progress.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-2">
              {goal.progress.map(p => <ProgressChip key={p.id} p={p} />)}
            </div>
          )}
          {goal.progress.length === 0 && (
            <div className="mt-2 text-xs text-gray-500 italic">Not yet assessed.</div>
          )}

          {expanded && goal.source_quote && (
            <blockquote className="mt-3 text-xs italic text-gray-400 border-l-2 border-gray-600 pl-3 whitespace-pre-wrap">
              "{goal.source_quote}"
            </blockquote>
          )}
        </div>
      </div>
    </div>
  );
}

function ScorecardBar({ row }: { row: GoalScorecardRow }) {
  const total = row.goals_total || 1;
  const segments: { key: GoalStatus | 'not_yet_assessed'; count: number; color: string }[] = [
    { key: 'achieved', count: row.achieved, color: 'bg-green-500' },
    { key: 'on_track', count: row.on_track, color: 'bg-emerald-500' },
    { key: 'partially_achieved', count: row.partially_achieved, color: 'bg-yellow-500' },
    { key: 'missed', count: row.missed, color: 'bg-red-500' },
    { key: 'abandoned', count: row.abandoned, color: 'bg-gray-500' },
    { key: 'no_mention', count: row.no_mention, color: 'bg-slate-600' },
    { key: 'not_yet_assessed', count: row.not_yet_assessed, color: 'bg-slate-800' },
  ];

  return (
    <div className="flex items-center gap-3 text-xs">
      <span className="font-mono text-gray-300 w-14">FY{row.fiscal_year_set}</span>
      <span className="text-gray-400 w-20">{row.goals_total} goal{row.goals_total === 1 ? '' : 's'}</span>
      <div className="flex-1 flex h-3 rounded overflow-hidden border border-dark-border" title={`${row.achieved} achieved · ${row.on_track} on track · ${row.partially_achieved} partial · ${row.missed} missed · ${row.abandoned} abandoned · ${row.no_mention} no mention · ${row.not_yet_assessed} not yet assessed`}>
        {segments.map(s => s.count > 0 && (
          <div
            key={s.key}
            className={s.color}
            style={{ width: `${(s.count / total) * 100}%` }}
            title={`${s.key}: ${s.count}`}
          />
        ))}
      </div>
      <span className="text-gray-400 w-32 text-right">
        {row.achieved + row.on_track} ✓ · {row.partially_achieved} ~ · {row.missed + row.abandoned} ✗
      </span>
    </div>
  );
}

export default function GoalsSection({ companyId }: Props) {
  const [goals, setGoals] = useState<CompanyGoal[]>([]);
  const [scorecard, setScorecard] = useState<GoalScorecardRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(true);
  const [categoryFilter, setCategoryFilter] = useState<GoalCategory | 'all'>('all');

  useEffect(() => {
    if (!companyId) return;
    setLoading(true);
    Promise.all([
      goalsApi.list(companyId).catch(() => ({ data: [] as CompanyGoal[] })),
      goalsApi.scorecard(companyId).catch(() => ({ data: [] as GoalScorecardRow[] })),
    ])
      .then(([g, s]) => {
        setGoals(g.data);
        setScorecard(s.data);
      })
      .finally(() => setLoading(false));
  }, [companyId]);

  const filtered = useMemo(
    () => goals.filter(g => categoryFilter === 'all' || g.goal_category === categoryFilter),
    [goals, categoryFilter],
  );

  const grouped = useMemo(() => {
    const out: Record<number, CompanyGoal[]> = {};
    for (const g of filtered) {
      (out[g.fiscal_year_set] ||= []).push(g);
    }
    return Object.entries(out)
      .map(([y, gs]) => ({ year: Number(y), goals: gs }))
      .sort((a, b) => b.year - a.year);
  }, [filtered]);

  if (!loading && goals.length === 0) return null;

  return (
    <div className="bg-dark-surface border border-dark-border rounded-xl p-6 mb-6">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 w-full text-left"
      >
        <Target size={18} className="text-primary-400" />
        <h3 className="text-lg font-semibold flex-1">
          Management Goals ({goals.length})
        </h3>
        {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
      </button>

      {expanded && (
        <div className="mt-4">
          {loading && <p className="text-gray-400 text-sm">Loading goals…</p>}

          {!loading && scorecard.length > 0 && (
            <div className="mb-5 p-3 bg-dark-bg/40 rounded-lg border border-dark-border">
              <div className="flex items-center gap-2 mb-2 text-xs text-gray-400">
                <Info size={12} /> Goal scorecard — latest known outcome per goal, grouped by year set
              </div>
              <div className="space-y-1.5">
                {scorecard.map(row => <ScorecardBar key={row.fiscal_year_set} row={row} />)}
              </div>
            </div>
          )}

          {/* Category filter */}
          {!loading && goals.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-3">
              {CATEGORY_FILTERS.map(f => (
                <button
                  key={f.value}
                  onClick={() => setCategoryFilter(f.value)}
                  className={`text-xs px-3 py-1 rounded border transition-colors ${
                    categoryFilter === f.value
                      ? 'bg-primary-600 border-primary-500 text-white'
                      : 'bg-dark-bg border-dark-border text-gray-400 hover:text-white'
                  }`}
                >
                  {f.label}
                </button>
              ))}
            </div>
          )}

          {/* Goals grouped by year */}
          <div className="space-y-4">
            {grouped.map(group => (
              <div key={group.year}>
                <h4 className="text-sm font-semibold text-gray-300 mb-2">
                  Set in FY{group.year} <span className="text-gray-500 font-normal">— {group.goals.length} goal{group.goals.length === 1 ? '' : 's'}</span>
                </h4>
                <div className="space-y-2">
                  {group.goals.map(g => <GoalCard key={g.id} goal={g} />)}
                </div>
              </div>
            ))}
            {!loading && grouped.length === 0 && (
              <p className="text-gray-400 text-sm text-center py-4">No goals match this filter.</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
