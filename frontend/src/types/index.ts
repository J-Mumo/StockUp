// API Types matching backend schemas

export interface User {
  id: number;
  email: string;
  full_name: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
}

export interface Market {
  id: number;
  name: string;
  code: string;
  country: string;
  timezone: string;
}

export interface Company {
  id: number;
  ticker_symbol: string;
  name: string;
  sector: string | null;
  is_active: boolean;
  latest_price: number | null;
  latest_change_pct: number | null;
  latest_price_date: string | null;
  intrinsic_value: number | null;
  margin_of_safety_pct: number | null;
  recommendation: string | null;
  index_membership: string | null; // "NSE 20", "NSE 25", or null
}

export interface PriceHistory {
  id: number;
  price_date: string;
  open_price: number | null;
  high_price: number | null;
  low_price: number | null;
  close_price: number;
  volume: number | null;
  change_percent: number | null;
  source: string;
}

export interface FinancialStatement {
  id: number;
  company_id: number;
  fiscal_year: number;
  period_type: string;
  revenue: number | null;
  net_income: number | null;
  earnings_per_share: number | null;
  total_assets: number | null;
  total_liabilities: number | null;
  total_equity: number | null;
  shareholders_equity: number | null;
  book_value_per_share: number | null;
  operating_cash_flow: number | null;
  capital_expenditures: number | null;
  free_cash_flow: number | null;
  dividends_per_share: number | null;
  return_on_equity: number | null;
  debt_to_equity: number | null;
  current_ratio: number | null;
  notes: string | null;
  report_date: string | null;
  entered_by_user_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface IntrinsicValue {
  id: number;
  company_id: number;
  valuation_date: string;
  dcf_value: number | null;
  epv_value: number | null;
  book_value_estimate: number | null;
  weighted_intrinsic_value: number | null;
  current_market_price: number | null;
  margin_of_safety_pct: number | null;
  recommendation: string | null;
  recommendation_reason: string | null;
  assumptions: Record<string, unknown> | null;
  calculation_details: Record<string, unknown> | null;
  calculated_at: string;
}

export interface Recommendation {
  action: string;
  reason: string;
  margin_of_safety_pct: number | null;
  quality_score: number;
  quality_max_score: number;
  quality_factors: Array<{ name: string; met: boolean; description: string }>;
}

export interface Portfolio {
  id: number;
  user_id: number;
  name: string;
  description: string | null;
  created_at: string;
}

export interface Transaction {
  id: number;
  portfolio_id: number;
  company_id: number;
  transaction_type: 'buy' | 'sell';
  shares: number;
  price_per_share: number;
  total_amount: number;
  transaction_date: string;
  notes: string | null;
  company?: Company;
}

export interface Holding {
  company_id: number;
  company_name: string;
  symbol: string;
  total_shares: number;
  average_cost: number;
  total_cost: number;
  current_price: number | null;
  current_value: number | null;
  unrealized_gain: number | null;
  unrealized_gain_pct: number | null;
}

export interface PortfolioPerformance {
  portfolio_id: number;
  total_invested: number;
  current_value: number;
  total_gain: number;
  total_gain_pct: number;
  holdings_count: number;
}

export interface Alert {
  id: number;
  user_id: number;
  company_id: number;
  alert_type: 'price_above' | 'price_below' | 'valuation_change' | 'margin_of_safety';
  threshold: number;
  message: string | null;
  is_triggered: boolean;
  is_read: boolean;
  triggered_at: string | null;
  created_at: string;
  company?: Company;
}

export interface Watchlist {
  id: number;
  user_id: number;
  name: string;
  description: string | null;
  created_at: string;
  items?: WatchlistItem[];
}

export interface WatchlistItem {
  id: number;
  watchlist_id: number;
  company_id: number;
  notes: string | null;
  added_at: string;
  company?: Company;
}

export interface DashboardSummary {
  portfolio: {
    total_portfolios: number;
    total_invested: number;
    total_current_value: number;
    total_pnl: number;
    pnl_pct: number | null;
  };
  alerts: {
    total_active: number;
    unread_triggered: number;
    recent_triggered: Array<{
      id: number;
      company_id: number;
      alert_type: string;
      message: string | null;
      triggered_at: string | null;
      is_read: boolean;
    }>;
  };
  watchlists: {
    total_watchlists: number;
    total_items: number;
  };
  top_undervalued: Array<{
    company_id: number;
    company_name: string;
    ticker: string;
    margin_of_safety_pct: number;
    intrinsic_value: number | null;
    market_price: number | null;
    recommendation: string | null;
  }>;
  market_stats: {
    total_companies: number;
    latest_price_date: string | null;
    total_price_records: number;
    companies_with_valuations: number;
  };
}

export interface AnalysisSnapshot {
  id: number;
  user_id: number;
  company_id: number;
  snapshot_data: Record<string, unknown>;
  notes: string | null;
  created_at: string;
  company?: Company;
}
