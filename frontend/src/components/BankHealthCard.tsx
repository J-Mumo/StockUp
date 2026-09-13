import { Landmark } from 'lucide-react';
import MetricLabel, { verdictClassFor } from './learn/MetricLabel';
import type { FinancialStatement } from '../types';

/**
 * BankHealthCard — surfaces the four bank-specific health metrics that
 * StockUp already tracks (NPL, CAR, Cost-to-Income, Cost of Risk) as a
 * dedicated panel with Learn Mode wiring and threshold color-coding.
 *
 * Only rendered for companies in the Banking sector. If no sector_metrics
 * are present on the latest financial statement the card is hidden.
 */
interface Props {
  latestFinancial: FinancialStatement | null;
  sector: string | null | undefined;
  companyName?: string;
}

// Map of registry metric key → sector_metrics JSON key on the financial
// statement. Bank valuator reads them under these snake_case names.
const METRIC_MAP: { registryKey: string; sourceKey: string }[] = [
  { registryKey: 'npl_ratio', sourceKey: 'npl_ratio' },
  { registryKey: 'capital_adequacy_ratio', sourceKey: 'capital_adequacy_ratio' },
  { registryKey: 'cost_to_income_ratio', sourceKey: 'cost_to_income' },
  { registryKey: 'cost_of_risk', sourceKey: 'cost_of_risk' },
];

function fmtPct(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '—';
  return `${(v * 100).toFixed(2)}%`;
}

export default function BankHealthCard({ latestFinancial, sector, companyName }: Props) {
  if (!sector || !sector.toLowerCase().includes('bank')) return null;

  const sm = latestFinancial?.sector_metrics ?? null;
  const values = METRIC_MAP.map(({ registryKey, sourceKey }) => ({
    registryKey,
    sourceKey,
    value: sm?.[sourceKey] ?? null,
  }));

  // Hide card entirely when no bank data is available yet.
  if (values.every(v => v.value == null)) return null;

  return (
    <div className="mb-4 bg-dark-surface border border-dark-border rounded-xl p-5">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-base font-semibold text-white flex items-center gap-2">
          <Landmark size={16} className="text-primary-400" />
          Bank Health
        </h2>
        {latestFinancial?.fiscal_year && (
          <span className="text-[10px] px-2 py-0.5 rounded bg-dark-bg text-gray-400">
            FY {latestFinancial.fiscal_year}
          </span>
        )}
      </div>
      <p className="text-xs text-gray-500 mb-4">
        Regulatory and credit-risk metrics that matter most for a bank.
        Tap any label to learn what it means and what the healthy range is.
      </p>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {values.map(({ registryKey, value }) => {
          const verdictClass = verdictClassFor(registryKey, value);
          return (
            <div key={registryKey} className="p-3 bg-dark-bg rounded-lg">
              <MetricLabel
                metricKey={registryKey}
                value={value}
                contextLabel={companyName}
                sector={sector}
                className="mb-1"
                showIconAlways
              />
              <p className={`text-lg font-bold ${verdictClass ?? (value != null ? 'text-white' : 'text-gray-500')}`}>
                {fmtPct(value)}
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
