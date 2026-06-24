import api from './api';
import type {
  AuthResponse,
  Market,
  Company,
  CompanyDetail,
  PriceHistory,
  FinancialStatement,
  IntrinsicValue,
  Recommendation,
  Portfolio,
  Transaction,
  Holding,
  HoldingsListResponse,
  PortfolioPerformance,
  RealizedListResponse,
  Alert,
  Watchlist,
  WatchlistItem,
  DashboardSummary,
  AnalysisSnapshot,
  ValuationTrendPoint,
  CompanyNote,
  CompanyChatMessage,
  CompanyChatResponse,
  ChatHistoryResponse,
  CompanyGoal,
  GoalScorecardRow,
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
  getCompany: (id: number) => api.get<CompanyDetail>(`/stocks/companies/${id}`),
  getPrices: (id: number) => api.get<PriceHistory[]>(`/stocks/companies/${id}/prices`, { params: { limit: 5000 } }),
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
  computeValuation: (companyId: number, assumptions?: {
    discount_rate?: number;
    terminal_growth_rate?: number;
    projection_years?: number;
    dcf_weight?: number;
    epv_weight?: number;
    bv_weight?: number;
  }) =>
    api.post<IntrinsicValue>(`/analysis/companies/${companyId}/compute`, assumptions || {}),
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
    quantity: number;
    price_per_share: number;
    fees?: number;
    transaction_date: string;
    notes?: string;
  }) => api.post<Transaction>(`/portfolio/${id}/transactions`, data),
  getHoldings: (id: number) => api.get<HoldingsListResponse>(`/portfolio/${id}/holdings`),
  getRealized: (id: number) => api.get<RealizedListResponse>(`/portfolio/${id}/realized`),
  getPerformance: (id: number) => api.get<PortfolioPerformance>(`/portfolio/${id}/performance`),
  updateTransaction: (portfolioId: number, transactionId: number, data: {
    transaction_type?: 'buy' | 'sell';
    quantity?: number;
    price_per_share?: number;
    fees?: number;
    transaction_date?: string;
    notes?: string;
  }) => api.put<Transaction>(`/portfolio/${portfolioId}/transactions/${transactionId}`, data),
  deleteTransaction: (portfolioId: number, transactionId: number) =>
    api.delete(`/portfolio/${portfolioId}/transactions/${transactionId}`),
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

// Company Notes
export const notesApi = {
  list: (companyId: number) =>
    api.get<CompanyNote[]>(`/stocks/companies/${companyId}/notes`),
  create: (companyId: number, data: { note_text: string; tag?: string }) =>
    api.post<CompanyNote>(`/stocks/companies/${companyId}/notes`, data),
  update: (companyId: number, noteId: number, data: { note_text?: string; tag?: string }) =>
    api.put<CompanyNote>(`/stocks/companies/${companyId}/notes/${noteId}`, data),
  delete: (companyId: number, noteId: number) =>
    api.delete(`/stocks/companies/${companyId}/notes/${noteId}`),
};

// Company AI Chat
export const companyChatApi = {
  ask: (companyId: number, data: { question: string; history?: CompanyChatMessage[]; verify_online?: boolean }) =>
    api.post<CompanyChatResponse>(`/stocks/companies/${companyId}/chat`, data),
  saveHistory: (companyId: number, messages: CompanyChatMessage[]) =>
    api.post(`/stocks/companies/${companyId}/chat-history`, { messages }),
  getHistory: (companyId: number) =>
    api.get<ChatHistoryResponse>(`/stocks/companies/${companyId}/chat-history`),
};

// Company Goals
export const goalsApi = {
  list: (companyId: number) =>
    api.get<CompanyGoal[]>(`/stocks/companies/${companyId}/goals`),
  scorecard: (companyId: number) =>
    api.get<GoalScorecardRow[]>(`/stocks/companies/${companyId}/goals/scorecard`),
};
