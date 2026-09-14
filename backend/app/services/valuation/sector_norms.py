"""Sector-conditioned quality thresholds.

The industrial quality gate historically used a single set of numbers
(ROE > 15%, D/E < 0.5, total liabilities < 4× net income). Those defaults
are appropriate for asset-light manufacturers and consumer businesses but
systematically flag asset-heavy sectors (electricity generators, regulated
utilities, real estate) as low quality even when the underlying economics
are perfectly reasonable.

This module keeps the *same* 10-factor quality shape but lets the numeric
thresholds vary by sector. Classification is done on the free-form
``Company.sector`` string using keyword matching so the DB doesn't need any
schema changes. Unknown / missing sectors get the historical industrial
defaults.

Note: for capital-intensive sectors we prefer a ``liabilities / OCF``
metric over the classic ``liabilities / net income`` because operating
cash flow is much less distorted by non-cash charges (FX revaluation on
concessional foreign debt, revaluation reserves, deferred tax movements)
that are common in Kenyan utility and infrastructure names.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QualityNorms:
    """Per-sector thresholds for the industrial quality factors.

    Attributes:
        label: Human-readable sector label surfaced in factor detail strings.
        roe_min: Minimum average ROE for the profitability factor to pass.
        de_max: Maximum debt-to-equity for the leverage factor to pass.
        liab_to_ni_max: Maximum total liabilities / net income (fallback).
        liab_to_ocf_max: Maximum total liabilities / operating cash flow
            (preferred for asset-heavy sectors when OCF is available).
        prefer_ocf_debt_metric: When True the conservative-debt check tries
            ``liabilities / OCF`` first and only falls back to the NI-based
            metric if OCF is missing.
    """

    label: str = "industrial"
    roe_min: float = 0.15
    de_max: float = 0.5
    liab_to_ni_max: float = 4.0
    liab_to_ocf_max: float = 6.0
    prefer_ocf_debt_metric: bool = False


_INDUSTRIAL = QualityNorms()

# Electricity generators, IPPs, regulated utilities. Long-lived assets, large
# concessional debt stacks, regulated/PPA tariff revenue. 15% ROE is not a
# realistic hurdle for a well-run utility.
_ENERGY_UTILITY = QualityNorms(
    label="energy/utility",
    roe_min=0.10,
    de_max=1.2,
    liab_to_ni_max=15.0,
    liab_to_ocf_max=6.0,
    prefer_ocf_debt_metric=True,
)

# Downstream oil marketers (TotalEnergies, Rubis). Thin margins, high
# working-capital turnover. Debt is largely trade finance — different
# characterisation to a generator but still not industrial-tight.
_ENERGY_DOWNSTREAM = QualityNorms(
    label="energy/downstream",
    roe_min=0.12,
    de_max=1.0,
    liab_to_ni_max=8.0,
    liab_to_ocf_max=5.0,
    prefer_ocf_debt_metric=True,
)

# REITs / real estate operating companies (excluding formal REIT strategy).
_REAL_ESTATE = QualityNorms(
    label="real_estate",
    roe_min=0.08,
    de_max=1.5,
    liab_to_ni_max=12.0,
    liab_to_ocf_max=8.0,
    prefer_ocf_debt_metric=True,
)

# Telecoms — Safaricom-style: capex-heavy, high leverage acceptable, ROE
# often flattered by buybacks or depressed by tower spin-offs.
_TELECOM = QualityNorms(
    label="telecom",
    roe_min=0.12,
    de_max=1.0,
    liab_to_ni_max=6.0,
    liab_to_ocf_max=4.0,
    prefer_ocf_debt_metric=True,
)


# Keyword → norms mapping. First match wins. Ordering matters: more specific
# keywords should come before more general ones (e.g. "oil marketing" before
# "energy").
_KEYWORDS: tuple[tuple[tuple[str, ...], QualityNorms], ...] = (
    # Energy — downstream first so it doesn't get caught by "energy"
    (
        (
            "oil marketing",
            "oil & gas marketing",
            "petroleum retail",
            "fuel retail",
            "downstream",
        ),
        _ENERGY_DOWNSTREAM,
    ),
    # Energy — generation / utility
    (
        (
            "energy",
            "utility",
            "utilities",
            "electricity",
            "electric power",
            "power generation",
            "generation",
            "geothermal",
        ),
        _ENERGY_UTILITY,
    ),
    # Real estate (excluding formal REIT which has its own valuator)
    (
        (
            "real estate",
            "property",
            "construction & real estate",
        ),
        _REAL_ESTATE,
    ),
    # Telecoms
    (
        (
            "telecom",
            "telecommunication",
            "telecommunications",
        ),
        _TELECOM,
    ),
)


def norms_for_sector(sector: str | None) -> QualityNorms:
    """Return the appropriate ``QualityNorms`` for a free-form sector string.

    Falls back to the historical industrial defaults on unknown / missing
    input so behaviour is unchanged for any company not explicitly covered.
    """
    if not sector:
        return _INDUSTRIAL
    normalised = sector.strip().lower()
    if not normalised:
        return _INDUSTRIAL
    for keywords, norms in _KEYWORDS:
        for kw in keywords:
            if kw in normalised:
                return norms
    return _INDUSTRIAL
