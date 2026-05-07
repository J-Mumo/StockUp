import api from './api';
import type {
  AuthResponse,
  Market,
  Company,
  PriceHistory,
  FinancialStatement,
  IntrinsicValue,
  Recommendation,
  Portfolio,
  Transaction,
  Holding,
  HoldingsListResponse,
  PortfolioPerformance,
  Alert,
  Watchlist,
  WatchlistItem,
  DashboardSummary,
  AnalysisSnapshot,
  ValuationTrendPoint,
} from '../types';

// Auth
export const authApi = {
  login: (email: string, password: string) =>
    api.post<AuthResponse>('/auth/login', new URLSearchParams({ username: email, password }), {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    }),
  register: (email: string, password: string, full_name: string) =>
    api.post('/auth/register', { email, password, full_name }),
};

// Stocks
export const stocksApi = {
  getMarkets: () => api.get<Market[]>('/stocks/markets'),
  getCompanies: (params?: { search?: string; sector?: string }) =>
    api.get<Company[]>('/stocks/companies', { params }),
  getSectors: () => api.get<string[]>('/stocks/companies/sectors'),
  getCompany: (id: number) => api.get<Company>(`/stocks/companies/${id}`),
  getPrices: (id: number) => api.get<PriceHistory[]>(`/stocks/companies/${id}/prices`),
  getFinancials: (id: number) => api.get<FinancialStatement[]>(`/stocks/companies/${id}/financials`),
  createFinancial: (id: number, data: Partial<FinancialStatement>) =>
    api.post<FinancialStatement>(`/stocks/companies/${id}/financials`, data),
  updateFinancial: (companyId: number, financialId: number, data: Partial<FinancialStatement>) =>
    api.put<FinancialStatement>(`/stocks/companies/${companyId}/financials/${financialId}`, data),
  deleteFinancial: (companyId: number, financialId: number) =>
    api.delete(`/stocks/companies/${companyId}/financials/${financialId}`),
  getValuationTrend: (id: number, days?: number) =>
    api.get<ValuationTrendPoint[]>(`/stocks/companies/${id}/valuation-trend`, { params: { days } }),
};

// Analysis
export const analysisApi = {
  computeValuation: (companyId: number) =>
    api.post<IntrinsicValue>(`/analysis/companies/${companyId}/compute`),
  getRecommendation: (companyId: number) =>
    api.get<Recommendation>(`/analysis/companies/${companyId}/recommendation`),
  getValuations: (companyId: number) =>
    api.get<IntrinsicValue[]>(`/stocks/companies/${companyId}/valuations`),
  getLatestValuation: (companyId: number) =>
    api.get<IntrinsicValue>(`/stocks/companies/${companyId}/valuations/latest`),
  getSnapshots: () => api.get<AnalysisSnapshot[]>('/analysis/snapshots'),
  createSnapshot: (data: { company_id: number; notes?: string }) =>
    api.post<AnalysisSnapshot>('/analysis/snapshots', data),
};

// Portfolio
export const portfolioApi = {
  list: () => api.get<Portfolio[]>('/portfolio'),
  create: (data: { name: string; description?: string }) =>
    api.post<Portfolio>('/portfolio', data),
  get: (id: number) => api.get<Portfolio>(`/portfolio/${id}`),
  update: (id: number, data: { name?: string; description?: string }) =>
    api.put<Portfolio>(`/portfolio/${id}`, data),
  delete: (id: number) => api.delete(`/portfolio/${id}`),
  getTransactions: (id: number) => api.get<Transaction[]>(`/portfolio/${id}/transactions`),
  createTransaction: (id: number, data: {
    company_id: number;
    transaction_type: 'buy' | 'sell';
    shares: number;
    price_per_share: number;
    transaction_date: string;
    notes?: string;
  }) => api.post<Transaction>(`/portfolio/${id}/transactions`, data),
  getHoldings: (id: number) => api.get<HoldingsListResponse>(`/portfolio/${id}/holdings`),
  getPerformance: (id: number) => api.get<PortfolioPerformance>(`/portfolio/${id}/performance`),
};

// Alerts
export const alertsApi = {
  list: () => api.get<Alert[]>('/alerts'),
  create: (data: {
    company_id: number;
    alert_type: string;
    threshold: number;
    message?: string;
  }) => api.post<Alert>('/alerts', data),
  update: (id: number, data: Partial<Alert>) =>
    api.put<Alert>(`/alerts/${id}`, data),
  delete: (id: number) => api.delete(`/alerts/${id}`),
  markRead: (id: number) => api.post(`/alerts/${id}/mark-read`),
};

// Watchlists
export const watchlistsApi = {
  list: () => api.get<Watchlist[]>('/watchlists'),
  create: (data: { name: string; description?: string }) =>
    api.post<Watchlist>('/watchlists', data),
  get: (id: number) => api.get<Watchlist>(`/watchlists/${id}`),
  delete: (id: number) => api.delete(`/watchlists/${id}`),
  addItem: (watchlistId: number, data: { company_id: number; notes?: string }) =>
    api.post<WatchlistItem>(`/watchlists/${watchlistId}/items`, data),
  updateItem: (watchlistId: number, itemId: number, data: { notes?: string }) =>
    api.put<WatchlistItem>(`/watchlists/${watchlistId}/items/${itemId}`, data),
  removeItem: (watchlistId: number, itemId: number) =>
    api.delete(`/watchlists/${watchlistId}/items/${itemId}`),
};

// Dashboard
export const dashboardApi = {
  getSummary: () => api.get<DashboardSummary>('/dashboard'),
};
