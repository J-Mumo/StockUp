import { useEffect, useState, useMemo } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Area, ReferenceLine, ComposedChart, BarChart, Bar,
} from 'recharts';
import { ArrowLeft, TrendingUp, Calculator, FileText, RefreshCw, BarChart3, ExternalLink, Edit3, Info, RotateCcw, Briefcase, MessageSquare, Trash2, Save, X, Plus } from 'lucide-react';
import toast from 'react-hot-toast';
import { stocksApi, analysisApi, portfolioApi, notesApi } from '../lib/services';
import type { CompanyDetail, PriceHistory, FinancialStatement, IntrinsicValue, Recommendation, ValuationTrendPoint, Holding, Portfolio, CompanyNote } from '../types';
import { PageLoader } from '../components/ui/LoadingSpinner';

type TimePeriod = '1D' | '5D' | '1M' | '6M' | 'YTD' | '1Y' | '5Y' | 'ALL';

const PERIOD_DAYS: Record<TimePeriod, number> = {
  '1D': 1,
  '5D': 5,
  '1M': 30,
  '6M': 180,
  'YTD': -1, // special: computed from Jan 1
  '1Y': 365,
  '5Y': 1825,
  'ALL': 9999,
};

const PERIOD_LABELS: Record<TimePeriod, string> = {
  '1D': '1 day',
  '5D': '5 days',
  '1M': '1 month',
  '6M': '6 months',
  'YTD': 'Year to date',
  '1Y': '1 year',
  '5Y': '5 years',
  'ALL': 'All time',
};

// Format large numbers
function fmtNum(value: number | null, decimals = 1): string {
  if (value == null) return '—';
  const abs = Math.abs(value);
  if (abs >= 1e12) return (value / 1e12).toFixed(decimals) + 'T';
  if (abs >= 1e9) return (value / 1e9).toFixed(decimals) + 'B';
  if (abs >= 1e6) return (value / 1e6).toFixed(decimals) + 'M';
  if (abs >= 1e3) return (value / 1e3).toFixed(decimals) + 'K';
  return value.toFixed(decimals);
}

function fmtPct(value: number | null): string {
  if (value == null) return '—';
  return (value * 100).toFixed(1) + '%';
}

function fmtKES(value: number | null): string {
  if (value == null) return '—';
  return 'KES ' + value.toFixed(2);
}

function getDataSource(notes: string | null): { label: string; color: string } {
  if (!notes) return { label: 'Unknown', color: 'bg-gray-600' };
  if (notes.includes('[PDF annual report]')) return { label: 'PDF', color: 'bg-blue-600' };
  if (notes.includes('[AI enriched')) return { label: 'AI', color: 'bg-purple-600' };
  if (notes.includes('Manual')) return { label: 'Manual', color: 'bg-green-600' };
  if (notes.includes('kenyanstocks')) return { label: 'Scraped', color: 'bg-orange-600' };
  return { label: 'Auto', color: 'bg-gray-600' };
}

