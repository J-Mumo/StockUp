"""Data-quality helpers for ``FinancialStatement`` rows.

Two responsibilities:

1. Cheap derivations that fill obvious blanks (e.g. BVPS from equity/shares).
2. Consistency checks that flag or reject internally-inconsistent rows
   (EPS vs NI/shares, BVPS vs equity/shares, ROE vs NI/equity, sudden equity
   swings that betray an interim filing being ingested as full-year).

Design goal: the validator returns structured issues; callers decide whether
to reject/flag/skip. The engine itself keeps tolerating ``None`` values.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.financial_statement import FinancialStatement


# Tolerances -----------------------------------------------------------------

EPS_TOLERANCE = 0.10               # EPS vs NI/shares (banks routinely diluted)
BVPS_TOLERANCE = 0.05
ROE_TOLERANCE_ABS = 0.02           # 200 bps
EQUITY_YOY_MIN = -0.40             # equity shouldn't drop >40% YoY
EQUITY_YOY_MAX = 0.60              # or grow >60% YoY (excl. rights issues)
BS_YOY_FLAT_EPS = 0.001            # < 0.1% YoY change on a balance-sheet total = duplicate ingest
PL_SCALE_JUMP_RATIO = 50.0         # >50x YoY on revenue/NI = base-year data error
BS_RECONCILE_TOLERANCE = 0.01      # |A - (L + E)| / A > 1% = failed reconciliation


# Result types ---------------------------------------------------------------

@dataclass
class QualityIssue:
    field_name: str
    severity: str  # "warn" | "error"
    message: str


@dataclass
class QualityReport:
    issues: list[QualityIssue] = field(default_factory=list)
    derived: dict[str, float] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    @property
    def errors(self) -> list[QualityIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[QualityIssue]:
        return [i for i in self.issues if i.severity == "warn"]


# Helpers --------------------------------------------------------------------

def _f(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _row_equity(fs: FinancialStatement) -> float | None:
    return _f(fs.shareholders_equity) or _f(fs.total_equity)


# Derivations ----------------------------------------------------------------

def derive_missing_fields(
    fs: FinancialStatement, company: Company
) -> dict[str, float]:
    """Fill obvious blanks in-place. Returns a dict of applied changes.

    Currently:
      - ``book_value_per_share`` = equity / shares_outstanding
    """
    derived: dict[str, float] = {}
    shares = company.shares_outstanding
    equity = _row_equity(fs)
    if fs.book_value_per_share is None and shares and equity:
        bvps = equity / shares
        fs.book_value_per_share = bvps
        derived["book_value_per_share"] = bvps
    return derived


# Validators -----------------------------------------------------------------

def validate_row(
    fs: FinancialStatement,
    company: Company,
    *,
    prev_row: FinancialStatement | None = None,
) -> QualityReport:
    """Check internal consistency of a single ``FinancialStatement`` row.

    ``prev_row`` (if supplied) is used for YoY sanity checks.
    """
    report = QualityReport()
    shares = company.shares_outstanding
    ni = _f(fs.net_income)
    eps = _f(fs.earnings_per_share)
    equity = _row_equity(fs)
    bvps = _f(fs.book_value_per_share)
    roe = _f(fs.return_on_equity)
    sector_is_bank = bool(company.sector and "bank" in company.sector.lower())

    # 1. EPS vs NI/shares
    if shares and ni and eps:
        implied = ni / shares
        if implied and abs(implied - eps) / abs(implied) > EPS_TOLERANCE:
            report.issues.append(
                QualityIssue(
                    "earnings_per_share",
                    "error",
                    f"EPS={eps:.2f} disagrees with NI/shares={implied:.2f} "
                    f"(>{EPS_TOLERANCE:.0%}); probable period mismatch",
                )
            )

    # 2. BVPS vs equity/shares
    if shares and equity and bvps:
        implied = equity / shares
        if implied and abs(implied - bvps) / abs(implied) > BVPS_TOLERANCE:
            report.issues.append(
                QualityIssue(
                    "book_value_per_share",
                    "warn",
                    f"BVPS={bvps:.2f} disagrees with equity/shares={implied:.2f} "
                    f"(>{BVPS_TOLERANCE:.0%})",
                )
            )

    # 3. ROE vs NI/equity — methodology variance, not an error.
    # Reported ROE is typically computed on *average* equity and may use
    # attributable-to-owners equity, while NI/(closing equity) uses
    # point-in-time total equity. A 200 bps gap almost always reflects
    # this definition difference. We preserve the reported value and
    # surface both figures for transparency.
    if ni and equity and roe is not None:
        implied = ni / equity
        if abs(implied - roe) > ROE_TOLERANCE_ABS:
            report.issues.append(
                QualityIssue(
                    "return_on_equity",
                    "warn",
                    f"ROE methodology variance: reported={roe:.3f} vs "
                    f"NI/closing-equity={implied:.3f} (diff={implied - roe:+.3f}). "
                    f"Likely average-vs-point-in-time equity or "
                    f"attributable-vs-total equity; reported ROE preserved.",
                )
            )

    # 4. Equity YoY sanity (banks don't halve; large jumps usually mean interims)
    if prev_row is not None:
        prev_equity = _row_equity(prev_row)
        if prev_equity and equity:
            change = (equity - prev_equity) / prev_equity
            if change < EQUITY_YOY_MIN or change > EQUITY_YOY_MAX:
                report.issues.append(
                    QualityIssue(
                        "shareholders_equity",
                        "error",
                        f"Equity moved {change:+.1%} YoY "
                        f"(FY{prev_row.fiscal_year}->FY{fs.fiscal_year}); "
                        f"probable interim / period-mismatch row",
                    )
                )

    # 4b. Balance-sheet YoY-flat anomaly: totals identical to the prior year
    # (< 0.1% change) almost always mean the ingest re-used the prior row's
    # value because the current-year figure was missing or mis-extracted.
    if prev_row is not None:
        for attr in ("total_assets", "total_liabilities", "shareholders_equity"):
            prev_v = _f(getattr(prev_row, attr, None))
            curr_v = _f(getattr(fs, attr, None))
            if prev_v and curr_v and prev_v > 0:
                change = abs(curr_v - prev_v) / prev_v
                if change < BS_YOY_FLAT_EPS:
                    report.issues.append(
                        QualityIssue(
                            attr,
                            "warn",
                            f"{attr}={curr_v:.0f} unchanged vs FY{prev_row.fiscal_year} "
                            f"({change:+.4%} YoY); probable duplicate ingest / missing value",
                        )
                    )

    # 4c. P&L scale-jump anomaly: revenue or NI jumping >50x YoY (either
    # direction) is almost always a base-year data error (unit mismatch,
    # partial-year row, restated base). Flag to keep CAGRs clean.
    if prev_row is not None:
        for attr in ("revenue", "net_income"):
            prev_v = _f(getattr(prev_row, attr, None))
            curr_v = _f(getattr(fs, attr, None))
            if prev_v and curr_v and prev_v > 0 and curr_v > 0:
                ratio = curr_v / prev_v
                if ratio > PL_SCALE_JUMP_RATIO or ratio < 1.0 / PL_SCALE_JUMP_RATIO:
                    report.issues.append(
                        QualityIssue(
                            attr,
                            "warn",
                            f"{attr} moved {ratio:.0f}x YoY "
                            f"(FY{prev_row.fiscal_year}->FY{fs.fiscal_year}); "
                            f"probable base-year data error",
                        )
                    )

    # 4d. Balance-sheet reconciliation: Assets = Liabilities + Equity
    # (within tolerance). This catches the most common ingest bug --
    # one of the three totals being carried over from the wrong row,
    # unit-mismatched, or missing entirely -- long before it corrupts
    # the valuation model.
    total_assets = _f(fs.total_assets)
    total_liab = _f(fs.total_liabilities)
    if total_assets and total_liab and equity and total_assets > 0:
        implied_a = total_liab + equity
        diff = total_assets - implied_a
        rel = abs(diff) / total_assets
        if rel > BS_RECONCILE_TOLERANCE:
            report.issues.append(
                QualityIssue(
                    "total_assets",
                    "error",
                    f"Balance sheet does not reconcile: "
                    f"assets={total_assets:.0f} vs "
                    f"liabilities+equity={implied_a:.0f} "
                    f"(diff={diff:+.0f}, {rel:.2%} of assets); "
                    f"one of the three totals is mis-ingested",
                )
            )

    # 5. Period type must be annual for the valuation engine
    period_type = (fs.period_type or "annual").lower()
    if period_type != "annual":
        report.issues.append(
            QualityIssue(
                "period_type",
                "error",
                f"Non-annual row (period_type={period_type!r})",
            )
        )

    # 6. Banks must have sector_metrics for the quality discount to fire
    if sector_is_bank and not fs.sector_metrics:
        report.issues.append(
            QualityIssue(
                "sector_metrics",
                "warn",
                "Bank row missing sector_metrics (NPL/CAR/CoR); "
                "quality discount and bank-specific recommendation gate "
                "will not fire",
            )
        )

    return report


def audit_company(
    db: Session, company: Company
) -> list[tuple[FinancialStatement, QualityReport]]:
    """Run ``validate_row`` across every annual row of a company, ordered by
    fiscal year ascending, threading ``prev_row`` for YoY checks."""
    stmt = (
        select(FinancialStatement)
        .where(FinancialStatement.company_id == company.id)
        .order_by(FinancialStatement.fiscal_year.asc())
    )
    rows: Sequence[FinancialStatement] = list(db.scalars(stmt))
    out: list[tuple[FinancialStatement, QualityReport]] = []
    prev: FinancialStatement | None = None
    for row in rows:
        report = validate_row(row, company, prev_row=prev)
        out.append((row, report))
        prev = row
    return out


# Ingest-side gate ----------------------------------------------------------

# NSE bank fiscal-year-ends are almost universally December 31; a handful of
# groups run to Sep 30. Any June-30 date is much more likely an H1 filing
# than a year-end, so we keep the window narrow. (June-30-year-end companies
# on the NSE are rare; they can be handled with a per-company override.)
ANNUAL_REPORT_MONTHS: frozenset[int] = frozenset({9, 10, 11, 12, 1, 2, 3})

# When comparing to a prior-year row, an audited full-year record should not
# see net income drop by more than this fraction (interim filings look tiny).
EXTRACTION_NI_DROP_MAX = 0.50
EXTRACTION_EQUITY_DROP_MAX = 0.40

# EPS-vs-NI/shares tolerance at ingest time is looser than the post-hoc audit
# (EPS_TOLERANCE=15%) because reported basic EPS is calculated on
# weighted-average shares outstanding rather than year-end shares, which can
# legitimately drift ~15% when a company issues stock mid-year (rights,
# scrip, acquisitions).
EXTRACTION_EPS_TOLERANCE = 0.20


def check_extraction_is_annual(
    record: dict,
    *,
    prev_row: FinancialStatement | None = None,
    company: Company | None = None,
    today: date | None = None,
) -> tuple[bool, list[str]]:
    """Decide whether an extracted record represents a full-year audited row.

    Returns ``(ok, reasons)`` where ``ok`` is False when the record should be
    rejected before upsert, and ``reasons`` lists all failing checks.

    Rules (any single failure rejects the row):

    - ``fiscal_year`` cannot be later than the current calendar year (an
      audited FY-N report can only exist after N's fiscal year-end has
      passed and the audit has completed). A row labelled with the current
      year is only accepted if a plausible year-end has already occurred.
    - ``period_type``, when present in the record, must be ``"annual"``.
    - ``report_date``, when present, must fall in a fiscal-year-end month.
    - When a previous audited row exists, net income and shareholders'
      equity must not have collapsed vs the prior year (interim filings
      typically show ~50% figures).
    - Internal consistency: EPS x shares vs NI within ``EPS_TOLERANCE``
      when both are present.
    """
    reasons: list[str] = []
    now = today or date.today()

    fiscal_year = record.get("fiscal_year")
    fy: int | None = None
    if fiscal_year is not None:
        try:
            fy = int(fiscal_year)
        except (TypeError, ValueError):
            fy = None
        if fy is not None:
            if fy > now.year:
                reasons.append(
                    f"fiscal_year={fy} is in the future (today={now.isoformat()}); "
                    f"cannot be an audited annual report"
                )
            elif fy == now.year and now.month < 4:
                reasons.append(
                    f"fiscal_year={fy} equals current year and today={now.isoformat()} "
                    f"is before typical audit-publish window (Apr-N); probable interim"
                )

    period_type = record.get("period_type")
    if period_type is not None and str(period_type).lower() != "annual":
        reasons.append(
            f"period_type={period_type!r} (only 'annual' accepted for ingest)"
        )

    report_date = record.get("report_date")
    month = None
    if report_date is not None:
        try:
            month = int(getattr(report_date, "month", 0)) or None
            if month is None and isinstance(report_date, str):
                month = int(report_date.split("-")[1])
        except (AttributeError, ValueError, IndexError):
            month = None
    if month is not None and month not in ANNUAL_REPORT_MONTHS:
        reasons.append(
            f"report_date month={month} is mid-year (not a typical fiscal "
            f"year-end); probable interim filing"
        )

    # When the record is for the current year, we require an explicit
    # report_date proving the fiscal year-end has already passed. Without
    # it, we cannot distinguish a delayed audit ingest from an interim
    # filing labelled as annual (e.g. NCBA-FY2026-in-Sept-2026).
    if fy is not None and fy >= now.year and report_date is None:
        reasons.append(
            f"fiscal_year={fy} is current or future and no report_date "
            f"supplied; require an explicit year-end date to prove annual"
        )

    ni = _f(record.get("net_income"))
    equity = _f(record.get("shareholders_equity")) or _f(record.get("total_equity"))
    eps = _f(record.get("earnings_per_share"))

    if company is not None and company.shares_outstanding and ni and eps:
        implied = ni / company.shares_outstanding
        if implied and abs(implied - eps) / abs(implied) > EXTRACTION_EPS_TOLERANCE:
            reasons.append(
                f"EPS={eps:.2f} disagrees with NI/shares={implied:.2f} "
                f"(>{EXTRACTION_EPS_TOLERANCE:.0%}); interim EPS in FY row"
            )

    if prev_row is not None:
        prev_ni = _f(prev_row.net_income)
        if prev_ni and prev_ni > 0 and ni is not None:
            drop = (prev_ni - ni) / prev_ni
            if drop > EXTRACTION_NI_DROP_MAX:
                reasons.append(
                    f"net_income dropped {drop:.0%} vs FY{prev_row.fiscal_year} "
                    f"({prev_ni:,.0f} -> {ni:,.0f}); probable half-year figure"
                )
        prev_equity = _row_equity(prev_row)
        if prev_equity and equity is not None:
            change = (equity - prev_equity) / prev_equity
            if change < -EXTRACTION_EQUITY_DROP_MAX:
                reasons.append(
                    f"equity dropped {change:+.0%} vs FY{prev_row.fiscal_year} "
                    f"({prev_equity:,.0f} -> {equity:,.0f}); probable interim "
                    f"balance sheet"
                )

    return (not reasons), reasons


__all__ = [
    "QualityIssue",
    "QualityReport",
    "derive_missing_fields",
    "validate_row",
    "audit_company",
    "check_extraction_is_annual",
    "ANNUAL_REPORT_MONTHS",
]
