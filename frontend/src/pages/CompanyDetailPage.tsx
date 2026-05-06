import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, AreaChart, Area, ReferenceLine, ComposedChart,
} from 'recharts';
import { ArrowLeft, TrendingUp, Calculator, FileText, RefreshCw, BarChart3 } from 'lucide-react';
import toast from 'react-hot-toast';
import { stocksApi, analysisApi } from '../lib/services';
import type { Company, PriceHistory, FinancialStatement, IntrinsicValue, Recommendation, ValuationTrendPoint } from '../types';
import { PageLoader } from '../components/ui/LoadingSpinner';

export default function CompanyDetailPage() {
  const { id } = useParams<{ id: string }>();
  const companyId = Number(id);

  const [company, setCompany] = useState<Company | null>(null);
  const [prices, setPrices] = useState<PriceHistory[]>([]);
  const [financials, setFinancials] = useState<FinancialStatement[]>([]);
  const [valuation, setValuation] = useState<IntrinsicValue | null>(null);
  const [recommendation, setRecommendation] = useState<Recommendation | null>(null);
  const [trendData, setTrendData] = useState<ValuationTrendPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [computing, setComputing] = useState(false);

  useEffect(() => {
    if (!companyId) return;
    setLoading(true);
    Promise.all([
      stocksApi.getCompany(companyId),
      stocksApi.getPrices(companyId),
      stocksApi.getFinancials(companyId),
      analysisApi.getLatestValuation(companyId).catch(() => null),
      analysisApi.getRecommendation(companyId).catch(() => null),
      stocksApi.getValuationTrend(companyId, 365).catch(() => null),
    ])
      .then(([companyRes, pricesRes, financialsRes, valuationRes, recRes, trendRes]) => {
        setCompany(companyRes.data);
        setPrices(pricesRes.data);
        setFinancials(financialsRes.data);
        if (valuationRes) setValuation(valuationRes.data);
        if (recRes) setRecommendation(recRes.data);
        if (trendRes) setTrendData(trendRes.data);
      })
      .catch(() => toast.error('Failed to load company data'))
      .finally(() => setLoading(false));
  }, [companyId]);

  const handleCompute = async () => {
    setComputing(true);
    try {
      const res = await analysisApi.computeValuation(companyId);
      setValuation(res.data);
      const recRes = await analysisApi.getRecommendation(companyId);
      setRecommendation(recRes.data);
      toast.success('Valuation computed!');
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        || 'Failed to compute valuation';
      toast.error(detail);
    } finally {
      setComputing(false);
    }
  };

  if (loading) return <PageLoader />;
  if (!company) return <p className="text-red-400">Company not found</p>;

  // Backend returns prices newest-first; sort ascending for chart display
  const sortedPrices = [...prices].sort((a, b) => a.price_date.localeCompare(b.price_date));
  const chartData = sortedPrices.slice(-90).map((p) => ({
    date: p.price_date,
    price: p.close_price,
    volume: p.volume,
  }));

  const recColors: Record<string, string> = {
    'Strong Buy': 'bg-green-600',
    'Buy': 'bg-green-500',
    'Accumulate': 'bg-emerald-500',
    'Hold': 'bg-yellow-500',
    'Hold/Trim': 'bg-orange-500',
    'Sell': 'bg-red-500',
    'Strong Sell': 'bg-red-600',
  };

  return (
    <div>
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <Link to="/companies" className="p-2 hover:bg-dark-surface rounded-lg transition-colors">
          <ArrowLeft className="text-gray-400" size={20} />
        </Link>
        <div className="flex-1">
          <h1 className="text-2xl font-bold text-white">{company.name}</h1>
          <p className="text-gray-400">
            {company.ticker_symbol} {company.sector && `• ${company.sector}`}
          </p>
        </div>
        {recommendation && recommendation.action && (
          <span className={`px-3 py-1.5 rounded-lg text-white text-sm font-medium ${recColors[recommendation.action] || 'bg-gray-500'}`}>
            {recommendation.action}
          </span>
        )}
      </div>

      {/* Price Chart */}
      <div className="bg-dark-surface border border-dark-border rounded-xl p-6 mb-6">
        <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
          <TrendingUp size={18} className="text-primary-400" />
          Price History (Last 90 days)
        </h2>
        {chartData.length > 0 ? (
          <ResponsiveContainer width="100%" height={300}>
            <AreaChart data={chartData}>
              <defs>
                <linearGradient id="priceGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="date" stroke="#64748b" fontSize={12} />
              <YAxis stroke="#64748b" fontSize={12} />
              <Tooltip
                contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }}
                labelStyle={{ color: '#94a3b8' }}
                itemStyle={{ color: '#fff' }}
              />
              <Area type="monotone" dataKey="price" stroke="#3b82f6" fill="url(#priceGradient)" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        ) : (
          <p className="text-gray-400 text-center py-8">No price data available</p>
        )}
      </div>

      {/* Valuation Trend Chart */}
      {trendData.length > 0 && (() => {
        // Compute sensible Y-axis domain: cap IV at 3x max market price to avoid extreme outliers
        const marketPrices = trendData.map(d => d.market_price).filter((v): v is number => v != null);
        const ivValues = trendData.map(d => d.intrinsic_value).filter((v): v is number => v != null);
        const maxMarket = Math.max(...marketPrices, 1);
        const minMarket = Math.min(...marketPrices, 0);
        const ivCap = maxMarket * 3; // Cap IV display at 3x market price
        const cappedIv = ivValues.filter(v => v <= ivCap);
        const maxY = Math.max(maxMarket, ...cappedIv) * 1.1;
        const minY = Math.max(0, minMarket * 0.9);

        // Clamp trend data for chart (don't mutate original)
        const chartTrendData = trendData.map(d => ({
          ...d,
          intrinsic_value: d.intrinsic_value != null && d.intrinsic_value > ivCap ? ivCap : d.intrinsic_value,
        }));

        return (
          <div className="bg-dark-surface border border-dark-border rounded-xl p-6 mb-6">
            <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
              <BarChart3 size={18} className="text-emerald-400" />
              Valuation vs Market Price
            </h2>
            <ResponsiveContainer width="100%" height={320}>
              <ComposedChart data={chartTrendData}>
                <defs>
                  <linearGradient id="buyZoneGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#10b981" stopOpacity={0.15} />
                    <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis
                  dataKey="date"
                  stroke="#64748b"
                  fontSize={11}
                  tickFormatter={(d: string) => d.slice(5)}
                />
                <YAxis stroke="#64748b" fontSize={11} domain={[minY, maxY]} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }}
                  labelStyle={{ color: '#94a3b8' }}
                  formatter={(value: number, name: string) => {
                    const label = name === 'market_price' ? 'Market Price' : name === 'intrinsic_value' ? 'Intrinsic Value' : name;
                    return [value != null ? `KES ${value.toFixed(2)}` : '—', label];
                  }}
                />
                <Area
                  type="monotone"
                  dataKey="intrinsic_value"
                  stroke="#10b981"
                  strokeWidth={2}
                  strokeDasharray="6 3"
                  fill="url(#buyZoneGradient)"
                  name="intrinsic_value"
                  dot={false}
                  connectNulls
                />
                <Line
                  type="monotone"
                  dataKey="market_price"
                  stroke="#f59e0b"
                  strokeWidth={2}
                  dot={false}
                  name="market_price"
                  connectNulls
                />
              </ComposedChart>
            </ResponsiveContainer>
            <div className="flex items-center gap-6 mt-3 text-xs text-gray-400">
              <span className="flex items-center gap-1.5">
                <span className="w-4 h-0.5 bg-amber-500 inline-block" /> Market Price
              </span>
              <span className="flex items-center gap-1.5">
                <span className="w-4 h-0.5 bg-emerald-500 inline-block border-dashed" style={{ borderTopWidth: 2, borderColor: '#10b981', background: 'none' }} /> Intrinsic Value
              </span>
              <span className="flex items-center gap-1.5">
                <span className="w-4 h-3 bg-emerald-500/20 inline-block rounded-sm" /> Buy Zone (Price &lt; IV)
              </span>
            </div>
          </div>
        );
      })()}

      {/* Valuation Section */}
      <div className="bg-dark-surface border border-dark-border rounded-xl p-6 mb-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <Calculator size={18} className="text-purple-400" />
            Valuation
          </h2>
          <button
            onClick={handleCompute}
            disabled={computing}
            className="flex items-center gap-2 px-3 py-1.5 bg-primary-600 hover:bg-primary-700 disabled:opacity-50 text-white text-sm rounded-lg transition-colors"
          >
            <RefreshCw size={14} className={computing ? 'animate-spin' : ''} />
            {computing ? 'Computing...' : 'Compute Valuation'}
          </button>
        </div>

        {valuation ? (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="p-4 bg-dark-bg rounded-lg">
              <p className="text-sm text-gray-400 mb-1">Intrinsic Value</p>
              <p className="text-xl font-bold text-white">
                KES {valuation.weighted_intrinsic_value?.toFixed(2) ?? '—'}
              </p>
            </div>
            <div className="p-4 bg-dark-bg rounded-lg">
              <p className="text-sm text-gray-400 mb-1">Margin of Safety</p>
              <p className={`text-xl font-bold ${(valuation.margin_of_safety_pct ?? 0) > 0 ? 'text-gain' : 'text-loss'}`}>
                {valuation.margin_of_safety_pct != null ? (valuation.margin_of_safety_pct * 100).toFixed(1) : '—'}%
              </p>
            </div>
            <div className="p-4 bg-dark-bg rounded-lg">
              <p className="text-sm text-gray-400 mb-1">Market Price</p>
              <p className="text-xl font-bold text-white">
                {valuation.current_market_price ? `KES ${valuation.current_market_price.toFixed(2)}` : '—'}
              </p>
              <p className="text-xs text-gray-500">{valuation.valuation_date}</p>
            </div>
          </div>
        ) : (
          <p className="text-gray-400 text-center py-4">
            No valuation computed yet. Click "Compute Valuation" to generate one.
          </p>
        )}

        {recommendation && recommendation.reason && (
          <div className="mt-4 p-4 bg-dark-bg rounded-lg">
            <p className="text-sm text-gray-400 mb-2">Analysis:</p>
            <p className="text-gray-300 text-sm">{recommendation.reason}</p>
            {recommendation.quality_factors.length > 0 && (
              <div className="mt-3">
                <p className="text-sm text-gray-400 mb-1">
                  Quality Score: {recommendation.quality_score}/{recommendation.quality_max_score}
                </p>
                <ul className="list-disc list-inside text-gray-300 text-sm space-y-1">
                  {recommendation.quality_factors.map((f, i) => (
                    <li key={i} className={f.met ? 'text-gain' : 'text-gray-500'}>
                      {f.name}: {f.description}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Financial Statements */}
      <div className="bg-dark-surface border border-dark-border rounded-xl p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <FileText size={18} className="text-green-400" />
            Financial Statements
          </h2>
          <Link
            to={`/companies/${companyId}/financials/new`}
            className="px-3 py-1.5 bg-green-600 hover:bg-green-700 text-white text-sm rounded-lg transition-colors"
          >
            Add Statement
          </Link>
        </div>

        {financials.length === 0 ? (
          <p className="text-gray-400 text-center py-4">No financial statements recorded.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="text-left text-sm text-gray-400 border-b border-dark-border">
                  <th className="pb-3 font-medium">Year</th>
                  <th className="pb-3 font-medium">Revenue (KES)</th>
                  <th className="pb-3 font-medium">Net Income (KES)</th>
                  <th className="pb-3 font-medium text-right">ROE</th>
                </tr>
              </thead>
              <tbody>
                {financials.map((fs) => (
                  <tr key={fs.id} className="border-b border-dark-border/50">
                    <td className="py-3">
                      <span className="px-2 py-1 bg-dark-border/50 rounded text-xs text-gray-300">
                        {fs.fiscal_year} ({fs.period_type})
                      </span>
                    </td>
                    <td className="py-3 text-gray-300">
                      {fs.revenue ? (fs.revenue / 1e9).toFixed(1) + 'B' : '—'}
                    </td>
                    <td className="py-3 text-gray-300">
                      {fs.net_income ? (fs.net_income / 1e9).toFixed(1) + 'B' : '—'}
                    </td>
                    <td className="py-3 text-right">
                      <Link
                        to={`/companies/${companyId}/financials/${fs.id}/edit`}
                        className="text-primary-400 hover:text-primary-300 text-sm"
                      >
                        {fs.return_on_equity != null ? (fs.return_on_equity * 100).toFixed(1) + '%' : '—'}
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
