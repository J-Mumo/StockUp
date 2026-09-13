import { useEffect } from 'react';
import { X } from 'lucide-react';
import { useLearnStore } from '../../store/learnStore';
import { formatMetricValue, getMetric, verdictForValue } from '../../lib/metrics/registry';
import type { MetricVerdict } from '../../lib/metrics/types';

// LearnCard — the slide-in drawer / bottom-sheet that shows the full
// explanation for a metric. Mounted once at the app root; controlled by the
// learn store. Related-metric chips swap the content in place, enabling the
// user to browse the glossary without closing the sheet.

const verdictBadge: Record<MetricVerdict, string> = {
  good: 'bg-emerald-600/20 text-emerald-300 border-emerald-600/40',
  ok: 'bg-teal-600/20 text-teal-300 border-teal-600/40',
  caution: 'bg-amber-600/20 text-amber-300 border-amber-600/40',
  bad: 'bg-rose-600/20 text-rose-300 border-rose-600/40',
};

const verdictWord: Record<MetricVerdict, string> = {
  good: 'Strong',
  ok: 'Healthy',
  caution: 'Watch',
  bad: 'Weak',
};

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-t border-dark-border pt-3 mt-3 first:border-t-0 first:pt-0 first:mt-0">
      <h4 className="text-[11px] font-semibold text-gray-500 uppercase tracking-wider mb-1.5">
        {title}
      </h4>
      <div className="text-sm text-gray-200 leading-relaxed">{children}</div>
    </section>
  );
}

export default function LearnCard() {
  const active = useLearnStore(s => s.active);
  const close = useLearnStore(s => s.close);
  const open = useLearnStore(s => s.open);

  useEffect(() => {
    if (!active) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [active, close]);

  if (!active) return null;

  const { metric, value, contextLabel, sector } = active;
  const verdict = verdictForValue(metric, value);

  return (
    <>
      {/* Overlay */}
      <div
        className="fixed inset-0 bg-black/50 z-50 animate-in fade-in"
        onClick={close}
        aria-hidden="true"
      />

      {/* Drawer (desktop: right side) / Bottom-sheet (mobile) */}
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="learn-card-title"
        className="fixed z-50 bg-dark-surface border-dark-border shadow-2xl
                   inset-x-0 bottom-0 max-h-[85vh] rounded-t-2xl border-t
                   sm:inset-y-0 sm:right-0 sm:left-auto sm:bottom-auto sm:max-h-none
                   sm:w-[420px] sm:rounded-none sm:border-l sm:border-t-0
                   overflow-y-auto"
      >
        {/* Header */}
        <div className="sticky top-0 bg-dark-surface border-b border-dark-border px-5 py-4 flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <h3 id="learn-card-title" className="text-lg font-bold text-white">
                {metric.label}
              </h3>
              {verdict && (
                <span
                  className={`text-[10px] px-2 py-0.5 rounded-full border font-semibold ${verdictBadge[verdict.verdict]}`}
                  title={verdict.note ?? undefined}
                >
                  {verdictWord[verdict.verdict]}
                </span>
              )}
            </div>
            {value != null && (
              <p className="text-sm text-gray-400 mt-0.5">
                <span className="font-semibold text-white">
                  {formatMetricValue(metric, value)}
                </span>
                {contextLabel && <span className="text-gray-500"> · {contextLabel}</span>}
                {sector && <span className="text-gray-500"> · {sector}</span>}
              </p>
            )}
            <p className="text-xs text-gray-500 mt-1 italic">{metric.one_liner}</p>
          </div>
          <button
            type="button"
            onClick={close}
            className="p-1 -mr-1 rounded text-gray-400 hover:text-white hover:bg-dark-border/60"
            aria-label="Close"
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="px-5 py-4">
          <Section title="What it measures">
            <p>{metric.what_it_measures}</p>
          </Section>

          <Section title="How it's calculated">
            <p>{metric.how_its_calculated}</p>
          </Section>

          <Section title="What a high value means">
            <p>{metric.what_high_means}</p>
          </Section>

          <Section title="What a low value means">
            <p>{metric.what_low_means}</p>
          </Section>

          {metric.watch_outs.length > 0 && (
            <Section title="Watch-outs">
              <ul className="list-disc pl-5 space-y-1.5">
                {metric.watch_outs.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            </Section>
          )}

          {metric.rule_of_thumb && (
            <Section title="Rule of thumb">
              <p className="italic text-gray-300">{metric.rule_of_thumb}</p>
            </Section>
          )}

          {verdict?.note && (
            <Section title="On this value">
              <p>{verdict.note}</p>
            </Section>
          )}

          {metric.related_metrics && metric.related_metrics.length > 0 && (
            <Section title="Related">
              <div className="flex flex-wrap gap-1.5 mt-1">
                {metric.related_metrics.map(key => {
                  const rel = getMetric(key);
                  if (!rel) return null;
                  return (
                    <button
                      key={key}
                      type="button"
                      onClick={() => open({ metric: rel, sector })}
                      className="text-xs px-2 py-1 rounded-full bg-dark-bg border border-dark-border hover:border-primary-500 hover:text-primary-300 transition-colors"
                    >
                      {rel.short_label ?? rel.label}
                    </button>
                  );
                })}
              </div>
            </Section>
          )}

          <p className="text-[11px] text-gray-500 mt-6 pt-3 border-t border-dark-border">
            Educational content. Not investment advice.
          </p>
        </div>
      </div>
    </>
  );
}
