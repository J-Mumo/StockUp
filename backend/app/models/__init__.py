"""Models package - imports all models for Alembic discovery."""

from app.models.market import Market
from app.models.company import Company
from app.models.price_history import PriceHistory
from app.models.financial_statement import FinancialStatement
from app.models.intrinsic_value import IntrinsicValue
from app.models.user import User
from app.models.portfolio import Portfolio, PortfolioTransaction
from app.models.alert import Alert
from app.models.watchlist import Watchlist, WatchlistItem
from app.models.analysis_snapshot import AnalysisSnapshot

__all__ = [
    "Market",
    "Company",
    "PriceHistory",
    "FinancialStatement",
    "IntrinsicValue",
    "User",
    "Portfolio",
    "PortfolioTransaction",
    "Alert",
    "Watchlist",
    "WatchlistItem",
    "AnalysisSnapshot",
]
