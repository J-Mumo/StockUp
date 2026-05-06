import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Search, Filter, Building2 } from 'lucide-react';
import { stocksApi } from '../lib/services';
import type { Company } from '../types';
import { SkeletonTable } from '../components/ui/LoadingSpinner';

function formatKES(value: number | null): string {
  if (value == null) return '—';
  return `KES ${value.toFixed(2)}`;
}

function formatMoS(value: number | null): string {
  if (value == null) return '—';
  // Backend stores MoS as a ratio (0.667 = 66.7%)
  const pct = value * 100;
  return `${pct.toFixed(1)}%`;
}

const recColors: Record<string, string> = {
  'Strong Buy': 'text-green-400',
  'Buy': 'text-green-400',
  'Hold': 'text-yellow-400',
  'Sell': 'text-red-400',
  'Strong Sell': 'text-red-400',
};

interface CompanySectionProps {
  title: string;
  companies: Company[];
  badge?: string;
}

function CompanySection({ title, companies, badge }: CompanySectionProps) {
  if (companies.length === 0) return null;

  return (
    <div className="mb-8">
      <div className="flex items-center gap-3 mb-3">
        <h2 className="text-lg font-semibold text-white">{title}</h2>
        {badge && (
          <span className="px-2 py-0.5 bg-primary-500/20 text-primary-400 text-xs font-medium rounded-full">
            {badge}
          </span>
        )}
        <span className="text-gray-500 text-sm">({companies.length})</span>
      </div>
      <div className="bg-dark-surface border border-dark-border rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="text-left text-xs text-gray-400 border-b border-dark-border bg-dark-bg/50">
                <th className="px-4 py-3 font-medium">Company</th>
                <th className="px-4 py-3 font-medium">Ticker</th>
                <th className="px-4 py-3 font-medium">Sector</th>
                <th className="px-4 py-3 font-medium text-right">Market Price</th>
                <th className="px-4 py-3 font-medium text-right">Intrinsic Value</th>
                <th className="px-4 py-3 font-medium text-right">Margin of Safety</th>
                <th className="px-4 py-3 font-medium text-center">Signal</th>
              </tr>
            </thead>
            <tbody>
              {companies.map((company) => {
                const mosVal = company.margin_of_safety_pct;
                const mosPositive = mosVal != null && mosVal > 0;
                const mosNegative = mosVal != null && mosVal < 0;

                return (
                  <tr key={company.id} className="border-b border-dark-border/50 hover:bg-dark-border/20 transition-colors">
                    <td className="px-4 py-3">
                      <Link
                        to={`/companies/${company.id}`}
                        className="text-white hover:text-primary-400 font-medium text-sm"
                      >
                        {company.name}
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-gray-400 font-mono text-xs">{company.ticker_symbol}</td>
                    <td className="px-4 py-3">
                      {company.sector ? (
                        <span className="px-2 py-0.5 bg-dark-border/50 rounded text-xs text-gray-300">
                          {company.sector}
                        </span>
                      ) : (
                        <span className="text-gray-600 text-xs">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right text-sm text-gray-300 font-mono">
                      {formatKES(company.latest_price)}
                    </td>
                    <td className="px-4 py-3 text-right text-sm text-gray-300 font-mono">
                      {formatKES(company.intrinsic_value)}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <span className={`text-sm font-mono font-medium ${
                        mosPositive ? 'text-green-400' : mosNegative ? 'text-red-400' : 'text-gray-500'
                      }`}>
                        {formatMoS(mosVal)}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-center">
                      {company.recommendation ? (
                        <span className={`text-xs font-medium ${recColors[company.recommendation] || 'text-gray-400'}`}>
                          {company.recommendation}
                        </span>
                      ) : (
                        <span className="text-gray-600 text-xs">—</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

export default function CompaniesPage() {
  const [companies, setCompanies] = useState<Company[]>([]);
  const [sectors, setSectors] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [selectedSector, setSelectedSector] = useState('');

  useEffect(() => {
    stocksApi.getSectors().then((res) => setSectors(res.data)).catch(() => {});
  }, []);

  useEffect(() => {
    setLoading(true);
    const params: { search?: string; sector?: string } = {};
    if (search) params.search = search;
    if (selectedSector) params.sector = selectedSector;

    stocksApi.getCompanies(params)
      .then((res) => setCompanies(res.data))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [search, selectedSector]);

  // Debounce search
  const [searchInput, setSearchInput] = useState('');
  useEffect(() => {
    const timer = setTimeout(() => setSearch(searchInput), 300);
    return () => clearTimeout(timer);
  }, [searchInput]);

  // Sort by Margin of Safety descending (most undervalued first), nulls last
  const sorted = [...companies].sort((a, b) => {
    const aMos = a.margin_of_safety_pct;
    const bMos = b.margin_of_safety_pct;
    if (aMos == null && bMos == null) return 0;
    if (aMos == null) return 1;
    if (bMos == null) return -1;
    return bMos - aMos;
  });

  // Split into sections
  const nse20 = sorted.filter((c) => c.index_membership === 'NSE 20');
  const nse25 = sorted.filter((c) => c.index_membership === 'NSE 25');
  const others = sorted.filter((c) => !c.index_membership);

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-white">Companies</h1>
        <span className="text-sm text-gray-400">{companies.length} companies</span>
      </div>

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-3 mb-6">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={18} />
          <input
            type="text"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Search companies..."
            className="w-full pl-10 pr-4 py-2.5 bg-dark-surface border border-dark-border rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
          />
        </div>
        <div className="relative">
          <Filter className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={18} />
          <select
            value={selectedSector}
            onChange={(e) => setSelectedSector(e.target.value)}
            className="pl-10 pr-8 py-2.5 bg-dark-surface border border-dark-border rounded-lg text-white appearance-none focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent min-w-[180px]"
          >
            <option value="">All Sectors</option>
            {sectors.map((sector) => (
              <option key={sector} value={sector}>{sector}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Companies Table */}
      {loading ? (
        <SkeletonTable rows={8} />
      ) : companies.length === 0 ? (
        <div className="bg-dark-surface border border-dark-border rounded-xl p-12 text-center">
          <Building2 className="text-gray-600 mx-auto mb-3" size={40} />
          <p className="text-gray-400">No companies found</p>
          {(search || selectedSector) && (
            <button
              onClick={() => { setSearchInput(''); setSelectedSector(''); }}
              className="mt-3 text-primary-400 hover:text-primary-300 text-sm"
            >
              Clear filters
            </button>
          )}
        </div>
      ) : (
        <>
          <CompanySection title="NSE 20 Share Index" companies={nse20} badge="Blue Chip" />
          <CompanySection title="NSE 25 Share Index" companies={nse25} badge="Top 25" />
          <CompanySection title="Other Listed Companies" companies={others} />
        </>
      )}
    </div>
  );
}
