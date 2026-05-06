import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Search, Filter, Building2 } from 'lucide-react';
import { stocksApi } from '../lib/services';
import type { Company } from '../types';
import { SkeletonTable } from '../components/ui/LoadingSpinner';

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

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-white">Companies</h1>
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
        <div className="bg-dark-surface border border-dark-border rounded-xl overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="text-left text-sm text-gray-400 border-b border-dark-border bg-dark-bg/50">
                  <th className="px-6 py-3 font-medium">Company</th>
                  <th className="px-6 py-3 font-medium">Symbol</th>
                  <th className="px-6 py-3 font-medium">Sector</th>
                  <th className="px-6 py-3 font-medium text-right">Market Cap</th>
                </tr>
              </thead>
              <tbody>
                {companies.map((company) => (
                  <tr key={company.id} className="border-b border-dark-border/50 hover:bg-dark-border/20 transition-colors">
                    <td className="px-6 py-4">
                      <Link
                        to={`/companies/${company.id}`}
                        className="text-white hover:text-primary-400 font-medium"
                      >
                        {company.name}
                      </Link>
                    </td>
                    <td className="px-6 py-4 text-gray-400 font-mono text-sm">{company.symbol}</td>
                    <td className="px-6 py-4">
                      {company.sector ? (
                        <span className="px-2 py-1 bg-dark-border/50 rounded text-xs text-gray-300">
                          {company.sector}
                        </span>
                      ) : (
                        <span className="text-gray-600">—</span>
                      )}
                    </td>
                    <td className="px-6 py-4 text-right text-gray-300">
                      {company.market_cap
                        ? new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(company.market_cap)
                        : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
