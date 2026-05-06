import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { Plus, Briefcase, TrendingUp, TrendingDown, X } from 'lucide-react';
import toast from 'react-hot-toast';
import { portfolioApi, stocksApi } from '../lib/services';
import type { Portfolio, Holding, Transaction, PortfolioPerformance, Company } from '../types';
import { SkeletonCard, PageLoader } from '../components/ui/LoadingSpinner';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

interface TransactionForm {
  company_id: number;
  transaction_type: 'buy' | 'sell';
  shares: number;
  price_per_share: number;
  transaction_date: string;
  notes: string;
}

export default function PortfolioPage() {
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  const [selectedPortfolio, setSelectedPortfolio] = useState<Portfolio | null>(null);
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [performance, setPerformance] = useState<PortfolioPerformance | null>(null);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreatePortfolio, setShowCreatePortfolio] = useState(false);
  const [showAddTransaction, setShowAddTransaction] = useState(false);
  const [newPortfolioName, setNewPortfolioName] = useState('');

  const { register, handleSubmit, reset } = useForm<TransactionForm>({
    defaultValues: { transaction_type: 'buy', transaction_date: new Date().toISOString().split('T')[0] },
  });

  useEffect(() => {
    loadPortfolios();
    stocksApi.getCompanies().then((res) => setCompanies(res.data)).catch(() => {});
  }, []);

  const loadPortfolios = async () => {
    try {
      const res = await portfolioApi.list();
      setPortfolios(res.data);
      if (res.data.length > 0 && !selectedPortfolio) {
        selectPortfolio(res.data[0]);
      } else {
        setLoading(false);
      }
    } catch {
      setLoading(false);
    }
  };

  const selectPortfolio = async (portfolio: Portfolio) => {
    setSelectedPortfolio(portfolio);
    setLoading(true);
    try {
      const [holdingsRes, transRes, perfRes] = await Promise.all([
        portfolioApi.getHoldings(portfolio.id),
        portfolioApi.getTransactions(portfolio.id),
        portfolioApi.getPerformance(portfolio.id),
      ]);
      setHoldings(holdingsRes.data);
      setTransactions(transRes.data);
      setPerformance(perfRes.data);
    } catch {
      toast.error('Failed to load portfolio data');
    } finally {
      setLoading(false);
    }
  };

  const createPortfolio = async () => {
    if (!newPortfolioName.trim()) return;
    try {
      const res = await portfolioApi.create({ name: newPortfolioName });
      setPortfolios([...portfolios, res.data]);
      setNewPortfolioName('');
      setShowCreatePortfolio(false);
      selectPortfolio(res.data);
      toast.success('Portfolio created');
    } catch {
      toast.error('Failed to create portfolio');
    }
  };

  const onAddTransaction = async (data: TransactionForm) => {
    if (!selectedPortfolio) return;
    try {
      await portfolioApi.createTransaction(selectedPortfolio.id, {
        ...data,
        company_id: Number(data.company_id),
        shares: Number(data.shares),
        price_per_share: Number(data.price_per_share),
      });
      toast.success('Transaction recorded');
      setShowAddTransaction(false);
      reset();
      selectPortfolio(selectedPortfolio);
    } catch {
      toast.error('Failed to record transaction');
    }
  };

  const deletePortfolio = async (id: number) => {
    if (!confirm('Delete this portfolio?')) return;
    try {
      await portfolioApi.delete(id);
      const remaining = portfolios.filter((p) => p.id !== id);
      setPortfolios(remaining);
      if (remaining.length > 0) selectPortfolio(remaining[0]);
      else { setSelectedPortfolio(null); setHoldings([]); setTransactions([]); setPerformance(null); }
      toast.success('Portfolio deleted');
    } catch {
      toast.error('Failed to delete portfolio');
    }
  };

  const formatCurrency = (val: number) =>
    new Intl.NumberFormat('en-US', { style: 'currency', currency: 'KES', maximumFractionDigits: 0 }).format(val);

  if (loading && portfolios.length === 0) return <PageLoader />;

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-white">Portfolio</h1>
        <button
          onClick={() => setShowCreatePortfolio(true)}
          className="flex items-center gap-2 px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg transition-colors"
        >
          <Plus size={16} />
          New Portfolio
        </button>
      </div>

      {/* Create Portfolio Modal */}
      {showCreatePortfolio && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-dark-surface border border-dark-border rounded-xl p-6 w-full max-w-md">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-white">Create Portfolio</h3>
              <button onClick={() => setShowCreatePortfolio(false)} className="text-gray-400 hover:text-white">
                <X size={20} />
              </button>
            </div>
            <input
              value={newPortfolioName}
              onChange={(e) => setNewPortfolioName(e.target.value)}
              placeholder="Portfolio name"
              className="w-full px-4 py-2.5 bg-dark-bg border border-dark-border rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-primary-500 mb-4"
            />
            <div className="flex gap-3 justify-end">
              <button onClick={() => setShowCreatePortfolio(false)} className="px-4 py-2 text-gray-400 hover:text-white">Cancel</button>
              <button onClick={createPortfolio} className="px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg">Create</button>
            </div>
          </div>
        </div>
      )}

      {/* Portfolio Tabs */}
      {portfolios.length > 0 && (
        <div className="flex gap-2 mb-6 overflow-x-auto pb-2">
          {portfolios.map((p) => (
            <button
              key={p.id}
              onClick={() => selectPortfolio(p)}
              className={`px-4 py-2 rounded-lg whitespace-nowrap text-sm font-medium transition-colors ${
                selectedPortfolio?.id === p.id
                  ? 'bg-primary-600 text-white'
                  : 'bg-dark-surface text-gray-400 hover:text-white border border-dark-border'
              }`}
            >
              {p.name}
            </button>
          ))}
        </div>
      )}

      {!selectedPortfolio ? (
        <div className="bg-dark-surface border border-dark-border rounded-xl p-12 text-center">
          <Briefcase className="mx-auto text-gray-600 mb-3" size={40} />
          <p className="text-gray-400">Create your first portfolio to get started</p>
        </div>
      ) : (
        <>
          {/* Performance Summary */}
          {performance && (
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
              <div className="bg-dark-surface border border-dark-border rounded-xl p-4">
                <p className="text-sm text-gray-400">Total Invested</p>
                <p className="text-xl font-bold text-white">{formatCurrency(performance.total_invested)}</p>
              </div>
              <div className="bg-dark-surface border border-dark-border rounded-xl p-4">
                <p className="text-sm text-gray-400">Current Value</p>
                <p className="text-xl font-bold text-white">{formatCurrency(performance.current_value)}</p>
              </div>
              <div className="bg-dark-surface border border-dark-border rounded-xl p-4">
                <p className="text-sm text-gray-400">Total Gain</p>
                <p className={`text-xl font-bold ${performance.total_gain >= 0 ? 'text-gain' : 'text-loss'}`}>
                  {formatCurrency(performance.total_gain)}
                </p>
              </div>
              <div className="bg-dark-surface border border-dark-border rounded-xl p-4">
                <p className="text-sm text-gray-400">Return %</p>
                <p className={`text-xl font-bold ${performance.total_gain_pct >= 0 ? 'text-gain' : 'text-loss'}`}>
                  {performance.total_gain_pct >= 0 ? '+' : ''}{performance.total_gain_pct.toFixed(2)}%
                </p>
              </div>
            </div>
          )}

          {/* Holdings */}
          <div className="bg-dark-surface border border-dark-border rounded-xl p-6 mb-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold text-white">Holdings</h2>
              <button
                onClick={() => setShowAddTransaction(true)}
                className="flex items-center gap-1 px-3 py-1.5 bg-green-600 hover:bg-green-700 text-white text-sm rounded-lg"
              >
                <Plus size={14} /> Add Transaction
              </button>
            </div>

            {holdings.length === 0 ? (
              <p className="text-gray-400 text-center py-4">No holdings yet. Add a buy transaction to get started.</p>
            ) : (
              <>
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead>
                      <tr className="text-left text-sm text-gray-400 border-b border-dark-border">
                        <th className="pb-3 font-medium">Company</th>
                        <th className="pb-3 font-medium text-right">Shares</th>
                        <th className="pb-3 font-medium text-right">Avg Cost</th>
                        <th className="pb-3 font-medium text-right">Current</th>
                        <th className="pb-3 font-medium text-right">Gain/Loss</th>
                      </tr>
                    </thead>
                    <tbody>
                      {holdings.map((h) => (
                        <tr key={h.company_id} className="border-b border-dark-border/50">
                          <td className="py-3">
                            <p className="text-white font-medium">{h.company_name}</p>
                            <p className="text-xs text-gray-500">{h.symbol}</p>
                          </td>
                          <td className="py-3 text-right text-gray-300">{h.total_shares}</td>
                          <td className="py-3 text-right text-gray-300">{h.average_cost.toFixed(2)}</td>
                          <td className="py-3 text-right text-gray-300">{h.current_price?.toFixed(2) ?? '—'}</td>
                          <td className="py-3 text-right">
                            {h.unrealized_gain_pct !== null ? (
                              <span className={h.unrealized_gain_pct >= 0 ? 'text-gain' : 'text-loss'}>
                                {h.unrealized_gain_pct >= 0 ? '+' : ''}{h.unrealized_gain_pct.toFixed(2)}%
                              </span>
                            ) : '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* Holdings Chart */}
                <div className="mt-6">
                  <ResponsiveContainer width="100%" height={200}>
                    <BarChart data={holdings.map((h) => ({ name: h.symbol, value: h.current_value || h.total_cost }))}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                      <XAxis dataKey="name" stroke="#64748b" fontSize={12} />
                      <YAxis stroke="#64748b" fontSize={12} />
                      <Tooltip
                        contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }}
                        labelStyle={{ color: '#fff' }}
                      />
                      <Bar dataKey="value" fill="#3b82f6" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </>
            )}
          </div>

          {/* Transaction History */}
          <div className="bg-dark-surface border border-dark-border rounded-xl p-6 mb-6">
            <h2 className="text-lg font-semibold text-white mb-4">Transaction History</h2>
            {transactions.length === 0 ? (
              <p className="text-gray-400 text-center py-4">No transactions yet.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="text-left text-sm text-gray-400 border-b border-dark-border">
                      <th className="pb-3 font-medium">Date</th>
                      <th className="pb-3 font-medium">Type</th>
                      <th className="pb-3 font-medium">Company</th>
                      <th className="pb-3 font-medium text-right">Shares</th>
                      <th className="pb-3 font-medium text-right">Price</th>
                      <th className="pb-3 font-medium text-right">Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {transactions.map((t) => (
                      <tr key={t.id} className="border-b border-dark-border/50">
                        <td className="py-3 text-gray-300">{t.transaction_date}</td>
                        <td className="py-3">
                          <span className={`flex items-center gap-1 ${t.transaction_type === 'buy' ? 'text-gain' : 'text-loss'}`}>
                            {t.transaction_type === 'buy' ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
                            {t.transaction_type.toUpperCase()}
                          </span>
                        </td>
                        <td className="py-3 text-white">{t.company?.name || `Company #${t.company_id}`}</td>
                        <td className="py-3 text-right text-gray-300">{t.shares}</td>
                        <td className="py-3 text-right text-gray-300">{t.price_per_share.toFixed(2)}</td>
                        <td className="py-3 text-right text-gray-300">{formatCurrency(t.total_amount)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Delete Portfolio */}
          <div className="text-right">
            <button
              onClick={() => selectedPortfolio && deletePortfolio(selectedPortfolio.id)}
              className="text-red-400 hover:text-red-300 text-sm"
            >
              Delete Portfolio
            </button>
          </div>

          {/* Add Transaction Modal */}
          {showAddTransaction && (
            <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
              <div className="bg-dark-surface border border-dark-border rounded-xl p-6 w-full max-w-md">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-lg font-semibold text-white">Add Transaction</h3>
                  <button onClick={() => setShowAddTransaction(false)} className="text-gray-400 hover:text-white">
                    <X size={20} />
                  </button>
                </div>
                <form onSubmit={handleSubmit(onAddTransaction)} className="space-y-4">
                  <div>
                    <label className="block text-sm text-gray-300 mb-1">Company</label>
                    <select
                      {...register('company_id', { required: true })}
                      className="w-full px-4 py-2.5 bg-dark-bg border border-dark-border rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                    >
                      <option value="">Select company</option>
                      {companies.map((c) => (
                        <option key={c.id} value={c.id}>{c.name} ({c.ticker_symbol})</option>
                      ))}
                    </select>
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-sm text-gray-300 mb-1">Type</label>
                      <select
                        {...register('transaction_type')}
                        className="w-full px-4 py-2.5 bg-dark-bg border border-dark-border rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                      >
                        <option value="buy">Buy</option>
                        <option value="sell">Sell</option>
                      </select>
                    </div>
                    <div>
                      <label className="block text-sm text-gray-300 mb-1">Date</label>
                      <input
                        type="date"
                        {...register('transaction_date')}
                        className="w-full px-4 py-2.5 bg-dark-bg border border-dark-border rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                      />
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-sm text-gray-300 mb-1">Shares</label>
                      <input
                        type="number"
                        step="any"
                        {...register('shares', { required: true })}
                        className="w-full px-4 py-2.5 bg-dark-bg border border-dark-border rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                        placeholder="0"
                      />
                    </div>
                    <div>
                      <label className="block text-sm text-gray-300 mb-1">Price per Share</label>
                      <input
                        type="number"
                        step="any"
                        {...register('price_per_share', { required: true })}
                        className="w-full px-4 py-2.5 bg-dark-bg border border-dark-border rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                        placeholder="0.00"
                      />
                    </div>
                  </div>
                  <div>
                    <label className="block text-sm text-gray-300 mb-1">Notes (optional)</label>
                    <input
                      type="text"
                      {...register('notes')}
                      className="w-full px-4 py-2.5 bg-dark-bg border border-dark-border rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                      placeholder="Optional notes"
                    />
                  </div>
                  <div className="flex gap-3 justify-end">
                    <button type="button" onClick={() => setShowAddTransaction(false)} className="px-4 py-2 text-gray-400 hover:text-white">Cancel</button>
                    <button type="submit" className="px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg">Record</button>
                  </div>
                </form>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
