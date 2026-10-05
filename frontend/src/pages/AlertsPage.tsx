import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { Bell, Mail, Plus, Trash2, Check, X } from 'lucide-react';
import toast from 'react-hot-toast';
import { alertsApi, notificationsApi, stocksApi } from '../lib/services';
import type { Alert, Company, Notification, NotificationPreferences } from '../types';
import { PageLoader } from '../components/ui/LoadingSpinner';

interface AlertForm {
  company_id: number;
  alert_type: string;
  threshold: number;
  message: string;
}

export default function AlertsPage() {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [unreadNotifications, setUnreadNotifications] = useState(0);
  const [preferences, setPreferences] = useState<NotificationPreferences | null>(null);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const { register, handleSubmit, reset } = useForm<AlertForm>();

  useEffect(() => {
    loadAlerts();
    loadNotifications();
    stocksApi.getCompanies().then((res) => setCompanies(res.data)).catch(() => {});
  }, []);

  const loadNotifications = async () => {
    try {
      const [inbox, prefs] = await Promise.all([
        notificationsApi.list(),
        notificationsApi.getPreferences(),
      ]);
      setNotifications(inbox.data.notifications);
      setUnreadNotifications(inbox.data.unread_count);
      setPreferences(prefs.data);
    } catch {
      toast.error('Failed to load notifications');
    }
  };

  const loadAlerts = async () => {
    try {
      const res = await alertsApi.list();
      setAlerts(res.data);
    } catch {
      toast.error('Failed to load alerts');
    } finally {
      setLoading(false);
    }
  };

  const onCreate = async (data: AlertForm) => {
    try {
      await alertsApi.create({
        company_id: Number(data.company_id),
        alert_type: data.alert_type,
        condition: `${data.alert_type}_${data.threshold}`,
        threshold_value: Number(data.threshold),
      });
      toast.success('Alert created');
      setShowCreate(false);
      reset();
      loadAlerts();
    } catch {
      toast.error('Failed to create alert');
    }
  };

  const markRead = async (id: number) => {
    try {
      await alertsApi.markRead(id);
      setAlerts(alerts.map((a) => a.id === id ? { ...a, is_read: true } : a));
    } catch {
      toast.error('Failed to mark alert');
    }
  };

  const deleteAlert = async (id: number) => {
    try {
      await alertsApi.delete(id);
      setAlerts(alerts.filter((a) => a.id !== id));
      toast.success('Alert deleted');
    } catch {
      toast.error('Failed to delete alert');
    }
  };

  const markNotificationRead = async (id: number) => {
    try {
      const response = await notificationsApi.markRead(id);
      setNotifications(notifications.map((n) => n.id === id ? response.data : n));
      setUnreadNotifications((count) => Math.max(0, count - 1));
    } catch {
      toast.error('Failed to mark notification as read');
    }
  };

  const markAllNotificationsRead = async () => {
    try {
      await notificationsApi.markAllRead();
      setNotifications(notifications.map((n) => ({ ...n, read_at: n.read_at || new Date().toISOString() })));
      setUnreadNotifications(0);
    } catch {
      toast.error('Failed to mark notifications as read');
    }
  };

  const updatePreferences = async (patch: Partial<NotificationPreferences>) => {
    if (!preferences) return;
    try {
      const response = await notificationsApi.updatePreferences(patch);
      setPreferences(response.data);
      toast.success('Notification preferences saved');
    } catch {
      toast.error('Failed to update notification preferences');
    }
  };

  if (loading) return <PageLoader />;

  const unreadAlerts = alerts.filter((a) => a.is_triggered && !a.is_read);
  const activeAlerts = alerts.filter((a) => !a.is_triggered);
  const readAlerts = alerts.filter((a) => a.is_read);

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-white">Alerts</h1>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-2 px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg transition-colors"
        >
          <Plus size={16} />
          Create Alert
        </button>
      </div>

      {/* Notification inbox ------------------------------------------------ */}
      <section className="bg-dark-surface border border-dark-border rounded-xl p-6 mb-6">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <div className="flex items-center gap-2">
            <Bell className="text-primary-400" size={19} />
            <h2 className="text-lg font-semibold text-white">Notification Inbox</h2>
            {unreadNotifications > 0 && (
              <span className="px-2 py-0.5 rounded-full bg-primary-500/20 text-primary-300 text-xs">
                {unreadNotifications} unread
              </span>
            )}
          </div>
          {unreadNotifications > 0 && (
            <button onClick={markAllNotificationsRead} className="text-sm text-primary-400 hover:text-primary-300">
              Mark all read
            </button>
          )}
        </div>
        {notifications.length === 0 ? (
          <p className="text-sm text-gray-400">Triggered alerts will appear here and can also be sent to your signup email.</p>
        ) : (
          <div className="space-y-2 max-h-96 overflow-y-auto pr-1">
            {notifications.map((notification) => (
              <div
                key={notification.id}
                className={`rounded-lg border p-3 ${notification.read_at ? 'border-dark-border bg-dark-bg/50 opacity-70' : 'border-primary-500/40 bg-primary-500/5'}`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-medium text-white">{notification.title}</p>
                    <p className="text-sm text-gray-300 mt-1">{notification.body}</p>
                    <p className="text-xs text-gray-500 mt-2">
                      {new Date(notification.created_at).toLocaleString()} · email {notification.email_status.replace('_', ' ')}
                    </p>
                  </div>
                  {!notification.read_at && (
                    <button onClick={() => markNotificationRead(notification.id)} className="p-1 text-primary-300 hover:text-white" title="Mark as read">
                      <Check size={16} />
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Email preferences ------------------------------------------------- */}
      {preferences && (
        <section className="bg-dark-surface border border-dark-border rounded-xl p-6 mb-6">
          <div className="flex items-center gap-2 mb-2">
            <Mail className="text-primary-400" size={19} />
            <h2 className="text-lg font-semibold text-white">Email Notifications</h2>
          </div>
          <p className="text-sm text-gray-400 mb-4">Emails are sent only to the address used to sign in to StockUp.</p>
          <div className="grid md:grid-cols-2 gap-4 text-sm">
            <label className="flex items-center justify-between gap-3 text-gray-200">
              Email delivery
              <input type="checkbox" checked={preferences.email_enabled} onChange={(e) => updatePreferences({ email_enabled: e.target.checked })} />
            </label>
            <label className="flex items-center justify-between gap-3 text-gray-200">
              Delivery frequency
              <select
                value={preferences.email_frequency}
                onChange={(e) => updatePreferences({ email_frequency: e.target.value as NotificationPreferences['email_frequency'] })}
                className="bg-dark-bg border border-dark-border rounded px-2 py-1 text-white"
              >
                <option value="immediate">Immediate</option>
                <option value="daily_digest">Daily digest</option>
                <option value="off">Off</option>
              </select>
            </label>
            <label className="flex items-center gap-2 text-gray-300">
              <input type="checkbox" checked={preferences.price_alerts_enabled} onChange={(e) => updatePreferences({ price_alerts_enabled: e.target.checked })} />
              Price-target alerts
            </label>
            <label className="flex items-center gap-2 text-gray-300">
              <input type="checkbox" checked={preferences.valuation_alerts_enabled} onChange={(e) => updatePreferences({ valuation_alerts_enabled: e.target.checked })} />
              Margin-of-safety alerts
            </label>
            <label className="flex items-center gap-2 text-gray-300">
              <input type="checkbox" checked={preferences.opportunity_alerts_enabled} onChange={(e) => updatePreferences({ opportunity_alerts_enabled: e.target.checked })} />
              Unowned Strong Buy opportunities (MOS ≥ 20%)
            </label>
          </div>
        </section>
      )}

      {/* Triggered / Unread Alerts */}
      {unreadAlerts.length > 0 && (
        <div className="mb-6">
          <h2 className="text-lg font-semibold text-white mb-3 flex items-center gap-2">
            <Bell className="text-yellow-400" size={18} />
            Triggered Alerts ({unreadAlerts.length})
          </h2>
          <div className="space-y-2">
            {unreadAlerts.map((alert) => (
              <div key={alert.id} className="bg-yellow-900/20 border border-yellow-700/50 rounded-xl p-4 flex items-center justify-between">
                <div>
                  <p className="text-white font-medium">{alert.company?.name || `Company #${alert.company_id}`}</p>
                  <p className="text-sm text-yellow-300">
                    {alert.alert_type.replace('_', ' ')} at {alert.threshold_value}
                    {alert.message && ` — ${alert.message}`}
                  </p>
                  {alert.triggered_at && (
                    <p className="text-xs text-gray-400 mt-1">Triggered: {new Date(alert.triggered_at).toLocaleString()}</p>
                  )}
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => markRead(alert.id)}
                    className="p-2 hover:bg-dark-border rounded-lg text-green-400 hover:text-green-300"
                    title="Mark as read"
                  >
                    <Check size={16} />
                  </button>
                  <button
                    onClick={() => deleteAlert(alert.id)}
                    className="p-2 hover:bg-dark-border rounded-lg text-red-400 hover:text-red-300"
                    title="Delete"
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Active Alerts */}
      <div className="bg-dark-surface border border-dark-border rounded-xl p-6 mb-6">
        <h2 className="text-lg font-semibold text-white mb-4">Active Alerts ({activeAlerts.length})</h2>
        {activeAlerts.length === 0 ? (
          <p className="text-gray-400 text-center py-4">No active alerts. Create one to get notified.</p>
        ) : (
          <div className="space-y-3">
            {activeAlerts.map((alert) => (
              <div key={alert.id} className="flex items-center justify-between p-3 bg-dark-bg rounded-lg">
                <div>
                  <p className="text-white">{alert.company?.name || `Company #${alert.company_id}`}</p>
                  <p className="text-sm text-gray-400">
                    {alert.alert_type.replace('_', ' ')} • threshold: {alert.threshold_value}
                  </p>
                </div>
                <button
                  onClick={() => deleteAlert(alert.id)}
                  className="p-2 hover:bg-dark-border rounded-lg text-gray-400 hover:text-red-400"
                >
                  <Trash2 size={16} />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Read/Dismissed Alerts */}
      {readAlerts.length > 0 && (
        <div className="bg-dark-surface border border-dark-border rounded-xl p-6">
          <h2 className="text-lg font-semibold text-gray-400 mb-4">Dismissed ({readAlerts.length})</h2>
          <div className="space-y-2">
            {readAlerts.slice(0, 10).map((alert) => (
              <div key={alert.id} className="flex items-center justify-between p-3 bg-dark-bg/50 rounded-lg opacity-60">
                <div>
                  <p className="text-gray-300">{alert.company?.name || `Company #${alert.company_id}`}</p>
                  <p className="text-xs text-gray-500">
                    {alert.alert_type.replace('_', ' ')} at {alert.threshold_value}
                  </p>
                </div>
                <button onClick={() => deleteAlert(alert.id)} className="p-2 text-gray-500 hover:text-red-400">
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Create Alert Modal */}
      {showCreate && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-dark-surface border border-dark-border rounded-xl p-6 w-full max-w-md">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-white">Create Alert</h3>
              <button onClick={() => setShowCreate(false)} className="text-gray-400 hover:text-white">
                <X size={20} />
              </button>
            </div>
            <form onSubmit={handleSubmit(onCreate)} className="space-y-4">
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
              <div>
                <label className="block text-sm text-gray-300 mb-1">Alert Type</label>
                <select
                  {...register('alert_type', { required: true })}
                  className="w-full px-4 py-2.5 bg-dark-bg border border-dark-border rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                >
                  <option value="price_above">Price Above</option>
                  <option value="price_below">Price Below</option>
                  <option value="margin_of_safety">Margin of Safety</option>
                </select>
              </div>
              <div>
                <label className="block text-sm text-gray-300 mb-1">Threshold</label>
                <input
                  type="number"
                  step="any"
                  {...register('threshold', { required: true })}
                  className="w-full px-4 py-2.5 bg-dark-bg border border-dark-border rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                  placeholder="0.00"
                />
              </div>
              <div className="flex gap-3 justify-end">
                <button type="button" onClick={() => setShowCreate(false)} className="px-4 py-2 text-gray-400 hover:text-white">Cancel</button>
                <button type="submit" className="px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg">Create Alert</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
