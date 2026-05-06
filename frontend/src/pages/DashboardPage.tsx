import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Briefcase, Bell, Eye, TrendingDown, BarChart3, Building2 } from 'lucide-react';
import { dashboardApi } from '../lib/services';
import type { DashboardSummary } from '../types';
import { SkeletonCard } from '../components/ui/LoadingSpinner';

export default function DashboardPage() {
  const [data, setData] = useState<DashboardSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    dashboardApi.getSummary()
      .then((res) => setData(res.data))
      .catch((err) => setError(err.response?.data?.detail || 'Failed to load dashboard'))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div>
        <h1 className="text-2xl font-bold text-white mb-6">Dashboard</h1>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          {Array.from({ length: 4 }).map((_, i) => <SkeletonCard key={i} />)}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-center py-12">
        <p className="text-red-400 mb-4">{error}</p>
        <button
          onClick={() => window.location.reload()}
          className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700"
        >
          Retry
        </button>
      </div>
    );
  }

  if (!data) return null;

  const formatCurrency = (val: number | null | undefined) =>
    val != null
      ? new Intl.NumberFormat('en-US', { style: 'currency', currency: 'KES', maximumFractionDigits: 0 }).format(val)
      : '—';

  const formatPct = (val: number | null | undefined) =>
    val != null ? `${val >= 0 ? '+' : ''}${val.toFixed(2)}%` : '—';

  return (
    <div>
      <h1 className="text-2xl font-bold text-white mb-6">Dashboard</h1>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <Link to="/portfolio" className="bg-dark-surface border border-dark-border rounded-xl p-6 hover:border-primary-500/50 transition-colors">
          <div className="flex items-center gap-3 mb-3">
            <div className="p-2 bg-primary-600/20 rounded-lg">
              <Briefcase className="text-primary-400" size={20} />
            </div>
            <span className="text-sm text-gray-400">Portfolio Value</span>
          </div>
          <p className="text-2xl font-bold text-white">{formatCurrency(data.portfolio.total_current_value)}</p>
          <p className={`text-sm mt-1 ${(data.portfolio.total_pnl || 0) >= 0 ? 'text-gain' : 'text-loss'}`}>
            {formatPct(data.portfolio.pnl_pct)}
          </p>
        </Link>

        <Link to="/alerts" className="bg-dark-surface border border-dark-border rounded-xl p-6 hover:border-primary-500/50 transition-colors">
          <div className="flex items-center gap-3 mb-3">
            <div className="p-2 bg-yellow-600/20 rounded-lg">
              <Bell className="text-yellow-400" size={20} />
            </div>
            <span className="text-sm text-gray-400">Unread Alerts</span>
          </div>
          <p className="text-2xl font-bold text-white">{data.alerts.unread_triggered}</p>
          <p className="text-sm text-gray-500 mt-1">{data.alerts.total_active} active</p>
        </Link>

        <Link to="/watchlists" className="bg-dark-surface border border-dark-border rounded-xl p-6 hover:border-primary-500/50 transition-colors">
          <div className="flex items-center gap-3 mb-3">
            <div className="p-2 bg-green-600/20 rounded-lg">
              <Eye className="text-green-400" size={20} />
            </div>
            <span className="text-sm text-gray-400">Watchlists</span>
          </div>
          <p className="text-2xl font-bold text-white">{data.watchlists.total_watchlists}</p>
          <p className="text-sm text-gray-500 mt-1">{data.watchlists.total_items} items tracked</p>
        </Link>

        <Link to="/companies" className="bg-dark-surface border border-dark-border rounded-xl p-6 hover:border-primary-500/50 transition-colors">
          <div className="flex items-center gap-3 mb-3">
            <div className="p-2 bg-purple-600/20 rounded-lg">
              <BarChart3 className="text-purple-400" size={20} />
            </div>
            <span className="text-sm text-gray-400">Market Stats</span>
          </div>
          <p className="text-2xl font-bold text-white">{data.market_stats.total_companies}</p>
          <p className="text-sm text-gray-500 mt-1">
            {data.market_stats.companies_with_valuations} valued
          </p>
        </Link>
      </div>

      {/* Top Undervalued Stocks */}
      <div className="bg-dark-surface border border-dark-border rounded-xl p-6 mb-6">
        <div className="flex items-center gap-2 mb-4">
          <TrendingDown className="text-gain" size={20} />
          <h2 className="text-lg font-semibold text-white">Top Undervalued Stocks</h2>
        </div>

        {data.top_undervalued.length === 0 ? (
          <p className="text-gray-400 text-center py-4">No valuation data available yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="text-left text-sm text-gray-400 border-b border-dark-border">
                  <th className="pb-3 font-medium">Company</th>
                  <th className="pb-3 font-medium">Symbol</th>
                  <th className="pb-3 font-medium text-right">Market Price</th>
                  <th className="pb-3 font-medium text-right">Intrinsic Value</th>
                  <th className="pb-3 font-medium text-right">Margin of Safety</th>
                  <th className="pb-3 font-medium text-right">Recommendation</th>
                </tr>
              </thead>
              <tbody>
                {data.top_undervalued.map((stock) => (
                  <tr key={stock.company_id} className="border-b border-dark-border/50 hover:bg-dark-border/20">
                    <td className="py-3">
                      <Link to={`/companies/${stock.company_id}`} className="text-white hover:text-primary-400">
                        {stock.company_name}
                      </Link>
                    </td>
                    <td className="py-3 text-gray-400">{stock.ticker}</td>
                    <td className="py-3 text-right text-gray-300">
                      {stock.market_price ? formatCurrency(stock.market_price) : '—'}
                    </td>
                    <td className="py-3 text-right text-gray-300">
                      {stock.intrinsic_value ? formatCurrency(stock.intrinsic_value) : '—'}
                    </td>
                    <td className="py-3 text-right">
                      <span className="text-gain font-medium">
                        {stock.margin_of_safety_pct.toFixed(1)}%
                      </span>
                    </td>
                    <td className="py-3 text-right">
                      <span className="px-2 py-1 text-xs rounded-full bg-gain/20 text-gain">
                        {stock.recommendation || '—'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Quick Stats */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-dark-surface border border-dark-border rounded-xl p-6">
          <div className="flex items-center gap-2 mb-2">
            <Building2 className="text-gray-400" size={18} />
            <span className="text-sm text-gray-400">Price Records</span>
          </div>
          <p className="text-xl font-bold text-white">{data.market_stats.total_price_records.toLocaleString()}</p>
        </div>
        <div className="bg-dark-surface border border-dark-border rounded-xl p-6">
          <div className="flex items-center gap-2 mb-2">
            <Building2 className="text-gray-400" size={18} />
            <span className="text-sm text-gray-400">Latest Data</span>
          </div>
          <p className="text-xl font-bold text-white">{data.market_stats.latest_price_date || '—'}</p>
        </div>
        <div className="bg-dark-surface border border-dark-border rounded-xl p-6">
          <div className="flex items-center gap-2 mb-2">
            <Briefcase className="text-gray-400" size={18} />
            <span className="text-sm text-gray-400">Total Portfolios</span>
          </div>
          <p className="text-xl font-bold text-white">{data.portfolio.total_portfolios}</p>
        </div>
      </div>
    </div>
  );
}
