// API Types matching backend schemas

export interface User {
  id: number;
  email: string;
  full_name: string;
}

export interface AuthResponse {
  access_token: string;
  refresh_token: string;
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

export interface CompanyDetail {
  id: number;
  market_id: number;
  name: string;
  ticker_symbol: string;
  yfinance_ticker: string | null;
  sector: string | null;
  industry: string | null;
  description: string | null;
  website: string | null;
  shares_outstanding: number | null;
  is_active: boolean;
  latest_price: number | null;
  latest_change_pct: number | null;
  latest_price_date: string | null;
  latest_valuation: IntrinsicValue | null;
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
  company_name: string | null;
  company_ticker: string | null;
  transaction_type: 'buy' | 'sell';
  quantity: number;
  price_per_share: number;
  total_amount: number;
  fees: number | null;
  transaction_date: string;
  notes: string | null;
  created_at: string;
}

export interface Holding {
  company_id: number;
  company_name: string;
  company_ticker: string;
  total_shares: number;
  average_cost_basis: number;
  total_cost: number;
  current_price: number | null;
  current_value: number | null;
  unrealized_pnl: number | null;
  unrealized_pnl_pct: number | null;
}

export interface HoldingsListResponse {
  portfolio_id: number;
  portfolio_name: string;
  holdings: Holding[];
  total_invested: number;
  total_current_value: number | null;
  total_unrealized_pnl: number | null;
}

export interface PortfolioPerformance {
  portfolio_id: number;
  portfolio_name: string;
  initial_capital: number | null;
  total_invested: number;
  total_current_value: number | null;
  cash_from_sales: number;
  total_fees_paid: number;
  unrealized_pnl: number | null;
  realized_pnl: number;
  total_pnl: number | null;
  total_return_pct: number | null;
  cagr: number | null;
  allocations: { company_id: number; company_name: string; company_ticker: string; current_value: number; allocation_pct: number }[];
}

export interface RealizedPosition {
  company_id: number;
  company_name: string;
  company_ticker: string;
  quantity_sold: number;
  remaining_shares: number;
  avg_buy_price: number;
  avg_sell_price: number;
  total_buy_cost: number;
  total_sell_proceeds: number;
  realized_fees: number;
  realized_pnl: number;
  realized_pnl_pct: number;
  first_buy_date: string | null;
  last_sell_date: string | null;
  fully_closed: boolean;
}

export interface RealizedListResponse {
  portfolio_id: number;
  portfolio_name: string;
  positions: RealizedPosition[];
  total_realized_pnl: number;
  total_realized_proceeds: number;
  total_realized_cost: number;
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

export interface ValuationTrendPoint {
  date: string;
  market_price: number | null;
  intrinsic_value: number | null;
  margin_of_safety_pct: number | null;
}

export interface CompanyNote {
  id: number;
  company_id: number;
  user_id: number;
  note_text: string;
  tag: string | null;
  created_at: string;
  updated_at: string;
}

export interface CompanyChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface OnlineValidationSummary {
  status: 'match' | 'mismatch' | 'partial' | 'unavailable';
  source: string | null;
  db_price_date: string | null;
  db_close_price: number | null;
  online_price_date: string | null;
  online_close_price: number | null;
  price_diff_pct: number | null;
  note: string | null;
}

export interface CompanyChatContextMeta {
  latest_db_price_date: string | null;
  latest_valuation_date: string | null;
  latest_financial_year: number | null;
}

export interface CompanyChatResponse {
  answer: string;
  company_ticker: string;
  online_validation: OnlineValidationSummary;
  context_meta: CompanyChatContextMeta;
}

export interface ChatHistoryItem {
  id: number;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
}

export interface ChatHistoryResponse {
  company_id: number;
  user_id: number;
  messages: ChatHistoryItem[];
}

export type GoalCategory = 'financial' | 'strategic' | 'esg' | 'operational';
export type GoalStatus =
  | 'achieved'
  | 'on_track'
  | 'partially_achieved'
  | 'missed'
  | 'abandoned'
  | 'no_mention';
export type AssessmentMethod = 'mechanical' | 'llm' | 'manual';
export type GoalConfidence = 'high' | 'medium' | 'low';

export interface CompanyGoalProgress {
  id: number;
  assessed_in_fiscal_year: number;
  status: GoalStatus;
  actual_value: number | null;
  narrative: string | null;
  evidence_quote: string | null;
  confidence: GoalConfidence;
  assessment_method: AssessmentMethod;
  created_at: string;
}

export interface CompanyGoal {
  id: number;
  company_id: number;
  fiscal_year_set: number;
  goal_text: string;
  goal_category: GoalCategory;
  metric_name: string | null;
  target_value: number | null;
  target_unit: string | null;
  target_horizon_year: number | null;
  source_section: string | null;
  source_quote: string | null;
  created_at: string;
  updated_at: string;
  progress: CompanyGoalProgress[];
}

export interface GoalScorecardRow {
  fiscal_year_set: number;
  goals_total: number;
  achieved: number;
  on_track: number;
  partially_achieved: number;
  missed: number;
  abandoned: number;
  no_mention: number;
  not_yet_assessed: number;
}
