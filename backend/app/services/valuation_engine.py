"""Backward-compat shim for the historical valuation-engine module.

The real implementation now lives in ``app.services.valuation`` (a package
of sector-specific strategies). This module re-exports the public API so
existing imports continue to work:

    from app.services.valuation_engine import (
        compute_valuation,
        calculate_dcf,
        calculate_epv,
        calculate_book_value,
        calculate_weighted_intrinsic_value,
        calculate_margin_of_safety,
        DEFAULT_ASSUMPTIONS,
        DCFResult, EPVResult, BookValueResult, ValuationResult,
    )

New code should import from ``app.services.valuation`` directly.

The DCF/EPV/BV functions live on the ``IndustrialValuator`` strategy and
their observable behaviour is unchanged.
"""

from __future__ import annotations

# Public composite valuation entry points
from app.services.valuation import (  # noqa: F401
    compute_valuation,
    compute_all_valuations,
    get_strategy,
)

# Result types
from app.services.valuation.base import (  # noqa: F401
    BookValueResult,
    DCFResult,
    EPVResult,
    ValuationResult,
    calculate_margin_of_safety,
)

# Industrial-strategy math (historical public API)
from app.services.valuation.industrial import (  # noqa: F401
    DEFAULT_ASSUMPTIONS,
    IndustrialValuator,
    calculate_book_value,
    calculate_dcf,
    calculate_epv,
    calculate_weighted_intrinsic_value,
    _calculate_cagr,
    _remove_outliers,
)

# Historical private helper — re-exported so tests importing it keep working.
from app.services.valuation.base import get_numeric as _get_numeric  # noqa: F401


__all__ = [
    # entry points
    "compute_valuation",
    "compute_all_valuations",
    "get_strategy",
    # results
    "DCFResult",
    "EPVResult",
    "BookValueResult",
    "ValuationResult",
    # math
    "DEFAULT_ASSUMPTIONS",
    "calculate_dcf",
    "calculate_epv",
    "calculate_book_value",
    "calculate_weighted_intrinsic_value",
    "calculate_margin_of_safety",
    "IndustrialValuator",
]