export default function CompanyDetailPage() {
  const { id } = useParams<{ id: string }>();
  const companyId = Number(id);

  const [company, setCompany] = useState<CompanyDetail | null>(null);
  const [prices, setPrices] = useState<PriceHistory[]>([]);
  const [financials, setFinancials] = useState<FinancialStatement[]>([]);
  const [valuation, setValuation] = useState<IntrinsicValue | null>(null);
  const [recommendation, setRecommendation] = useState<Recommendation | null>(null);
  const [trendData, setTrendData] = useState<ValuationTrendPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [computing, setComputing] = useState(false);
  const [pricePeriod, setPricePeriod] = useState<TimePeriod>('1Y');
  const [trendPeriod, setTrendPeriod] = useState<TimePeriod>('1Y');
  const [showAssumptions, setShowAssumptions] = useState(false);

  // Custom assumptions for stress-testing
  const [customDiscountRate, setCustomDiscountRate] = useState<string>('');
  const [customTerminalGrowth, setCustomTerminalGrowth] = useState<string>('');
  const [customProjectionYears, setCustomProjectionYears] = useState<string>('');
  const [customDcfWeight, setCustomDcfWeight] = useState<string>('');
  const [customEpvWeight, setCustomEpvWeight] = useState<string>('');
  const [customBvWeight, setCustomBvWeight] = useState<string>('');
  const [isCustom, setIsCustom] = useState(false);
  const [position, setPosition] = useState<Holding | null>(null);
  const [notes, setNotes] = useState<CompanyNote[]>([]);
  const [newNoteText, setNewNoteText] = useState('');
  const [newNoteTag, setNewNoteTag] = useState('');
  const [editingNoteId, setEditingNoteId] = useState<number | null>(null);
  const [editNoteText, setEditNoteText] = useState('');
  const [editNoteTag, setEditNoteTag] = useState('');
  const [showNotes, setShowNotes] = useState(true);

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

  // Fetch user's position in this company across all portfolios
  useEffect(() => {
    if (!companyId) return;
    portfolioApi.list()
      .then(async (res) => {
        const portfolios: Portfolio[] = res.data;
        for (const p of portfolios) {
          try {
            const holdingsRes = await portfolioApi.getHoldings(p.id);
            const match = holdingsRes.data.holdings.find((h: Holding) => h.company_id === companyId);
            if (match && match.total_shares > 0) {
              setPosition(match);
              return;
            }
          } catch { /* ignore */ }
        }
        setPosition(null);
      })
      .catch(() => setPosition(null));
  }, [companyId]);

  // Fetch notes
  useEffect(() => {
    if (!companyId) return;
    notesApi.list(companyId).then(res => setNotes(res.data)).catch(() => {});
  }, [companyId]);

  const loadNotes = () => {
    notesApi.list(companyId).then(res => setNotes(res.data)).catch(() => {});
  };

  const handleCreateNote = async () => {
    if (!newNoteText.trim()) return;
    try {
      await notesApi.create(companyId, { note_text: newNoteText.trim(), tag: newNoteTag || undefined });
      setNewNoteText('');
      setNewNoteTag('');
      loadNotes();
      toast.success('Note saved');
    } catch { toast.error('Failed to save note'); }
  };

  const handleUpdateNote = async (noteId: number) => {
    try {
      await notesApi.update(companyId, noteId, { note_text: editNoteText, tag: editNoteTag || undefined });
      setEditingNoteId(null);
      loadNotes();
      toast.success('Note updated');
    } catch { toast.error('Failed to update note'); }
  };

  const handleDeleteNote = async (noteId: number) => {
    try {
      await notesApi.delete(companyId, noteId);
      loadNotes();
      toast.success('Note deleted');
    } catch { toast.error('Failed to delete note'); }
  };

  const handleCompute = async (useCustom = false) => {
    setComputing(true);
    try {
      const customAssumptions = useCustom ? {
        ...(customDiscountRate ? { discount_rate: parseFloat(customDiscountRate) / 100 } : {}),
        ...(customTerminalGrowth ? { terminal_growth_rate: parseFloat(customTerminalGrowth) / 100 } : {}),
        ...(customProjectionYears ? { projection_years: parseInt(customProjectionYears) } : {}),
        ...(customDcfWeight ? { dcf_weight: parseFloat(customDcfWeight) / 100 } : {}),
        ...(customEpvWeight ? { epv_weight: parseFloat(customEpvWeight) / 100 } : {}),
        ...(customBvWeight ? { bv_weight: parseFloat(customBvWeight) / 100 } : {}),
      } : undefined;
      const res = await analysisApi.computeValuation(companyId, customAssumptions);
      setValuation(res.data);
      if (useCustom) setIsCustom(true);
      const recRes = await analysisApi.getRecommendation(companyId);
      setRecommendation(recRes.data);
      toast.success(useCustom ? 'Custom valuation computed!' : 'Valuation computed!');
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        || 'Failed to compute valuation';
      toast.error(detail);
    } finally {
      setComputing(false);
    }
  };

  const resetAssumptions = () => {
    setCustomDiscountRate('');
    setCustomTerminalGrowth('');
    setCustomProjectionYears('');
    setCustomDcfWeight('');
    setCustomEpvWeight('');
    setCustomBvWeight('');
    setIsCustom(false);
  };

  // Populate custom fields from current assumptions when panel opens
  const populateFromCurrent = () => {
    if (assumptions) {
      setCustomDiscountRate((assumptions.discount_rate * 100).toFixed(0));
      setCustomTerminalGrowth((assumptions.terminal_growth_rate * 100).toFixed(0));
      setCustomProjectionYears(String(assumptions.projection_years));
      if (calcDetails) {
        const wa = (calcDetails as { weights_applied?: Record<string, number> }).weights_applied;
        if (wa) {
          setCustomDcfWeight(((wa.dcf ?? 0) * 100).toFixed(0));
          setCustomEpvWeight(((wa.epv ?? 0) * 100).toFixed(0));
          setCustomBvWeight(((wa.bv ?? 0) * 100).toFixed(0));
        }
      }
    }
  };

  // Sort prices ascending
  const sortedPrices = useMemo(
    () => [...prices].sort((a, b) => a.price_date.localeCompare(b.price_date)),
    [prices]
  );

  // Helper: slice prices by period
  const slicePricesByPeriod = (period: TimePeriod) => {
    if (sortedPrices.length === 0) return [];
    if (period === 'YTD') {
      const yearStart = new Date().getFullYear() + '-01-01';
      return sortedPrices.filter(p => p.price_date >= yearStart);
    }
    const days = PERIOD_DAYS[period];
    return days >= sortedPrices.length ? sortedPrices : sortedPrices.slice(-days);
  };

  // Price chart data filtered by period
  const priceChartData = useMemo(() => {
    const sliced = slicePricesByPeriod(pricePeriod);
    return sliced.map((p) => ({
      date: p.price_date,
      price: p.close_price,
    }));
  }, [sortedPrices, pricePeriod]);

  // Performance metrics for each period
  const performanceMetrics = useMemo(() => {
    if (sortedPrices.length === 0) return [];
    const latestPrice = sortedPrices[sortedPrices.length - 1].close_price;
    const periods: TimePeriod[] = ['1D', '5D', '1M', '6M', 'YTD', '1Y', '5Y', 'ALL'];
    return periods.map(period => {
      const sliced = slicePricesByPeriod(period);
      if (sliced.length === 0) return { period, label: PERIOD_LABELS[period], pct: null };
      const startPrice = sliced[0].close_price;
      const pct = startPrice > 0 ? ((latestPrice - startPrice) / startPrice) * 100 : null;
      return { period, label: PERIOD_LABELS[period], pct };
    });
  }, [sortedPrices]);

  // Valuation trend data filtered by period
  const trendChartData = useMemo(() => {
    if (trendData.length === 0) return [];
    let sliced: typeof trendData;
    if (trendPeriod === 'YTD') {
      const yearStart = new Date().getFullYear() + '-01-01';
      sliced = trendData.filter(d => d.date >= yearStart);
    } else {
      const days = PERIOD_DAYS[trendPeriod];
      sliced = days >= trendData.length ? trendData : trendData.slice(-days);
    }
    const marketPrices = sliced.map(d => d.market_price).filter((v): v is number => v != null);
    const maxMarket = Math.max(...marketPrices, 1);
    const ivCap = maxMarket * 3;
    return sliced.map(d => ({
      ...d,
      intrinsic_value: d.intrinsic_value != null && d.intrinsic_value > ivCap ? ivCap : d.intrinsic_value,
    }));
  }, [trendData, trendPeriod]);

  // Financial trend chart data
  const financialChartData = useMemo(() => {
    return [...financials]
      .sort((a, b) => a.fiscal_year - b.fiscal_year)
      .map(fs => ({
        year: fs.fiscal_year.toString(),
        revenue: fs.revenue ? fs.revenue / 1e9 : null,
        net_income: fs.net_income ? fs.net_income / 1e9 : null,
        fcf: fs.free_cash_flow ? fs.free_cash_flow / 1e9 : null,
      }));
  }, [financials]);

  // Key ratios from latest financial
  const latestFinancial = useMemo(() => {
    if (financials.length === 0) return null;
    return [...financials].sort((a, b) => b.fiscal_year - a.fiscal_year)[0];
  }, [financials]);

  if (loading) return <PageLoader />;
  if (!company) return <p className="text-red-400">Company not found</p>;

  // Current price
  const currentPrice = sortedPrices.length > 0 ? sortedPrices[sortedPrices.length - 1].close_price : null;
  const prevPrice = sortedPrices.length > 1 ? sortedPrices[sortedPrices.length - 2].close_price : null;
  const priceChange = currentPrice && prevPrice ? currentPrice - prevPrice : null;
  const priceChangePct = priceChange && prevPrice ? (priceChange / prevPrice) * 100 : null;
  const isPositive = (priceChange ?? 0) >= 0;

  // Key ratios
  const pe = currentPrice && latestFinancial?.earnings_per_share ? currentPrice / latestFinancial.earnings_per_share : null;
  const pb = currentPrice && latestFinancial?.book_value_per_share && latestFinancial.book_value_per_share > 0
    ? currentPrice / latestFinancial.book_value_per_share : null;
  const divYield = currentPrice && latestFinancial?.dividends_per_share
    ? latestFinancial.dividends_per_share / currentPrice : null;

  const recColors: Record<string, string> = {
    'Strong Buy': 'bg-green-600',
    'Buy': 'bg-green-500',
    'Accumulate': 'bg-emerald-500',
    'Hold': 'bg-yellow-500',
    'Hold/Trim': 'bg-orange-500',
    'Sell': 'bg-red-500',
    'Strong Sell': 'bg-red-600',
  };

  const tvGreen = '#26a69a';
  const tvRed = '#ef5350';
  const lineColor = isPositive ? tvGreen : tvRed;

  // Assumptions from valuation
  const assumptions = valuation?.assumptions as Record<string, number> | null;
  const calcDetails = valuation?.calculation_details as Record<string, unknown> | null;

  return (
    <div>
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <Link to="/companies" className="p-2 hover:bg-dark-surface rounded-lg transition-colors">
          <ArrowLeft className="text-gray-400" size={20} />
        </Link>
        <div className="flex-1">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-white">{company.name}</h1>
            {company.website && (
              <a href={company.website} target="_blank" rel="noopener noreferrer" className="text-primary-400 hover:text-primary-300">
                <ExternalLink size={16} />
              </a>
            )}
          </div>
          <div className="flex items-center gap-2 text-gray-400 text-sm">
            <span>{company.ticker_symbol}</span>
            {company.sector && <span>• {company.sector}</span>}
            {company.industry && <span>• {company.industry}</span>}
            {company.shares_outstanding && (
              <span>• {fmtNum(company.shares_outstanding, 0)} shares</span>
            )}
          </div>
          {company.description && (
            <p className="text-gray-500 text-sm mt-1 line-clamp-2">{company.description}</p>
          )}
        </div>
        {recommendation && recommendation.action && (
          <span className={`px-3 py-1.5 rounded-lg text-white text-sm font-medium ${recColors[recommendation.action] || 'bg-gray-500'}`}>
            {recommendation.action}
          </span>
        )}
      </div>

      {/* Price Chart */}
      <div className="bg-[#131722] border border-[#2a2e39] rounded-xl p-5 mb-6">
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
        </div>

        {/* Performance indicators */}
        {performanceMetrics.length > 0 && (
          <div className="flex gap-1.5 mb-3">
            {performanceMetrics.map(({ period, label, pct }) => (
              <button
                key={period}
                onClick={() => setPricePeriod(period)}
                className={`flex-1 flex flex-col items-center justify-center py-2.5 rounded-lg transition-colors whitespace-nowrap ${
                  pricePeriod === period
                    ? 'bg-[#2962FF]/20 border border-[#2962FF]/50'
                    : 'hover:bg-[#1e222d] border border-[#2a2e39]'
                }`}
              >
                <span className="text-gray-400 text-sm mb-0.5">{label}</span>
                <span className={`text-base font-semibold ${
                  pct == null ? 'text-gray-600'
                  : pct > 0 ? 'text-[#26a69a]'
                  : pct < 0 ? 'text-[#ef5350]'
                  : 'text-gray-400'
                }`}>
                  {pct != null ? `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%` : '—'}
                </span>
              </button>
            ))}
          </div>
        )}

        {priceChartData.length > 0 ? (
          <ResponsiveContainer width="100%" height={340}>
            <LineChart data={priceChartData} margin={{ top: 10, right: 60, bottom: 0, left: 0 }}>
              <CartesianGrid horizontal={true} vertical={false} stroke="#1e222d" strokeWidth={1} />
              <XAxis
                dataKey="date" stroke="#363a45" fontSize={10} tickLine={false} axisLine={false}
                tickFormatter={(d: string) => {
                  if (pricePeriod === '1D' || pricePeriod === '5D') return d.slice(5);
                  if (pricePeriod === '1M') return d.slice(8);
                  return d.slice(0, 7);
                }}
                minTickGap={40}
              />
              <YAxis orientation="right" stroke="#363a45" fontSize={10} tickLine={false} axisLine={false} domain={['auto', 'auto']} tickFormatter={(v: number) => v.toFixed(1)} />
              <Tooltip
                contentStyle={{ backgroundColor: '#1e222d', border: '1px solid #363a45', borderRadius: '4px', padding: '8px 12px' }}
                labelStyle={{ color: '#787b86', fontSize: 11 }}
                itemStyle={{ color: '#d1d4dc', fontSize: 12 }}
                formatter={(value: unknown) => [`KES ${Number(value).toFixed(2)}`, 'Price']}
              />
              {currentPrice != null && (
                <ReferenceLine y={currentPrice} stroke={lineColor} strokeDasharray="2 2" strokeWidth={0.5} />
              )}
              <Line type="monotone" dataKey="price" stroke={lineColor} strokeWidth={1.5} dot={false} activeDot={{ r: 3, fill: lineColor, strokeWidth: 0 }} />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <p className="text-gray-500 text-center py-16 text-sm">No price data available</p>
        )}
      </div>

      {/* Valuation Trend Chart */}
      {trendChartData.length > 0 && (() => {
        const marketPrices = trendChartData.map(d => d.market_price).filter((v): v is number => v != null);
        const ivValues = trendChartData.map(d => d.intrinsic_value).filter((v): v is number => v != null);
        const allValues = [...marketPrices, ...ivValues];
        const maxY = Math.max(...allValues) * 1.05;
        const minY = Math.max(0, Math.min(...allValues) * 0.95);

        return (
          <div className="bg-[#131722] border border-[#2a2e39] rounded-xl p-5 mb-6">
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
              <div className="flex gap-1">
                {(['6M', '1Y', '5Y', 'ALL'] as TimePeriod[]).map((p) => (
                  <button
                    key={p}
                    onClick={() => setTrendPeriod(p)}
                    className={`px-2.5 py-1 text-xs font-medium rounded transition-colors ${
                      trendPeriod === p ? 'bg-[#2962FF] text-white' : 'text-gray-500 hover:text-gray-300 hover:bg-[#1e222d]'
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
                <CartesianGrid horizontal={true} vertical={false} stroke="#1e222d" strokeWidth={1} />
                <XAxis dataKey="date" stroke="#363a45" fontSize={10} tickLine={false} axisLine={false} tickFormatter={(d: string) => d.slice(5)} minTickGap={40} />
                <YAxis orientation="right" stroke="#363a45" fontSize={10} tickLine={false} axisLine={false} domain={[minY, maxY]} tickFormatter={(v: number) => v.toFixed(1)} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#1e222d', border: '1px solid #363a45', borderRadius: '4px', padding: '8px 12px' }}
                  labelStyle={{ color: '#787b86', fontSize: 11 }}
                  formatter={(value: unknown, name: unknown) => {
                    const label = name === 'market_price' ? 'Market Price' : 'Intrinsic Value';
                    return [value != null ? `KES ${Number(value).toFixed(2)}` : '—', label];
                  }}
                />
                <Area type="monotone" dataKey="intrinsic_value" stroke="none" fill="url(#buyZoneGradient)" dot={false} connectNulls />
                <Line type="monotone" dataKey="intrinsic_value" stroke="#26a69a" strokeWidth={1.5} strokeDasharray="4 3" dot={false} name="intrinsic_value" connectNulls />
                <Line type="monotone" dataKey="market_price" stroke="#f59e0b" strokeWidth={1.5} dot={false} name="market_price" connectNulls />
              </ComposedChart>
            </ResponsiveContainer>
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

      {/* Your Position */}
      {position && (
        <div className="bg-gradient-to-r from-blue-900/30 to-purple-900/30 border border-blue-500/30 rounded-xl p-5 mb-6">
          <h2 className="text-sm font-semibold text-blue-300 flex items-center gap-2 mb-3">
            <Briefcase size={16} />
            Your Position
          </h2>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
            <div>
              <p className="text-xs text-gray-400">Shares Held</p>
              <p className="text-lg font-bold text-white">{position.total_shares.toLocaleString()}</p>
            </div>
            <div>
              <p className="text-xs text-gray-400">Avg Cost</p>
              <p className="text-lg font-bold text-white">KES {position.average_cost_basis.toFixed(2)}</p>
            </div>
            <div>
              <p className="text-xs text-gray-400">Total Cost</p>
              <p className="text-lg font-bold text-white">KES {position.total_cost.toLocaleString(undefined, { maximumFractionDigits: 0 })}</p>
            </div>
            <div>
              <p className="text-xs text-gray-400">Current Value</p>
              <p className="text-lg font-bold text-white">
                {position.current_value != null ? `KES ${position.current_value.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : '—'}
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-400">Unrealized P&L</p>
              <p className={`text-lg font-bold ${(position.unrealized_pnl ?? 0) >= 0 ? 'text-gain' : 'text-loss'}`}>
                {position.unrealized_pnl != null
                  ? `${position.unrealized_pnl >= 0 ? '+' : ''}KES ${position.unrealized_pnl.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
                  : '—'}
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-400">P&L %</p>
              <p className={`text-lg font-bold ${(position.unrealized_pnl_pct ?? 0) >= 0 ? 'text-gain' : 'text-loss'}`}>
                {position.unrealized_pnl_pct != null
                  ? `${position.unrealized_pnl_pct >= 0 ? '+' : ''}${position.unrealized_pnl_pct.toFixed(2)}%`
                  : '—'}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Valuation Section */}
      <div className="bg-dark-surface border border-dark-border rounded-xl p-6 mb-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <Calculator size={18} className="text-purple-400" />
            Valuation
          </h2>
          <div className="flex items-center gap-2">
            {isCustom && (
              <span className="px-2 py-0.5 text-xs bg-yellow-600/30 text-yellow-400 rounded">Custom</span>
            )}
            <button
              onClick={() => handleCompute(false)}
              disabled={computing}
              className="flex items-center gap-2 px-3 py-1.5 bg-primary-600 hover:bg-primary-700 disabled:opacity-50 text-white text-sm rounded-lg transition-colors"
            >
              <RefreshCw size={14} className={computing ? 'animate-spin' : ''} />
              {computing ? 'Computing...' : 'Compute Valuation'}
            </button>
          </div>
        </div>

        {valuation ? (
          <>
            {/* Primary metrics */}
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 mb-4">
              <div className="p-3 bg-dark-bg rounded-lg">
                <p className="text-xs text-gray-400 mb-1">Intrinsic Value</p>
                <p className="text-lg font-bold text-white">
                  {fmtKES(valuation.weighted_intrinsic_value)}
                </p>
              </div>
              <div className="p-3 bg-dark-bg rounded-lg">
                <p className="text-xs text-gray-400 mb-1">Margin of Safety</p>
                <p className={`text-lg font-bold ${(valuation.margin_of_safety_pct ?? 0) > 0 ? 'text-gain' : 'text-loss'}`}>
                  {fmtPct(valuation.margin_of_safety_pct)}
                </p>
              </div>
              <div className="p-3 bg-dark-bg rounded-lg">
                <p className="text-xs text-gray-400 mb-1">Market Price</p>
                <p className="text-lg font-bold text-white">
                  {fmtKES(valuation.current_market_price)}
                </p>
              </div>
              <div className="p-3 bg-dark-bg rounded-lg">
                <p className="text-xs text-gray-400 mb-1">DCF Value</p>
                <p className={`text-lg font-bold ${valuation.dcf_value ? 'text-blue-400' : 'text-gray-500'}`}>
                  {valuation.dcf_value ? fmtKES(valuation.dcf_value) : '—'}
                </p>
              </div>
              <div className="p-3 bg-dark-bg rounded-lg">
                <p className="text-xs text-gray-400 mb-1">EPV Value</p>
                <p className={`text-lg font-bold ${valuation.epv_value ? 'text-teal-400' : 'text-gray-500'}`}>
                  {valuation.epv_value ? fmtKES(valuation.epv_value) : '—'}
                </p>
              </div>
              <div className="p-3 bg-dark-bg rounded-lg">
                <p className="text-xs text-gray-400 mb-1">Book Value</p>
                <p className={`text-lg font-bold ${valuation.book_value_estimate && valuation.book_value_estimate > 0 ? 'text-amber-400' : 'text-loss'}`}>
                  {valuation.book_value_estimate ? fmtKES(valuation.book_value_estimate) : '—'}
                </p>
              </div>
            </div>

            {/* Assumptions & Stress Test */}
            <div className="mb-4">
              <button
                onClick={() => {
                  const next = !showAssumptions;
                  setShowAssumptions(next);
                  if (next && assumptions && !customDiscountRate) populateFromCurrent();
                }}
                className="flex items-center gap-2 text-xs text-gray-400 hover:text-gray-300 transition-colors"
              >
                <Info size={12} />
                {showAssumptions ? 'Hide' : 'Show'} Assumptions & Stress Test
              </button>
              {showAssumptions && (
                <div className="mt-3 p-4 bg-dark-bg rounded-lg text-sm">
                  {/* Current values (read-only) */}
                  {assumptions && (
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4 pb-4 border-b border-dark-border">
                      <div>
                        <span className="text-gray-500 text-xs">Current Discount Rate</span>
                        <p className="text-gray-300">{(assumptions.discount_rate * 100).toFixed(0)}%</p>
                      </div>
                      <div>
                        <span className="text-gray-500 text-xs">Growth Rate Used</span>
                        <p className="text-gray-300">
                          {calcDetails && (calcDetails.dcf as { growth_rate_used?: number })?.growth_rate_used != null
                            ? ((calcDetails.dcf as { growth_rate_used: number }).growth_rate_used * 100).toFixed(1) + '%'
                            : '—'}
                        </p>
                      </div>
                      <div>
                        <span className="text-gray-500 text-xs">Historical FCFs</span>
                        <p className="text-gray-300 text-xs">
                          {calcDetails && (calcDetails.dcf as { historical_fcfs?: number[] })?.historical_fcfs
                            ? (calcDetails.dcf as { historical_fcfs: number[] }).historical_fcfs.map(f => fmtNum(f)).join(', ')
                            : '—'}
                        </p>
                      </div>
                      <div>
                        <span className="text-gray-500 text-xs">Weights Applied</span>
                        <p className="text-gray-300">
                          {calcDetails && (calcDetails as { weights_applied?: Record<string, number> }).weights_applied
                            ? Object.entries((calcDetails as { weights_applied: Record<string, number> }).weights_applied)
                                .map(([k, v]) => `${k.toUpperCase()} ${(v * 100).toFixed(0)}%`)
                                .join(', ')
                            : '—'}
                        </p>
                      </div>
                    </div>
                  )}

                  {/* Editable inputs */}
                  <p className="text-xs text-gray-400 mb-3 font-medium">✏️ Custom Assumptions (edit & recompute to stress-test)</p>
                  <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 mb-3">
                    <div>
                      <label className="text-gray-500 text-xs block mb-1">Discount Rate %</label>
                      <input
                        type="number" min="1" max="50" step="1"
                        value={customDiscountRate}
                        onChange={(e) => setCustomDiscountRate(e.target.value)}
                        placeholder="e.g. 15"
                        className="w-full px-2 py-1.5 bg-dark-surface border border-dark-border rounded text-white text-sm focus:border-primary-500 focus:outline-none"
                      />
                    </div>
                    <div>
                      <label className="text-gray-500 text-xs block mb-1">Terminal Growth %</label>
                      <input
                        type="number" min="0" max="10" step="0.5"
                        value={customTerminalGrowth}
                        onChange={(e) => setCustomTerminalGrowth(e.target.value)}
                        placeholder="e.g. 3"
                        className="w-full px-2 py-1.5 bg-dark-surface border border-dark-border rounded text-white text-sm focus:border-primary-500 focus:outline-none"
                      />
                    </div>
                    <div>
                      <label className="text-gray-500 text-xs block mb-1">Projection Years</label>
                      <input
                        type="number" min="5" max="20" step="1"
                        value={customProjectionYears}
                        onChange={(e) => setCustomProjectionYears(e.target.value)}
                        placeholder="e.g. 10"
                        className="w-full px-2 py-1.5 bg-dark-surface border border-dark-border rounded text-white text-sm focus:border-primary-500 focus:outline-none"
                      />
                    </div>
                    <div>
                      <label className="text-gray-500 text-xs block mb-1">DCF Weight %</label>
                      <input
                        type="number" min="0" max="100" step="5"
                        value={customDcfWeight}
                        onChange={(e) => setCustomDcfWeight(e.target.value)}
                        placeholder="e.g. 50"
                        className="w-full px-2 py-1.5 bg-dark-surface border border-dark-border rounded text-white text-sm focus:border-primary-500 focus:outline-none"
                      />
                    </div>
                    <div>
                      <label className="text-gray-500 text-xs block mb-1">EPV Weight %</label>
                      <input
                        type="number" min="0" max="100" step="5"
                        value={customEpvWeight}
                        onChange={(e) => setCustomEpvWeight(e.target.value)}
                        placeholder="e.g. 30"
                        className="w-full px-2 py-1.5 bg-dark-surface border border-dark-border rounded text-white text-sm focus:border-primary-500 focus:outline-none"
                      />
                    </div>
                    <div>
                      <label className="text-gray-500 text-xs block mb-1">BV Weight %</label>
                      <input
                        type="number" min="0" max="100" step="5"
                        value={customBvWeight}
                        onChange={(e) => setCustomBvWeight(e.target.value)}
                        placeholder="e.g. 20"
                        className="w-full px-2 py-1.5 bg-dark-surface border border-dark-border rounded text-white text-sm focus:border-primary-500 focus:outline-none"
                      />
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => handleCompute(true)}
                      disabled={computing}
                      className="flex items-center gap-2 px-3 py-1.5 bg-yellow-600 hover:bg-yellow-700 disabled:opacity-50 text-white text-sm rounded-lg transition-colors"
                    >
                      <Calculator size={14} />
                      {computing ? 'Computing...' : 'Recompute with Custom Assumptions'}
                    </button>
                    <button
                      onClick={() => { resetAssumptions(); handleCompute(false); }}
                      disabled={computing}
                      className="flex items-center gap-2 px-3 py-1.5 bg-dark-surface border border-dark-border hover:bg-dark-border/50 text-gray-300 text-sm rounded-lg transition-colors"
                    >
                      <RotateCcw size={14} />
                      Reset to Defaults
                    </button>
                  </div>
                </div>
              )}
            </div>
          </>
        ) : (
          <p className="text-gray-400 text-center py-4">
            No valuation computed yet. Click "Compute Valuation" to generate one.
          </p>
        )}

        {/* Recommendation */}
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

      {/* Key Ratios */}
      {latestFinancial && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
          <div className="bg-dark-surface border border-dark-border rounded-xl p-4">
            <p className="text-xs text-gray-400 mb-1">P/E Ratio</p>
            <p className="text-xl font-bold text-white">{pe != null ? pe.toFixed(1) : '—'}</p>
            <p className="text-xs text-gray-500">Price / EPS</p>
          </div>
          <div className="bg-dark-surface border border-dark-border rounded-xl p-4">
            <p className="text-xs text-gray-400 mb-1">P/B Ratio</p>
            <p className="text-xl font-bold text-white">{pb != null ? pb.toFixed(2) : '—'}</p>
            <p className="text-xs text-gray-500">Price / Book Value</p>
          </div>
          <div className="bg-dark-surface border border-dark-border rounded-xl p-4">
            <p className="text-xs text-gray-400 mb-1">Debt / Equity</p>
            <p className={`text-xl font-bold ${latestFinancial.debt_to_equity && latestFinancial.debt_to_equity > 2 ? 'text-loss' : 'text-white'}`}>
              {latestFinancial.debt_to_equity != null ? latestFinancial.debt_to_equity.toFixed(2) : '—'}
            </p>
            <p className="text-xs text-gray-500">Total Debt / Equity</p>
          </div>
          <div className="bg-dark-surface border border-dark-border rounded-xl p-4">
            <p className="text-xs text-gray-400 mb-1">Dividend Yield</p>
            <p className="text-xl font-bold text-white">{divYield != null ? (divYield * 100).toFixed(1) + '%' : '—'}</p>
            <p className="text-xs text-gray-500">DPS / Price</p>
          </div>
        </div>
      )}

      {/* Financial Trend Chart */}
      {financialChartData.length > 1 && (
        <div className="bg-dark-surface border border-dark-border rounded-xl p-6 mb-6">
          <h2 className="text-lg font-semibold text-white flex items-center gap-2 mb-4">
            <TrendingUp size={18} className="text-blue-400" />
            Financial Trend (KES Billions)
          </h2>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={financialChartData} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2a2e39" />
              <XAxis dataKey="year" stroke="#787b86" fontSize={11} />
              <YAxis stroke="#787b86" fontSize={10} tickFormatter={(v: number) => v.toFixed(0)} />
              <Tooltip
                contentStyle={{ backgroundColor: '#1e222d', border: '1px solid #363a45', borderRadius: '4px' }}
                labelStyle={{ color: '#787b86' }}
                formatter={(value: unknown, name: unknown) => [`KES ${Number(value).toFixed(1)}B`, name === 'revenue' ? 'Revenue' : name === 'net_income' ? 'Net Income' : 'FCF']}
              />
              <Bar dataKey="revenue" fill="#3b82f6" radius={[2, 2, 0, 0]} name="revenue" />
              <Bar dataKey="net_income" fill="#8b5cf6" radius={[2, 2, 0, 0]} name="net_income" />
              <Bar dataKey="fcf" fill="#10b981" radius={[2, 2, 0, 0]} name="fcf" />
            </BarChart>
          </ResponsiveContainer>
          <div className="flex items-center gap-5 mt-2 text-[10px] text-gray-500">
            <span className="flex items-center gap-1.5"><span className="w-3 h-2.5 bg-blue-500 inline-block rounded-sm" /> Revenue</span>
            <span className="flex items-center gap-1.5"><span className="w-3 h-2.5 bg-purple-500 inline-block rounded-sm" /> Net Income</span>
            <span className="flex items-center gap-1.5"><span className="w-3 h-2.5 bg-emerald-500 inline-block rounded-sm" /> Free Cash Flow</span>
          </div>
        </div>
      )}

      {/* Financial Statements — Expanded */}
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
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-gray-400 border-b border-dark-border">
                  <th className="pb-3 font-medium sticky left-0 bg-dark-surface">Year</th>
                  <th className="pb-3 font-medium px-2">Revenue</th>
                  <th className="pb-3 font-medium px-2">Net Income</th>
                  <th className="pb-3 font-medium px-2">EPS</th>
                  <th className="pb-3 font-medium px-2">FCF</th>
                  <th className="pb-3 font-medium px-2">OCF</th>
                  <th className="pb-3 font-medium px-2">CapEx</th>
                  <th className="pb-3 font-medium px-2">Equity</th>
                  <th className="pb-3 font-medium px-2">BVPS</th>
                  <th className="pb-3 font-medium px-2">D/E</th>
                  <th className="pb-3 font-medium px-2">ROE</th>
                  <th className="pb-3 font-medium px-2">DPS</th>
                  <th className="pb-3 font-medium px-2">Source</th>
                  <th className="pb-3 font-medium px-2"></th>
                </tr>
              </thead>
              <tbody>
                {[...financials].sort((a, b) => b.fiscal_year - a.fiscal_year).map((fs) => {
                  const source = getDataSource(fs.notes);
                  return (
                    <tr key={fs.id} className="border-b border-dark-border/50 hover:bg-dark-border/10">
                      <td className="py-2.5 sticky left-0 bg-dark-surface">
                        <span className="px-2 py-0.5 bg-dark-border/50 rounded text-xs text-gray-300">
                          {fs.fiscal_year}
                        </span>
                      </td>
                      <td className="py-2.5 px-2 text-gray-300">{fmtNum(fs.revenue)}</td>
                      <td className={`py-2.5 px-2 ${fs.net_income && fs.net_income < 0 ? 'text-loss' : 'text-gray-300'}`}>
                        {fmtNum(fs.net_income)}
                      </td>
                      <td className="py-2.5 px-2 text-gray-300">
                        {fs.earnings_per_share != null ? fs.earnings_per_share.toFixed(2) : '—'}
                      </td>
                      <td className={`py-2.5 px-2 ${fs.free_cash_flow && fs.free_cash_flow < 0 ? 'text-loss' : 'text-gain'}`}>
                        {fmtNum(fs.free_cash_flow)}
                      </td>
                      <td className="py-2.5 px-2 text-gray-300">{fmtNum(fs.operating_cash_flow)}</td>
                      <td className="py-2.5 px-2 text-gray-300">{fmtNum(fs.capital_expenditures)}</td>
                      <td className={`py-2.5 px-2 ${fs.total_equity && fs.total_equity < 0 ? 'text-loss' : 'text-gray-300'}`}>
                        {fmtNum(fs.total_equity)}
                      </td>
                      <td className="py-2.5 px-2 text-gray-300">
                        {fs.book_value_per_share != null ? fs.book_value_per_share.toFixed(2) : '—'}
                      </td>
                      <td className={`py-2.5 px-2 ${fs.debt_to_equity && (fs.debt_to_equity > 2 || fs.debt_to_equity < 0) ? 'text-loss' : 'text-gray-300'}`}>
                        {fs.debt_to_equity != null ? fs.debt_to_equity.toFixed(2) : '—'}
                      </td>
                      <td className="py-2.5 px-2 text-gray-300">{fmtPct(fs.return_on_equity)}</td>
                      <td className="py-2.5 px-2 text-gray-300">
                        {fs.dividends_per_share != null ? fs.dividends_per_share.toFixed(2) : '—'}
                      </td>
                      <td className="py-2.5 px-2">
                        <span className={`px-1.5 py-0.5 rounded text-[10px] text-white ${source.color}`}>
                          {source.label}
                        </span>
                      </td>
                      <td className="py-2.5 px-2">
                        <Link
                          to={`/companies/${companyId}/financials/${fs.id}/edit`}
                          className="text-gray-400 hover:text-primary-400 transition-colors"
                          title="Edit"
                        >
                          <Edit3 size={14} />
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* YoY Growth Analysis */}
      {financials.length >= 2 && (
        <div className="bg-dark-surface border border-dark-border rounded-xl p-6 mt-6">
          <h2 className="text-lg font-semibold text-white flex items-center gap-2 mb-4">
            <TrendingUp size={18} className="text-cyan-400" />
            Year-over-Year Growth Analysis
          </h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-gray-400 border-b border-dark-border">
                  <th className="pb-3 font-medium sticky left-0 bg-dark-surface">Year</th>
                  <th className="pb-3 font-medium px-2">Revenue (B)</th>
                  <th className="pb-3 font-medium px-2">Rev YoY</th>
                  <th className="pb-3 font-medium px-2">Net Inc (B)</th>
                  <th className="pb-3 font-medium px-2">NI YoY</th>
                  <th className="pb-3 font-medium px-2">EPS</th>
                  <th className="pb-3 font-medium px-2">EPS YoY</th>
                  <th className="pb-3 font-medium px-2">Assets (B)</th>
                  <th className="pb-3 font-medium px-2">Assets YoY</th>
                  <th className="pb-3 font-medium px-2">Equity (B)</th>
                  <th className="pb-3 font-medium px-2">Equity YoY</th>
                  <th className="pb-3 font-medium px-2">Liabilities (B)</th>
                  <th className="pb-3 font-medium px-2">Liab YoY</th>
                </tr>
              </thead>
              <tbody>
                {(() => {
                  const sorted = [...financials].sort((a, b) => a.fiscal_year - b.fiscal_year);
                  const yoyPct = (curr: number | null, prev: number | null) => {
                    if (curr == null || prev == null || prev === 0) return null;
                    return ((curr - prev) / Math.abs(prev)) * 100;
                  };
                  const fmtB = (v: number | null) => v != null ? (v / 1e9).toFixed(2) : '—';
                  const fmtYoY = (v: number | null) => {
                    if (v == null) return <span className="text-gray-600">—</span>;
                    const color = v > 0 ? 'text-gain' : v < 0 ? 'text-loss' : 'text-gray-400';
                    return <span className={color}>{v > 0 ? '+' : ''}{v.toFixed(1)}%</span>;
                  };
                  return sorted.map((fs, idx) => {
                    const prev = idx > 0 ? sorted[idx - 1] : null;
                    const liabilities = fs.total_assets != null && fs.total_equity != null
                      ? fs.total_assets - fs.total_equity : null;
                    const prevLiabilities = prev && prev.total_assets != null && prev.total_equity != null
                      ? prev.total_assets - prev.total_equity : null;
                    return (
                      <tr key={fs.id} className="border-b border-dark-border/50 hover:bg-dark-border/10">
                        <td className="py-2.5 sticky left-0 bg-dark-surface">
                          <span className="px-2 py-0.5 bg-dark-border/50 rounded text-xs text-gray-300">
                            {fs.fiscal_year}
                          </span>
                        </td>
                        <td className="py-2.5 px-2 text-gray-300">{fmtB(fs.revenue)}</td>
                        <td className="py-2.5 px-2">{fmtYoY(yoyPct(fs.revenue, prev?.revenue ?? null))}</td>
                        <td className="py-2.5 px-2 text-gray-300">{fmtB(fs.net_income)}</td>
                        <td className="py-2.5 px-2">{fmtYoY(yoyPct(fs.net_income, prev?.net_income ?? null))}</td>
                        <td className="py-2.5 px-2 text-gray-300">
                          {fs.earnings_per_share != null ? fs.earnings_per_share.toFixed(2) : '—'}
                        </td>
                        <td className="py-2.5 px-2">
                          {fmtYoY(yoyPct(fs.earnings_per_share, prev?.earnings_per_share ?? null))}
                        </td>
                        <td className="py-2.5 px-2 text-gray-300">{fmtB(fs.total_assets)}</td>
                        <td className="py-2.5 px-2">{fmtYoY(yoyPct(fs.total_assets, prev?.total_assets ?? null))}</td>
                        <td className="py-2.5 px-2 text-gray-300">{fmtB(fs.total_equity)}</td>
                        <td className="py-2.5 px-2">{fmtYoY(yoyPct(fs.total_equity, prev?.total_equity ?? null))}</td>
                        <td className="py-2.5 px-2 text-gray-300">{fmtB(liabilities)}</td>
                        <td className="py-2.5 px-2">{fmtYoY(yoyPct(liabilities, prevLiabilities))}</td>
                      </tr>
                    );
                  });
                })()}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Notes Section */}
      <div className="bg-dark-surface border border-dark-border rounded-xl p-6 mb-6">
        <button
          onClick={() => setShowNotes(!showNotes)}
          className="flex items-center gap-2 w-full text-left"
        >
          <MessageSquare size={18} className="text-primary-400" />
          <h3 className="text-lg font-semibold flex-1">Notes ({notes.length})</h3>
          <span className="text-gray-500 text-sm">{showNotes ? '▾' : '▸'}</span>
        </button>

        {showNotes && (
          <div className="mt-4 space-y-4">
            {/* Add new note */}
            <div className="border border-dark-border rounded-lg p-3 space-y-2">
              <textarea
                value={newNoteText}
                onChange={(e) => setNewNoteText(e.target.value)}
                placeholder="Add a note — buy thesis, sell reasoning, observations..."
                className="w-full bg-dark-bg border border-dark-border rounded px-3 py-2 text-sm text-white placeholder-gray-500 resize-none focus:outline-none focus:border-primary-500"
                rows={3}
              />
              <div className="flex items-center gap-2">
                <select
                  value={newNoteTag}
                  onChange={(e) => setNewNoteTag(e.target.value)}
                  className="bg-dark-bg border border-dark-border rounded px-2 py-1.5 text-sm text-white focus:outline-none focus:border-primary-500"
                >
                  <option value="">No tag</option>
                  <option value="buy_thesis">Buy Thesis</option>
                  <option value="sell_thesis">Sell Thesis</option>
                  <option value="observation">Observation</option>
                  <option value="risk">Risk</option>
                  <option value="catalyst">Catalyst</option>
                </select>
                <button
                  onClick={handleCreateNote}
                  disabled={!newNoteText.trim()}
                  className="ml-auto flex items-center gap-1.5 bg-primary-600 hover:bg-primary-700 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm px-3 py-1.5 rounded transition-colors"
                >
                  <Plus size={14} /> Add Note
                </button>
              </div>
            </div>

            {/* Existing notes */}
            {notes.length === 0 ? (
              <p className="text-gray-500 text-sm text-center py-4">No notes yet</p>
            ) : (
              <div className="space-y-2">
                {notes.map((note) => {
                  const tagColors: Record<string, string> = {
                    buy_thesis: 'bg-green-600/20 text-green-400',
                    sell_thesis: 'bg-red-600/20 text-red-400',
                    observation: 'bg-blue-600/20 text-blue-400',
                    risk: 'bg-orange-600/20 text-orange-400',
                    catalyst: 'bg-purple-600/20 text-purple-400',
                  };
                  const tagLabel: Record<string, string> = {
                    buy_thesis: 'Buy Thesis',
                    sell_thesis: 'Sell Thesis',
                    observation: 'Observation',
                    risk: 'Risk',
                    catalyst: 'Catalyst',
                  };

                  if (editingNoteId === note.id) {
                    return (
                      <div key={note.id} className="border border-primary-500/50 rounded-lg p-3 space-y-2">
                        <textarea
                          value={editNoteText}
                          onChange={(e) => setEditNoteText(e.target.value)}
                          className="w-full bg-dark-bg border border-dark-border rounded px-3 py-2 text-sm text-white resize-none focus:outline-none focus:border-primary-500"
                          rows={3}
                        />
                        <div className="flex items-center gap-2">
                          <select
                            value={editNoteTag}
                            onChange={(e) => setEditNoteTag(e.target.value)}
                            className="bg-dark-bg border border-dark-border rounded px-2 py-1.5 text-sm text-white focus:outline-none focus:border-primary-500"
                          >
                            <option value="">No tag</option>
                            <option value="buy_thesis">Buy Thesis</option>
                            <option value="sell_thesis">Sell Thesis</option>
                            <option value="observation">Observation</option>
                            <option value="risk">Risk</option>
                            <option value="catalyst">Catalyst</option>
                          </select>
                          <button
                            onClick={() => handleUpdateNote(note.id)}
                            className="ml-auto flex items-center gap-1 text-green-400 hover:text-green-300 text-sm"
                          >
                            <Save size={14} /> Save
                          </button>
                          <button
                            onClick={() => setEditingNoteId(null)}
                            className="flex items-center gap-1 text-gray-400 hover:text-gray-300 text-sm"
                          >
                            <X size={14} /> Cancel
                          </button>
                        </div>
                      </div>
                    );
                  }

                  return (
                    <div key={note.id} className="border border-dark-border rounded-lg p-3 group">
                      <div className="flex items-start gap-2">
                        <div className="flex-1 min-w-0">
                          {note.tag && (
                            <span className={`inline-block text-[10px] font-medium px-1.5 py-0.5 rounded mb-1 ${tagColors[note.tag] || 'bg-gray-600/20 text-gray-400'}`}>
                              {tagLabel[note.tag] || note.tag}
                            </span>
                          )}
                          <p className="text-sm text-gray-200 whitespace-pre-wrap">{note.note_text}</p>
                          <p className="text-[10px] text-gray-600 mt-1">
                            {new Date(note.updated_at).toLocaleDateString('en-KE', { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                          </p>
                        </div>
                        <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                          <button
                            onClick={() => { setEditingNoteId(note.id); setEditNoteText(note.note_text); setEditNoteTag(note.tag || ''); }}
                            className="text-gray-500 hover:text-primary-400 p-1"
                            title="Edit"
                          >
                            <Edit3 size={13} />
                          </button>
                          <button
                            onClick={() => handleDeleteNote(note.id)}
                            className="text-gray-500 hover:text-red-400 p-1"
                            title="Delete"
                          >
                            <Trash2 size={13} />
                          </button>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
