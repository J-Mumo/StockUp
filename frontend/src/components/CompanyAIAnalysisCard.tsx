/**
 * AI-generated per-company research narrative card.
 *
 * Renders on the company detail page. Loads (or generates on-demand) the
 * latest analysis for the company. Shows a summary strip (verdict, IV
 * range, cache freshness), the markdown narrative, and expandable
 * bull/bear/risk/caveat lists.
 *
 * The heavy lifting — grounding, fingerprint cache, prompt versioning —
 * lives in the backend service. This component is purely presentational
 * plus a couple of user actions (refresh, expand-all).
 */

import { useCallback, useEffect, useState } from 'react';
import { Sparkles, RefreshCw, AlertTriangle, ChevronDown, ChevronUp } from 'lucide-react';
import toast from 'react-hot-toast';

import { companyAIAnalysisApi } from '../lib/services';
import type { CompanyAIAnalysis } from '../types';

interface Props {
  companyId: number;
  companyName: string;
}

function formatDateTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

function ageInDays(iso: string): number {
  const diff = Date.now() - new Date(iso).getTime();
  return Math.max(0, Math.round(diff / (1000 * 60 * 60 * 24)));
}

function verdictColor(verdict: string | null | undefined): string {
  const v = (verdict || '').toLowerCase();
  if (v.includes('avoid') || v.includes('caution')) return 'text-red-400 border-red-400/40 bg-red-400/10';
  if (v.includes('wait') || v.includes('watch')) return 'text-amber-400 border-amber-400/40 bg-amber-400/10';
  if (v.includes('consider')) return 'text-emerald-400 border-emerald-400/40 bg-emerald-400/10';
  return 'text-gray-300 border-gray-500/40 bg-gray-500/10';
}

