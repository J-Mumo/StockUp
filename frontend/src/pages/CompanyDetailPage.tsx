import { useEffect, useState, useMemo } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Area, ReferenceLine, ComposedChart,
} from 'recharts';
import { ArrowLeft, TrendingUp, Calculator, FileText, RefreshCw, BarChart3 } from 'lucide-react';
import toast from 'react-hot-toast';
import { stocksApi, analysisApi } from '../lib/services';
import type { Company, PriceHistory, FinancialStatement, IntrinsicValue, Recommendation, ValuationTrendPoint } from '../types';
import { PageLoader } from '../components/ui/LoadingSpinner';

type TimePeriod = '1M' | '3M' | '6M' | '1Y' | 'ALL';

const PERIOD_DAYS: Record<TimePeriod, number> = {
  '1M': 30,
  '3M': 90,
  '6M': 180,
  '1Y': 365,
  'ALL': 9999,
};

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
  const [pricePeriod, setPricePeriod] = useState<TimePeriod>('3M');
  const [trendPeriod, setTrendPeriod] = useState<TimePeriod>('1Y');

  useEffect(() => {
    if (!companyId) return;
    setLoading(true);
    Promise.all([
      stocksApi.getCompany(companyId),
      stocksApi.getPrices(companyId),
      stocksApi.getFinancials(companyId),
      analysisApi.getLatestValuation(companyId).catch(() => null),
      analysisApi.getRecommendation(companyId).catch(() => null),
      stocksApi.getValuationTrend(companyId, 730).catch(() => null),
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

  // Sort prices ascending (backend returns newest-first)
  const sortedPrices = useMemo(
    () => [...prices].sort((a, b) => a.price_date.localeCompare(b.price_date)),
    [prices]
  );

  // Price chart data filtered by period
  const priceChartData = useMemo(() => {
    const days = PERIOD_DAYS[pricePeriod];
    const sliced = days >= sortedPrices.length ? sortedPrices : sortedPrices.slice(-days);
    return sliced.map((p) => ({
      date: p.price_date,
      price: p.close_price,
    }));
  }, [sortedPrices, pricePeriod]);

  // Valuation trend data filtered by period
  const trendChartData = useMemo(() => {
    if (trendData.length === 0) return [];
    const days = PERIOD_DAYS[trendPeriod];
    const sliced = days >= trendData.length ? trendData : trendData.slice(-days);

    // Cap IV at 3x max market price
    const marketPrices = sliced.map(d => d.market_price).filter((v): v is number => v != null);
    const maxMarket = Math.max(...marketPrices, 1);
    const ivCap = maxMarket * 3;

    return sliced.map(d => ({
      ...d,
      intrinsic_value: d.intrinsic_value != null && d.intrinsic_value > ivCap ? ivCap : d.intrinsic_value,
    }));
  }, [trendData, trendPeriod]);

  if (loading) return <PageLoader />;
  if (!company) return <p className="text-red-400">Company not found</p>;

  // Current price for badge display
  const currentPrice = sortedPrices.length > 0 ? sortedPrices[sortedPrices.length - 1].close_price : null;
  const prevPrice = sortedPrices.length > 1 ? sortedPrices[sortedPrices.length - 2].close_price : null;
  const priceChange = currentPrice && prevPrice ? currentPrice - prevPrice : null;
  const priceChangePct = priceChange && prevPrice ? (priceChange / prevPrice) * 100 : null;
  const isPositive = (priceChange ?? 0) >= 0;

  const recColors: Record<string, string> = {
    'Strong Buy': 'bg-green-600',
    'Buy': 'bg-green-500',
    'Accumulate': 'bg-emerald-500',
    'Hold': 'bg-yellow-500',
    'Hold/Trim': 'bg-orange-500',
    'Sell': 'bg-red-500',
    'Strong Sell': 'bg-red-600',
  };

  // TradingView-style chart colors
  const tvBlue = '#2962FF';
  const tvGreen = '#26a69a';
  const tvRed = '#ef5350';
  const lineColor = isPositive ? tvGreen : tvRed;

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

      {/* Price Chart — TradingView Style */}
      <div className="bg-[#131722] border border-[#2a2e39] rounded-xl p-5 mb-6">
        {/* Chart Header */}
        <div className="flex items-center justify-between mb-1">
          <div className="flex items-center gap-3">
            <h2 className="text-sm font-medium text-gray-400">{company.ticker_symbol}</h2>
            {currentPrice != null && (
              <div className="flex items-baseline gap-2">
                <span className="text-2xl font-semibold text-white">
                  {currentPrice.toFixed(2)}
                </span>
                <span className="text-xs text-gray-500">KES</span>
                {priceChange != null && (
                  <span className={`text-sm font-medium ${isPositive ? 'text-[#26a69a]' : 'text-[#ef5350]'}`}>
                    {isPositive ? '+' : ''}{priceChange.toFixed(2)} ({priceChangePct?.toFixed(2)}%)
                  </span>
                )}
              </div>
            )}
          </div>
          {/* Period Tabs */}
          <div className="flex gap-1">
            {(['1M', '3M', '6M', '1Y', 'ALL'] as TimePeriod[]).map((p) => (
              <button
                key={p}
                onClick={() => setPricePeriod(p)}
                className={`px-2.5 py-1 text-xs font-medium rounded transition-colors ${
                  pricePeriod === p
                    ? 'bg-[#2962FF] text-white'
                    : 'text-gray-500 hover:text-gray-300 hover:bg-[#1e222d]'
                }`}
              >
                {p}
              </button>
            ))}
          </div>
        </div>

        {priceChartData.length > 0 ? (
          <ResponsiveContainer width="100%" height={340}>
            <LineChart data={priceChartData} margin={{ top: 10, right: 60, bottom: 0, left: 0 }}>
              <CartesianGrid
                horizontal={true}
                vertical={false}
                stroke="#1e222d"
                strokeWidth={1}
              />
              <XAxis
                dataKey="date"
                stroke="#363a45"
                fontSize={10}
                tickLine={false}
                axisLine={false}
                tickFormatter={(d: string) => {
                  if (pricePeriod === '1M') return d.slice(8); // day only
                  if (pricePeriod === '3M') return d.slice(5); // MM-DD
                  return d.slice(0, 7); // YYYY-MM
                }}
                minTickGap={40}
              />
              <YAxis
                orientation="right"
                stroke="#363a45"
                fontSize={10}
                tickLine={false}
                axisLine={false}
                domain={['auto', 'auto']}
                tickFormatter={(v: number) => v.toFixed(1)}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#1e222d',
                  border: '1px solid #363a45',
                  borderRadius: '4px',
                  padding: '8px 12px',
                }}
                labelStyle={{ color: '#787b86', fontSize: 11 }}
                itemStyle={{ color: '#d1d4dc', fontSize: 12 }}
                formatter={(value: number) => [`KES ${value.toFixed(2)}`, 'Price']}
              />
              {/* Current price reference line */}
              {currentPrice != null && (
                <ReferenceLine
                  y={currentPrice}
                  stroke={lineColor}
                  strokeDasharray="2 2"
                  strokeWidth={0.5}
                />
              )}
              <Line
                type="monotone"
                dataKey="price"
                stroke={lineColor}
                strokeWidth={1.5}
                dot={false}
                activeDot={{ r: 3, fill: lineColor, strokeWidth: 0 }}
              />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <p className="text-gray-500 text-center py-16 text-sm">No price data available</p>
        )}
      </div>

      {/* Valuation Trend Chart — TradingView Style */}
      {trendChartData.length > 0 && (() => {
        const marketPrices = trendChartData.map(d => d.market_price).filter((v): v is number => v != null);
        const ivValues = trendChartData.map(d => d.intrinsic_value).filter((v): v is number => v != null);
        const allValues = [...marketPrices, ...ivValues];
        const maxY = Math.max(...allValues) * 1.05;
        const minY = Math.max(0, Math.min(...allValues) * 0.95);

        return (
          <div className="bg-[#131722] border border-[#2a2e39] rounded-xl p-5 mb-6">
            {/* Chart Header */}
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-3">
                <BarChart3 size={16} className="text-[#26a69a]" />
                <h2 className="text-sm font-medium text-gray-400">Valuation vs Price</h2>
                {valuation?.weighted_intrinsic_value != null && (
                  <span className="text-xs px-2 py-0.5 rounded bg-[#26a69a]/10 text-[#26a69a] font-medium">
                    IV: KES {valuation.weighted_intrinsic_value.toFixed(2)}
                  </span>
                )}
              </div>
              {/* Period Tabs */}
              <div className="flex gap-1">
                {(['3M', '6M', '1Y', 'ALL'] as TimePeriod[]).map((p) => (
                  <button
                    key={p}
                    onClick={() => setTrendPeriod(p)}
                    className={`px-2.5 py-1 text-xs font-medium rounded transition-colors ${
                      trendPeriod === p
                        ? 'bg-[#2962FF] text-white'
                        : 'text-gray-500 hover:text-gray-300 hover:bg-[#1e222d]'
                    }`}
                  >
                    {p}
                  </button>
                ))}
              </div>
            </div>

            <ResponsiveContainer width="100%" height={300}>
              <ComposedChart data={trendChartData} margin={{ top: 10, right: 60, bottom: 0, left: 0 }}>
                <defs>
                  <linearGradient id="buyZoneGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#26a69a" stopOpacity={0.08} />
                    <stop offset="100%" stopColor="#26a69a" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid
                  horizontal={true}
                  vertical={false}
                  stroke="#1e222d"
                  strokeWidth={1}
                />
                <XAxis
                  dataKey="date"
                  stroke="#363a45"
                  fontSize={10}
                  tickLine={false}
                  axisLine={false}
                  tickFormatter={(d: string) => d.slice(5)}
                  minTickGap={40}
                />
                <YAxis
                  orientation="right"
                  stroke="#363a45"
                  fontSize={10}
                  tickLine={false}
                  axisLine={false}
                  domain={[minY, maxY]}
                  tickFormatter={(v: number) => v.toFixed(1)}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#1e222d',
                    border: '1px solid #363a45',
                    borderRadius: '4px',
                    padding: '8px 12px',
                  }}
                  labelStyle={{ color: '#787b86', fontSize: 11 }}
                  formatter={(value: number, name: string) => {
                    const label = name === 'market_price' ? 'Market Price' : 'Intrinsic Value';
                    return [value != null ? `KES ${value.toFixed(2)}` : '—', label];
                  }}
                />
                {/* IV area fill (subtle buy zone) */}
                <Area
                  type="monotone"
                  dataKey="intrinsic_value"
                  stroke="none"
                  fill="url(#buyZoneGradient)"
                  dot={false}
                  connectNulls
                />
                {/* IV line (dashed) */}
                <Line
                  type="monotone"
                  dataKey="intrinsic_value"
                  stroke="#26a69a"
                  strokeWidth={1.5}
                  strokeDasharray="4 3"
                  dot={false}
                  name="intrinsic_value"
                  connectNulls
                />
                {/* Market price line (solid) */}
                <Line
                  type="monotone"
                  dataKey="market_price"
                  stroke="#f59e0b"
                  strokeWidth={1.5}
                  dot={false}
                  name="market_price"
                  connectNulls
                />
              </ComposedChart>
            </ResponsiveContainer>

            {/* Legend */}
            <div className="flex items-center gap-5 mt-3 text-[10px] text-gray-500">
              <span className="flex items-center gap-1.5">
                <span className="w-3 h-[2px] bg-amber-500 inline-block rounded" /> Market Price
              </span>
              <span className="flex items-center gap-1.5">
                <span className="w-3 h-[2px] inline-block rounded" style={{ background: 'repeating-linear-gradient(90deg, #26a69a 0, #26a69a 3px, transparent 3px, transparent 5px)' }} /> Intrinsic Value
              </span>
              <span className="flex items-center gap-1.5">
                <span className="w-3 h-2.5 bg-[#26a69a]/10 inline-block rounded-sm border border-[#26a69a]/30" /> Buy Zone
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
