import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { Link } from 'react-router-dom';
import { Eye, Plus, Trash2, X } from 'lucide-react';
import toast from 'react-hot-toast';
import { watchlistsApi, stocksApi } from '../lib/services';
import type { Watchlist, Company } from '../types';
import { PageLoader } from '../components/ui/LoadingSpinner';

interface WatchlistForm {
  name: string;
  description: string;
}

interface AddItemForm {
  company_id: number;
  notes: string;
}

export default function WatchlistsPage() {
  const [watchlists, setWatchlists] = useState<Watchlist[]>([]);
  const [selectedWatchlist, setSelectedWatchlist] = useState<Watchlist | null>(null);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [showAddItem, setShowAddItem] = useState(false);

  const { register: regCreate, handleSubmit: handleCreate, reset: resetCreate } = useForm<WatchlistForm>();
  const { register: regItem, handleSubmit: handleAddItem, reset: resetItem } = useForm<AddItemForm>();

  useEffect(() => {
    loadWatchlists();
    stocksApi.getCompanies().then((res) => setCompanies(res.data)).catch(() => {});
  }, []);

  const loadWatchlists = async () => {
    try {
      const res = await watchlistsApi.list();
      setWatchlists(res.data);
      if (res.data.length > 0 && !selectedWatchlist) {
        loadWatchlistDetail(res.data[0]);
      }
    } catch {
      toast.error('Failed to load watchlists');
    } finally {
      setLoading(false);
    }
  };

  const loadWatchlistDetail = async (wl: Watchlist) => {
    try {
      const res = await watchlistsApi.get(wl.id);
      setSelectedWatchlist(res.data);
    } catch {
      setSelectedWatchlist(wl);
    }
  };

  const onCreate = async (data: WatchlistForm) => {
    try {
      const res = await watchlistsApi.create({ name: data.name, description: data.description || undefined });
      setWatchlists([...watchlists, res.data]);
      setShowCreate(false);
      resetCreate();
      loadWatchlistDetail(res.data);
      toast.success('Watchlist created');
    } catch {
      toast.error('Failed to create watchlist');
    }
  };

  const onAddItem = async (data: AddItemForm) => {
    if (!selectedWatchlist) return;
    try {
      await watchlistsApi.addItem(selectedWatchlist.id, {
        company_id: Number(data.company_id),
        notes: data.notes || undefined,
      });
      toast.success('Item added');
      setShowAddItem(false);
      resetItem();
      loadWatchlistDetail(selectedWatchlist);
    } catch {
      toast.error('Failed to add item');
    }
  };

  const removeItem = async (itemId: number) => {
    if (!selectedWatchlist) return;
    try {
      await watchlistsApi.removeItem(selectedWatchlist.id, itemId);
      setSelectedWatchlist({
        ...selectedWatchlist,
        items: selectedWatchlist.items?.filter((i) => i.id !== itemId),
      });
      toast.success('Item removed');
    } catch {
      toast.error('Failed to remove item');
    }
  };

  const deleteWatchlist = async (id: number) => {
    if (!confirm('Delete this watchlist?')) return;
    try {
      await watchlistsApi.delete(id);
      const remaining = watchlists.filter((w) => w.id !== id);
      setWatchlists(remaining);
      if (remaining.length > 0) loadWatchlistDetail(remaining[0]);
      else setSelectedWatchlist(null);
      toast.success('Watchlist deleted');
    } catch {
      toast.error('Failed to delete watchlist');
    }
  };

  if (loading) return <PageLoader />;

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-white">Watchlists</h1>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-2 px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg transition-colors"
        >
          <Plus size={16} />
          New Watchlist
        </button>
      </div>

      {/* Watchlist Tabs */}
      {watchlists.length > 0 && (
        <div className="flex gap-2 mb-6 overflow-x-auto pb-2">
          {watchlists.map((wl) => (
            <button
              key={wl.id}
              onClick={() => loadWatchlistDetail(wl)}
              className={`px-4 py-2 rounded-lg whitespace-nowrap text-sm font-medium transition-colors ${
                selectedWatchlist?.id === wl.id
                  ? 'bg-primary-600 text-white'
                  : 'bg-dark-surface text-gray-400 hover:text-white border border-dark-border'
              }`}
            >
              {wl.name}
            </button>
          ))}
        </div>
      )}

      {!selectedWatchlist ? (
        <div className="bg-dark-surface border border-dark-border rounded-xl p-12 text-center">
          <Eye className="mx-auto text-gray-600 mb-3" size={40} />
          <p className="text-gray-400">Create a watchlist to track stocks you're interested in.</p>
        </div>
      ) : (
        <div className="bg-dark-surface border border-dark-border rounded-xl p-6">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-lg font-semibold text-white">{selectedWatchlist.name}</h2>
              {selectedWatchlist.description && (
                <p className="text-sm text-gray-400">{selectedWatchlist.description}</p>
              )}
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => setShowAddItem(true)}
                className="flex items-center gap-1 px-3 py-1.5 bg-green-600 hover:bg-green-700 text-white text-sm rounded-lg"
              >
                <Plus size={14} /> Add Stock
              </button>
              <button
                onClick={() => deleteWatchlist(selectedWatchlist.id)}
                className="p-2 text-red-400 hover:text-red-300 hover:bg-dark-border rounded-lg"
              >
                <Trash2 size={16} />
              </button>
            </div>
          </div>

          {/* Items */}
          {(!selectedWatchlist.items || selectedWatchlist.items.length === 0) ? (
            <p className="text-gray-400 text-center py-8">No items in this watchlist. Add stocks to track them.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="text-left text-sm text-gray-400 border-b border-dark-border">
                    <th className="pb-3 font-medium">Company</th>
                    <th className="pb-3 font-medium">Symbol</th>
                    <th className="pb-3 font-medium">Notes</th>
                    <th className="pb-3 font-medium">Added</th>
                    <th className="pb-3 font-medium text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {selectedWatchlist.items.map((item) => (
                    <tr key={item.id} className="border-b border-dark-border/50">
                      <td className="py-3">
                        <Link
                          to={`/companies/${item.company_id}`}
                          className="text-white hover:text-primary-400 font-medium"
                        >
                          {item.company?.name || `Company #${item.company_id}`}
                        </Link>
                      </td>
                      <td className="py-3 text-gray-400 font-mono text-sm">
                        {item.company?.symbol || '—'}
                      </td>
                      <td className="py-3 text-gray-400 text-sm">{item.notes || '—'}</td>
                      <td className="py-3 text-gray-500 text-sm">
                        {new Date(item.added_at).toLocaleDateString()}
                      </td>
                      <td className="py-3 text-right">
                        <button
                          onClick={() => removeItem(item.id)}
                          className="p-1 text-gray-400 hover:text-red-400"
                        >
                          <Trash2 size={14} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Create Watchlist Modal */}
      {showCreate && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-dark-surface border border-dark-border rounded-xl p-6 w-full max-w-md">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-white">Create Watchlist</h3>
              <button onClick={() => setShowCreate(false)} className="text-gray-400 hover:text-white">
                <X size={20} />
              </button>
            </div>
            <form onSubmit={handleCreate(onCreate)} className="space-y-4">
              <div>
                <label className="block text-sm text-gray-300 mb-1">Name</label>
                <input
                  type="text"
                  {...regCreate('name', { required: true })}
                  className="w-full px-4 py-2.5 bg-dark-bg border border-dark-border rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                  placeholder="My Watchlist"
                />
              </div>
              <div>
                <label className="block text-sm text-gray-300 mb-1">Description (optional)</label>
                <input
                  type="text"
                  {...regCreate('description')}
                  className="w-full px-4 py-2.5 bg-dark-bg border border-dark-border rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                  placeholder="Optional description"
                />
              </div>
              <div className="flex gap-3 justify-end">
                <button type="button" onClick={() => setShowCreate(false)} className="px-4 py-2 text-gray-400 hover:text-white">Cancel</button>
                <button type="submit" className="px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg">Create</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Add Item Modal */}
      {showAddItem && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-dark-surface border border-dark-border rounded-xl p-6 w-full max-w-md">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-white">Add Stock to Watchlist</h3>
              <button onClick={() => setShowAddItem(false)} className="text-gray-400 hover:text-white">
                <X size={20} />
              </button>
            </div>
            <form onSubmit={handleAddItem(onAddItem)} className="space-y-4">
              <div>
                <label className="block text-sm text-gray-300 mb-1">Company</label>
                <select
                  {...regItem('company_id', { required: true })}
                  className="w-full px-4 py-2.5 bg-dark-bg border border-dark-border rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                >
                  <option value="">Select company</option>
                  {companies.map((c) => (
                    <option key={c.id} value={c.id}>{c.name} ({c.symbol})</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm text-gray-300 mb-1">Notes (optional)</label>
                <input
                  type="text"
                  {...regItem('notes')}
                  className="w-full px-4 py-2.5 bg-dark-bg border border-dark-border rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                  placeholder="Why you're watching this stock"
                />
              </div>
              <div className="flex gap-3 justify-end">
                <button type="button" onClick={() => setShowAddItem(false)} className="px-4 py-2 text-gray-400 hover:text-white">Cancel</button>
                <button type="submit" className="px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg">Add</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