function BulletList({
  title,
  items,
  emphasis,
}: {
  title: string;
  items: string[] | null | undefined;
  emphasis: 'positive' | 'negative' | 'risk' | 'neutral';
}) {
  if (!items || items.length === 0) return null;
  const colors: Record<string, string> = {
    positive: 'text-emerald-400',
    negative: 'text-red-400',
    risk: 'text-amber-400',
    neutral: 'text-gray-400',
  };
  return (
    <div>
      <div className={`text-xs font-semibold uppercase tracking-wide mb-1.5 ${colors[emphasis]}`}>
        {title}
      </div>
      <ul className="space-y-1 text-sm text-gray-200">
        {items.map((item, i) => (
          <li key={i} className="flex gap-2">
            <span className={colors[emphasis]}>•</span>
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function CompanyAIAnalysisCard({ companyId, companyName }: Props) {
  const [analysis, setAnalysis] = useState<CompanyAIAnalysis | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [narrativeOpen, setNarrativeOpen] = useState(true);

  const loadAnalysis = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await companyAIAnalysisApi.get(companyId);
      setAnalysis(resp.data);
    } catch (err: any) {
      const detail = err?.response?.data?.detail || err?.message || 'Failed to load AI analysis';
      setError(String(detail));
    } finally {
      setLoading(false);
    }
  }, [companyId]);

  useEffect(() => {
    loadAnalysis();
  }, [loadAnalysis]);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      const resp = await companyAIAnalysisApi.refresh(companyId);
      setAnalysis(resp.data);
      toast.success('Analysis regenerated');
    } catch (err: any) {
      const detail = err?.response?.data?.detail || err?.message || 'Refresh failed';
      toast.error(String(detail));
    } finally {
      setRefreshing(false);
    }
  };

  // ------- Render states -------

  if (loading && !analysis) {
    return (
      <div className="bg-dark-card border border-dark-border rounded-lg p-4">
        <div className="flex items-center gap-2 mb-3">
          <Sparkles className="w-4 h-4 text-primary-400" />
          <h3 className="text-sm font-semibold text-white">AI Analysis</h3>
        </div>
        <div className="text-sm text-gray-400">
          Generating a fresh analysis for {companyName}… this may take a few seconds.
        </div>
      </div>
    );
  }

  if (error && !analysis) {
    return (
      <div className="bg-dark-card border border-red-500/40 rounded-lg p-4">
        <div className="flex items-center gap-2 mb-2">
          <AlertTriangle className="w-4 h-4 text-red-400" />
          <h3 className="text-sm font-semibold text-white">AI Analysis unavailable</h3>
        </div>
        <div className="text-sm text-gray-300 mb-3">{error}</div>
        <button
          onClick={loadAnalysis}
          className="text-xs px-3 py-1.5 bg-dark-bg border border-dark-border rounded hover:bg-dark-border transition-colors"
        >
          Retry
        </button>
      </div>
    );
  }

  if (!analysis) return null;

  const s = analysis.structured_json || {};
  const verdict = s.verdict || 'Watch';
  const ageDays = ageInDays(analysis.generated_at);

  return (
    <div className="bg-dark-card border border-dark-border rounded-lg overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-dark-border flex items-start justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-primary-400" />
          <h3 className="text-sm font-semibold text-white">AI Analysis</h3>
          <span className={`text-xs px-2 py-0.5 rounded-full border ${verdictColor(verdict)}`}>
            {verdict}
          </span>
        </div>
        <div className="flex items-center gap-3">
          <div className="text-xs text-gray-500">
            {formatDateTime(analysis.generated_at)} · {ageDays}d ago
            {analysis.from_cache ? ' · cached' : ' · fresh'}
          </div>
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className="text-xs inline-flex items-center gap-1 px-2 py-1 bg-dark-bg border border-dark-border rounded hover:bg-dark-border disabled:opacity-50 transition-colors"
            title="Force a new analysis (spends an LLM call)"
          >
            <RefreshCw className={`w-3 h-3 ${refreshing ? 'animate-spin' : ''}`} />
            {refreshing ? 'Regenerating…' : 'Refresh'}
          </button>
        </div>
      </div>

      {/* IV range strip */}
      {(s.iv_low_kes != null || s.iv_high_kes != null) && (
        <div className="px-4 py-2 bg-dark-bg/40 border-b border-dark-border text-xs text-gray-400">
          <span className="text-gray-500">AI intrinsic-value range:</span>{' '}
          <span className="text-white font-medium">
            KES {s.iv_low_kes != null ? s.iv_low_kes.toFixed(2) : '?'} –{' '}
            {s.iv_high_kes != null ? s.iv_high_kes.toFixed(2) : '?'}
          </span>
        </div>
      )}

      {/* Narrative (collapsible) */}
      <div className="p-4 space-y-4">
        <div>
          <button
            onClick={() => setNarrativeOpen((v) => !v)}
            className="w-full flex items-center justify-between text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2"
          >
            <span>Narrative</span>
            {narrativeOpen ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
          </button>
          {narrativeOpen && (
            // Rendered as pre-wrap markdown — same treatment as the chat
            // panel. A proper markdown renderer can slot in later without
            // touching the data shape.
            <div className="text-sm text-gray-200 whitespace-pre-wrap leading-relaxed">
              {analysis.narrative_md}
            </div>
          )}
        </div>

        {/* Structured breakdown */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <BulletList title="Bull points" items={s.bull_points} emphasis="positive" />
          <BulletList title="Bear points" items={s.bear_points} emphasis="negative" />
          <BulletList title="Key risks" items={s.key_risks} emphasis="risk" />
          <BulletList title="Caveats" items={s.caveats} emphasis="neutral" />
        </div>

        {s.sector_specific_notes && s.sector_specific_notes.length > 0 && (
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide mb-1.5 text-primary-400">
              Sector notes
            </div>
            <ul className="space-y-1 text-sm text-gray-200">
              {s.sector_specific_notes.map((item, i) => (
                <li key={i} className="flex gap-2">
                  <span className="text-primary-400">•</span>
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {/* Footer — provenance so users know what the AI actually saw */}
      <div className="px-4 py-2 border-t border-dark-border text-[10px] text-gray-500 flex items-center justify-between flex-wrap gap-1">
        <span>
          Model: {analysis.model_name} · Prompt {analysis.prompt_version} ·{' '}
          Sector: {analysis.sector_kind || 'unknown'} · Trigger: {analysis.triggered_by}
        </span>
        <span>
          This is an educational research aid, not investment advice.
        </span>
      </div>
    </div>
  );
}
