import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useForm } from 'react-hook-form';
import { Plus, Briefcase, TrendingUp, TrendingDown, X, Pencil, Trash2 } from 'lucide-react';
import toast from 'react-hot-toast';
import { portfolioApi, stocksApi } from '../lib/services';
import type { Portfolio, Holding, HoldingsListResponse, Transaction, PortfolioPerformance, Company } from '../types';
import { SkeletonCard, PageLoader } from '../components/ui/LoadingSpinner';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

interface TransactionForm {
  company_id: number;
  transaction_type: 'buy' | 'sell';
  shares: number;
  price_per_share: number;
  fees: number;
  transaction_date: string;
  notes: string;
}

interface EditTransactionForm {
  transaction_type: 'buy' | 'sell';
  quantity: number;
  price_per_share: number;
  fees: number;
  transaction_date: string;
  notes: string;
}

// NSE Kenya standard trading charges (% of gross consideration).
// Brokerage commission is broker-specific (NCBA = 1.76%) and editable.
const NSE_STATUTORY_RATE = 0.0008 + 0.0012 + 0.0001 + 0.0012 + 0.0001 + 0.0005; // 0.39%
const DEFAULT_BROKERAGE_RATE = 0.0176; // 1.76%

function computeNseCharges(gross: number, brokerageRate: number): number {
  if (!gross || gross <= 0) return 0;
  const total = gross * (brokerageRate + NSE_STATUTORY_RATE);
  return Math.round(total * 100) / 100;
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
  const [editingTransaction, setEditingTransaction] = useState<Transaction | null>(null);

  const { register, handleSubmit, reset, setValue, watch } = useForm<TransactionForm>({
    defaultValues: { transaction_type: 'buy', transaction_date: new Date().toISOString().split('T')[0], fees: 0 },
  });
  const { register: registerEdit, handleSubmit: handleEditSubmit, reset: resetEdit, setValue: setEditValue, watch: watchEdit } = useForm<EditTransactionForm>();
  const [companySearch, setCompanySearch] = useState('');
  const [companyDropdownOpen, setCompanyDropdownOpen] = useState(false);
  const [selectedCompanyLabel, setSelectedCompanyLabel] = useState('');
  const [brokerageRate, setBrokerageRate] = useState(DEFAULT_BROKERAGE_RATE * 100); // shown as %
  const [editBrokerageRate, setEditBrokerageRate] = useState(DEFAULT_BROKERAGE_RATE * 100);

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
      setHoldings(holdingsRes.data.holdings);
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
        company_id: Number(data.company_id),
        transaction_type: data.transaction_type,
        quantity: Number(data.shares),
        price_per_share: Number(data.price_per_share),
        fees: Number(data.fees) || 0,
        transaction_date: data.transaction_date,
        notes: data.notes || undefined,
      });
      toast.success('Transaction recorded');
      setShowAddTransaction(false);
      reset();
      setSelectedCompanyLabel('');
      setCompanySearch('');
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

  const deleteTransaction = async (transactionId: number) => {
    if (!selectedPortfolio) return;
    if (!confirm('Delete this transaction? This will affect your holdings.')) return;
    try {
      await portfolioApi.deleteTransaction(selectedPortfolio.id, transactionId);
      toast.success('Transaction deleted');
      selectPortfolio(selectedPortfolio);
    } catch {
      toast.error('Failed to delete transaction');
    }
  };

  const openEditTransaction = (t: Transaction) => {
    setEditingTransaction(t);
    resetEdit({
      transaction_type: t.transaction_type as 'buy' | 'sell',
      quantity: t.quantity,
      price_per_share: t.price_per_share,
      fees: t.fees ?? 0,
      transaction_date: t.transaction_date,
      notes: t.notes || '',
    });
  };

  const onEditTransaction = async (data: EditTransactionForm) => {
    if (!selectedPortfolio || !editingTransaction) return;
    try {
      await portfolioApi.updateTransaction(selectedPortfolio.id, editingTransaction.id, {
        transaction_type: data.transaction_type,
        quantity: Number(data.quantity),
        price_per_share: Number(data.price_per_share),
        fees: Number(data.fees) || 0,
        transaction_date: data.transaction_date,
        notes: data.notes || undefined,
      });
      toast.success('Transaction updated');
      setEditingTransaction(null);
      selectPortfolio(selectedPortfolio);
    } catch {
      toast.error('Failed to update transaction');
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
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4 mb-6">
              <div className="bg-dark-surface border border-dark-border rounded-xl p-4">
                <p className="text-sm text-gray-400">Cost of Shares</p>
                <p className="text-xl font-bold text-white">{formatCurrency(performance.total_invested)}</p>
              </div>
              <div className="bg-dark-surface border border-dark-border rounded-xl p-4">
                <p className="text-sm text-gray-400">Total Charges</p>
                <p className="text-xl font-bold text-white">{formatCurrency(performance.total_fees_paid ?? 0)}</p>
              </div>
              <div className="bg-dark-surface border border-dark-border rounded-xl p-4">
                <p className="text-sm text-gray-400">Net Cost</p>
                <p className="text-xl font-bold text-white">
                  {formatCurrency((performance.total_invested ?? 0) + (performance.total_fees_paid ?? 0))}
                </p>
              </div>
              <div className="bg-dark-surface border border-dark-border rounded-xl p-4">
                <p className="text-sm text-gray-400">Current Value</p>
                <p className="text-xl font-bold text-white">{formatCurrency(performance.total_current_value ?? 0)}</p>
              </div>
              <div className="bg-dark-surface border border-dark-border rounded-xl p-4">
                <p className="text-sm text-gray-400">Total Gain</p>
                <p className={`text-xl font-bold ${(performance.total_pnl ?? 0) >= 0 ? 'text-gain' : 'text-loss'}`}>
                  {formatCurrency(performance.total_pnl ?? 0)}
                </p>
              </div>
              <div className="bg-dark-surface border border-dark-border rounded-xl p-4">
                <p className="text-sm text-gray-400">Return %</p>
                <p className={`text-xl font-bold ${(performance.total_return_pct ?? 0) >= 0 ? 'text-gain' : 'text-loss'}`}>
                  {(performance.total_return_pct ?? 0) >= 0 ? '+' : ''}{(performance.total_return_pct ?? 0).toFixed(2)}%
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
                            <Link to={`/companies/${h.company_id}`} className="hover:text-primary-400 transition-colors">
                              <p className="text-white font-medium">{h.company_name}</p>
                              <p className="text-xs text-gray-500">{h.company_ticker}</p>
                            </Link>
                          </td>
                          <td className="py-3 text-right text-gray-300">{h.total_shares}</td>
                          <td className="py-3 text-right text-gray-300">{h.average_cost_basis.toFixed(2)}</td>
                          <td className="py-3 text-right text-gray-300">{h.current_price?.toFixed(2) ?? '—'}</td>
                          <td className="py-3 text-right">
                            {h.unrealized_pnl_pct !== null ? (
                              <span className={(h.unrealized_pnl_pct ?? 0) >= 0 ? 'text-gain' : 'text-loss'}>
                                {(h.unrealized_pnl_pct ?? 0) >= 0 ? '+' : ''}{h.unrealized_pnl_pct?.toFixed(2)}%
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
                    <BarChart data={holdings.map((h) => ({ name: h.company_ticker, value: h.current_value || h.total_cost }))}>
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
                      <th className="pb-3 font-medium text-right">Gross</th>
                      <th className="pb-3 font-medium text-right">Charges</th>
                      <th className="pb-3 font-medium text-right">Net</th>
                      <th className="pb-3 font-medium text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {transactions.map((t) => {
                      const fees = t.fees ?? 0;
                      const net = t.transaction_type === 'buy' ? t.total_amount + fees : t.total_amount - fees;
                      return (
                        <tr key={t.id} className="border-b border-dark-border/50 group">
                          <td className="py-3 text-gray-300">{t.transaction_date}</td>
                          <td className="py-3">
                            <span className={`flex items-center gap-1 ${t.transaction_type === 'buy' ? 'text-gain' : 'text-loss'}`}>
                              {t.transaction_type === 'buy' ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
                              {t.transaction_type.toUpperCase()}
                            </span>
                          </td>
                          <td className="py-3">
                            <Link to={`/companies/${t.company_id}`} className="text-white hover:text-primary-400 transition-colors">
                              {t.company_name || t.company_ticker || `Company #${t.company_id}`}
                            </Link>
                          </td>
                          <td className="py-3 text-right text-gray-300">{t.quantity}</td>
                          <td className="py-3 text-right text-gray-300">{t.price_per_share.toFixed(2)}</td>
                          <td className="py-3 text-right text-gray-300">{formatCurrency(t.total_amount)}</td>
                          <td className="py-3 text-right text-gray-400">{fees > 0 ? formatCurrency(fees) : '—'}</td>
                          <td className="py-3 text-right text-white font-medium">{formatCurrency(net)}</td>
                          <td className="py-3 text-right">
                            <div className="flex items-center justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                              <button
                                onClick={() => openEditTransaction(t)}
                                className="p-1.5 text-gray-400 hover:text-primary-400 hover:bg-dark-border/50 rounded-md transition-colors"
                                title="Edit transaction"
                              >
                                <Pencil size={14} />
                              </button>
                              <button
                                onClick={() => deleteTransaction(t.id)}
                                className="p-1.5 text-gray-400 hover:text-red-400 hover:bg-dark-border/50 rounded-md transition-colors"
                                title="Delete transaction"
                              >
                                <Trash2 size={14} />
                              </button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
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
                  <div className="relative">
                    <label className="block text-sm text-gray-300 mb-1">Company</label>
                    <input type="hidden" {...register('company_id', { required: true })} />
                    <input
                      type="text"
                      value={companyDropdownOpen ? companySearch : selectedCompanyLabel}
                      onChange={(e) => {
                        setCompanySearch(e.target.value);
                        setCompanyDropdownOpen(true);
                      }}
                      onFocus={() => {
                        setCompanyDropdownOpen(true);
                        setCompanySearch('');
                      }}
                      placeholder="Type to search companies..."
                      className="w-full px-4 py-2.5 bg-dark-bg border border-dark-border rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-primary-500"
                      autoComplete="off"
                    />
                    {companyDropdownOpen && (
                      <div className="absolute z-50 w-full mt-1 max-h-48 overflow-y-auto bg-dark-bg border border-dark-border rounded-lg shadow-lg">
                        {companies
                          .filter((c) => {
                            const q = companySearch.toLowerCase();
                            return c.name.toLowerCase().includes(q) || c.ticker_symbol.toLowerCase().includes(q);
                          })
                          .slice(0, 20)
                          .map((c) => (
                            <button
                              key={c.id}
                              type="button"
                              onClick={() => {
                                setValue('company_id', c.id);
                                setSelectedCompanyLabel(`${c.name} (${c.ticker_symbol})`);
                                setCompanySearch('');
                                setCompanyDropdownOpen(false);
                              }}
                              className="w-full text-left px-4 py-2 text-sm text-gray-300 hover:bg-dark-border/50 hover:text-white transition-colors"
                            >
                              <span className="font-medium text-white">{c.ticker_symbol}</span>
                              <span className="ml-2 text-gray-400">{c.name}</span>
                            </button>
                          ))}
                        {companies.filter((c) => {
                          const q = companySearch.toLowerCase();
                          return c.name.toLowerCase().includes(q) || c.ticker_symbol.toLowerCase().includes(q);
                        }).length === 0 && (
                          <p className="px-4 py-2 text-sm text-gray-500">No companies found</p>
                        )}
                      </div>
                    )}
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
                    <div className="flex items-center justify-between mb-1">
                      <label className="text-sm text-gray-300">Charges / Fees</label>
                      <div className="flex items-center gap-2">
                        <input
                          type="number"
                          step="0.01"
                          value={brokerageRate}
                          onChange={(e) => setBrokerageRate(Number(e.target.value))}
                          className="w-16 px-2 py-1 bg-dark-bg border border-dark-border rounded text-xs text-white text-right"
                          title="Brokerage commission %"
                        />
                        <span className="text-xs text-gray-500">% broker</span>
                        <button
                          type="button"
                          onClick={() => {
                            const gross = Number(watch('shares') || 0) * Number(watch('price_per_share') || 0);
                            setValue('fees', computeNseCharges(gross, brokerageRate / 100));
                          }}
                          className="px-2 py-1 text-xs bg-dark-bg border border-dark-border text-primary-400 hover:text-primary-300 rounded"
                        >
                          Auto NSE
                        </button>
                      </div>
                    </div>
                    <input
                      type="number"
                      step="0.01"
                      {...register('fees')}
                      className="w-full px-4 py-2.5 bg-dark-bg border border-dark-border rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                      placeholder="0.00"
                    />
                    {(() => {
                      const gross = Number(watch('shares') || 0) * Number(watch('price_per_share') || 0);
                      const fees = Number(watch('fees') || 0);
                      const isBuy = watch('transaction_type') === 'buy';
                      const net = isBuy ? gross + fees : gross - fees;
                      if (gross <= 0) return null;
                      return (
                        <div className="mt-2 text-xs text-gray-400 flex justify-between">
                          <span>Gross: <span className="text-gray-200">{formatCurrency(gross)}</span></span>
                          <span>Charges: <span className="text-gray-200">{formatCurrency(fees)}</span></span>
                          <span>{isBuy ? 'Net payable' : 'Net received'}: <span className="text-white font-semibold">{formatCurrency(net)}</span></span>
                        </div>
                      );
                    })()}
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

          {/* Edit Transaction Modal */}
          {editingTransaction && (
            <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
              <div className="bg-dark-surface border border-dark-border rounded-xl p-6 w-full max-w-md">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-lg font-semibold text-white">Edit Transaction</h3>
                  <button onClick={() => setEditingTransaction(null)} className="text-gray-400 hover:text-white">
                    <X size={20} />
                  </button>
                </div>
                <p className="text-sm text-gray-400 mb-4">
                  {editingTransaction.company_name || editingTransaction.company_ticker || `Company #${editingTransaction.company_id}`}
                </p>
                <form onSubmit={handleEditSubmit(onEditTransaction)} className="space-y-4">
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-sm text-gray-300 mb-1">Type</label>
                      <select
                        {...registerEdit('transaction_type')}
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
                        {...registerEdit('transaction_date')}
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
                        {...registerEdit('quantity', { required: true })}
                        className="w-full px-4 py-2.5 bg-dark-bg border border-dark-border rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                      />
                    </div>
                    <div>
                      <label className="block text-sm text-gray-300 mb-1">Price per Share</label>
                      <input
                        type="number"
                        step="any"
                        {...registerEdit('price_per_share', { required: true })}
                        className="w-full px-4 py-2.5 bg-dark-bg border border-dark-border rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                      />
                    </div>
                  </div>
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <label className="text-sm text-gray-300">Charges / Fees</label>
                      <div className="flex items-center gap-2">
                        <input
                          type="number"
                          step="0.01"
                          value={editBrokerageRate}
                          onChange={(e) => setEditBrokerageRate(Number(e.target.value))}
                          className="w-16 px-2 py-1 bg-dark-bg border border-dark-border rounded text-xs text-white text-right"
                          title="Brokerage commission %"
                        />
                        <span className="text-xs text-gray-500">% broker</span>
                        <button
                          type="button"
                          onClick={() => {
                            const gross = Number(watchEdit('quantity') || 0) * Number(watchEdit('price_per_share') || 0);
                            setEditValue('fees', computeNseCharges(gross, editBrokerageRate / 100));
                          }}
                          className="px-2 py-1 text-xs bg-dark-bg border border-dark-border text-primary-400 hover:text-primary-300 rounded"
                        >
                          Auto NSE
                        </button>
                      </div>
                    </div>
                    <input
                      type="number"
                      step="0.01"
                      {...registerEdit('fees')}
                      className="w-full px-4 py-2.5 bg-dark-bg border border-dark-border rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                      placeholder="0.00"
                    />
                    {(() => {
                      const gross = Number(watchEdit('quantity') || 0) * Number(watchEdit('price_per_share') || 0);
                      const fees = Number(watchEdit('fees') || 0);
                      const isBuy = watchEdit('transaction_type') === 'buy';
                      const net = isBuy ? gross + fees : gross - fees;
                      if (gross <= 0) return null;
                      return (
                        <div className="mt-2 text-xs text-gray-400 flex justify-between">
                          <span>Gross: <span className="text-gray-200">{formatCurrency(gross)}</span></span>
                          <span>Charges: <span className="text-gray-200">{formatCurrency(fees)}</span></span>
                          <span>{isBuy ? 'Net payable' : 'Net received'}: <span className="text-white font-semibold">{formatCurrency(net)}</span></span>
                        </div>
                      );
                    })()}
                  </div>
                  <div>
                    <label className="block text-sm text-gray-300 mb-1">Notes (optional)</label>
                    <input
                      type="text"
                      {...registerEdit('notes')}
                      className="w-full px-4 py-2.5 bg-dark-bg border border-dark-border rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                      placeholder="Optional notes"
                    />
                  </div>
                  <div className="flex gap-3 justify-end">
                    <button type="button" onClick={() => setEditingTransaction(null)} className="px-4 py-2 text-gray-400 hover:text-white">Cancel</button>
                    <button type="submit" className="px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg">Save Changes</button>
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
