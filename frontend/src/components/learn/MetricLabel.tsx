import { Info } from 'lucide-react';
import { getMetric, verdictForValue } from '../../lib/metrics/registry';
import type { MetricVerdict } from '../../lib/metrics/types';
import { useLearnStore } from '../../store/learnStore';

/**
 * MetricLabel — the standard label used next to any financial metric in the UI.
 *
 * Renders the metric's label plus an info icon that opens the LearnCard drawer
 * on click. When Learn Mode is enabled globally, the one-liner also renders
 * inline beneath the label, and the associated value can be color-tinted by
 * threshold verdict.
 */
interface Props {
  metricKey: string;
  value?: number | null;
  contextLabel?: string;   // e.g. company name — shown inside the LearnCard header
  sector?: string | null;
  size?: 'sm' | 'md';
  className?: string;
  as?: 'span' | 'p' | 'div';
  showIconAlways?: boolean;  // force icon visible even when Learn Mode is off
  hideOneLiner?: boolean;    // suppress inline one-liner (dense contexts like table headers)
  alwaysShowOneLiner?: boolean; // force inline one-liner regardless of Learn Mode
  labelOverride?: string;    // display a different label than the metric's default
}

const verdictClass: Record<MetricVerdict, string> = {
  good: 'text-emerald-400',
  ok: 'text-teal-400',
  caution: 'text-amber-400',
  bad: 'text-rose-400',
};

export function verdictClassFor(
  metricKey: string,
  value: number | null | undefined,
): string | null {
  const m = getMetric(metricKey);
  if (!m) return null;
  const v = verdictForValue(m, value);
  return v ? verdictClass[v.verdict] : null;
}

export default function MetricLabel({
  metricKey,
  value,
  contextLabel,
  sector,
  size = 'sm',
  className = '',
  as: Tag = 'p',
  showIconAlways = false,
  hideOneLiner = false,
  alwaysShowOneLiner = false,
  labelOverride,
}: Props) {
  const metric = getMetric(metricKey);
  const enabled = useLearnStore(s => s.enabled);
  const open = useLearnStore(s => s.open);

  if (!metric) {
    // Fallback to raw key so missing registrations are visible in dev.
    return <Tag className={className}>{labelOverride ?? metricKey}</Tag>;
  }

  const showIcon = enabled || showIconAlways;
  const textSize = size === 'md' ? 'text-sm' : 'text-xs';

  const handleClick = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    open({ metric, value, contextLabel, sector });
  };

  return (
    <Tag className={`${textSize} text-gray-400 ${className}`}>
      <button
        type="button"
        onClick={handleClick}
        aria-label={`Learn about ${metric.label}`}
        className="group inline-flex items-center gap-1 hover:text-gray-200 transition-colors cursor-pointer"
      >
        <span>{labelOverride ?? metric.label}</span>
        <Info
          size={size === 'md' ? 14 : 12}
          className={`${showIcon ? 'opacity-70' : 'opacity-0 group-hover:opacity-70'} transition-opacity`}
        />
      </button>
      {(alwaysShowOneLiner || enabled) && !hideOneLiner && (
        <span className="block mt-0.5 text-[11px] text-gray-500 leading-snug">
          {metric.one_liner}
        </span>
      )}
    </Tag>
  );
}
