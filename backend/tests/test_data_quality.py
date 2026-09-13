"""Unit tests for ``app.data.quality`` (validators + derivations)."""
from __future__ import annotations

from datetime import date

import pytest

from app.data.quality import (
    QualityIssue,
    QualityReport,
    derive_missing_fields,
    validate_row,
    audit_company,
    check_extraction_is_annual,
)
from app.models.company import Company
from app.models.financial_statement import FinancialStatement


# --- helpers ---------------------------------------------------------------

def _make_fs(**kwargs) -> FinancialStatement:
    defaults = {"company_id": 1, "fiscal_year": 2024, "period_type": "annual"}
    defaults.update(kwargs)
    return FinancialStatement(**defaults)


def _make_company(**kwargs) -> Company:
    defaults = {
        "market_id": 1,
        "name": "Test Bank",
        "ticker_symbol": "TB",
        "sector": "Banking",
        "shares_outstanding": 1_000_000_000,
        "is_active": True,
    }
    defaults.update(kwargs)
    return Company(**defaults)


# --- derive_missing_fields -------------------------------------------------

class TestDeriveMissingFields:
    def test_fills_bvps_when_missing(self):
        company = _make_company(shares_outstanding=1_000_000_000)
        fs = _make_fs(shareholders_equity=100_000_000_000, book_value_per_share=None)

        applied = derive_missing_fields(fs, company)

        assert applied == {"book_value_per_share": 100.0}
        assert fs.book_value_per_share == 100.0

    def test_uses_total_equity_when_shareholders_equity_missing(self):
        company = _make_company(shares_outstanding=1_000_000_000)
        fs = _make_fs(total_equity=80_000_000_000, book_value_per_share=None)

        applied = derive_missing_fields(fs, company)

        assert applied == {"book_value_per_share": 80.0}

    def test_no_change_when_bvps_already_set(self):
        company = _make_company()
        fs = _make_fs(shareholders_equity=100_000_000_000, book_value_per_share=99.5)

        applied = derive_missing_fields(fs, company)

        assert applied == {}
        assert fs.book_value_per_share == 99.5

    def test_no_change_when_no_shares_outstanding(self):
        company = _make_company(shares_outstanding=None)
        fs = _make_fs(shareholders_equity=100_000_000_000, book_value_per_share=None)

        applied = derive_missing_fields(fs, company)

        assert applied == {}
        assert fs.book_value_per_share is None

    def test_no_change_when_no_equity(self):
        company = _make_company()
        fs = _make_fs(book_value_per_share=None)

        applied = derive_missing_fields(fs, company)

        assert applied == {}


# --- validate_row: EPS vs NI/shares ---------------------------------------

class TestValidateEPS:
    def test_flags_eps_mismatch_as_error(self):
        # KCB FY2025 pattern: NI=48.9B, shares=3.21B → implied EPS=15.23, but stored EPS=4.93
        company = _make_company(shares_outstanding=3_213_462_815)
        fs = _make_fs(
            net_income=48_895_245_000, earnings_per_share=4.93,
            shareholders_equity=340_555_000_000,
        )

        report = validate_row(fs, company)

        errors = [i for i in report.issues if i.field_name == "earnings_per_share"]
        assert len(errors) == 1
        assert errors[0].severity == "error"
        assert not report.ok

    def test_tolerates_small_eps_variance(self):
        # Within 15% tolerance (diluted share count, etc.)
        company = _make_company(shares_outstanding=1_000_000_000)
        fs = _make_fs(
            net_income=15_000_000_000, earnings_per_share=14.5,  # implied 15.0, off ~3%
            shareholders_equity=100_000_000_000,
        )

        report = validate_row(fs, company)

        eps_issues = [i for i in report.issues if i.field_name == "earnings_per_share"]
        assert eps_issues == []

    def test_pre_split_eps_is_warn_not_error(self):
        # IMH FY2014 pattern: pre-split EPS reported against a row whose stored
        # shares_outstanding is post-split (4x higher). implied_shares << stored
        # -> historical share event, no per-row share history: warn, not error.
        company = _make_company(shares_outstanding=1_688_000_000)
        fs = _make_fs(
            net_income=5_320_885_000,     # FY2014 NI
            earnings_per_share=13.56,      # implied_shares = 392M (0.23x stored)
            shareholders_equity=25_000_000_000,
        )

        report = validate_row(fs, company)

        eps_issues = [i for i in report.issues if i.field_name == "earnings_per_share"]
        assert len(eps_issues) == 1
        assert eps_issues[0].severity == "warn"
        assert "historical share event" in eps_issues[0].message
        assert report.ok  # no errors


# --- validate_row: equity YoY sanity ---------------------------------------

class TestValidateEquityYoY:
    def test_flags_halving_equity_as_error(self):
        # EQTY FY2024→FY2025 pattern: 246.9B → 129.6B (-47%)
        company = _make_company(shares_outstanding=3_773_674_802)
        prev = _make_fs(fiscal_year=2024, shareholders_equity=246_868_000_000)
        curr = _make_fs(fiscal_year=2025, shareholders_equity=129_647_000_000)

        report = validate_row(curr, company, prev_row=prev)

        errors = [i for i in report.issues if i.field_name == "shareholders_equity"]
        assert len(errors) == 1
        assert errors[0].severity == "error"

    def test_tolerates_normal_growth(self):
        company = _make_company()
        prev = _make_fs(fiscal_year=2023, shareholders_equity=100_000_000_000)
        curr = _make_fs(fiscal_year=2024, shareholders_equity=115_000_000_000)  # +15%

        report = validate_row(curr, company, prev_row=prev)

        equity_issues = [i for i in report.issues if i.field_name == "shareholders_equity"]
        assert equity_issues == []


# --- validate_row: ROE consistency -----------------------------------------

class TestValidateROE:
    def test_flags_roe_mismatch_as_warn(self):
        company = _make_company()
        fs = _make_fs(
            net_income=10_000_000_000, shareholders_equity=100_000_000_000,
            return_on_equity=0.20,  # implied 0.10, off by 10 pts
        )

        report = validate_row(fs, company)

        warns = [i for i in report.issues if i.field_name == "return_on_equity"]
        assert len(warns) == 1
        assert warns[0].severity == "warn"
        assert "methodology variance" in warns[0].message


# --- validate_row: balance-sheet reconciliation ---------------------------

class TestValidateBalanceSheetReconciliation:
    def test_reconciled_balance_sheet_passes(self):
        company = _make_company()
        fs = _make_fs(
            total_assets=1_962_320_000_000,
            total_liabilities=1_679_341_000_000,
            shareholders_equity=282_979_000_000,  # 1679.341 + 282.979 = 1962.320
        )

        report = validate_row(fs, company)

        assert all(i.field_name != "total_assets" for i in report.issues)

    def test_unreconciled_balance_sheet_is_error(self):
        company = _make_company()
        # Assets duplicated from prior year (2170.874) but real liab+equity
        # only sum to 1,962.320B -- classic ingest bug.
        fs = _make_fs(
            total_assets=2_170_874_000_000,
            total_liabilities=1_679_341_000_000,
            shareholders_equity=282_979_000_000,
        )

        report = validate_row(fs, company)

        errors = [
            i for i in report.issues
            if i.field_name == "total_assets" and i.severity == "error"
        ]
        assert len(errors) == 1
        assert "reconcile" in errors[0].message
        assert not report.ok

    def test_missing_totals_skips_reconciliation(self):
        company = _make_company()
        fs = _make_fs(
            total_assets=1_962_320_000_000,
            total_liabilities=None,
            shareholders_equity=282_979_000_000,
        )

        report = validate_row(fs, company)

        # Missing pieces -> no reconciliation check, no error emitted.
        assert not any(
            i.field_name == "total_assets" and "reconcile" in i.message
            for i in report.issues
        )

    def test_small_bs_gap_is_warn_not_error(self):
        """1-3% gap (typical Kenyan filings) is a warn, not an error.

        This is the normal case when total_liabilities excludes deferred
        tax / non-controlling interest, which are reported as separate
        line items on Kenyan financial statements.
        """
        company = _make_company()
        # 2% gap: assets 100, liabilities 78, equity 20 -> L+E = 98 (2% below A)
        fs = _make_fs(
            total_assets=100_000_000_000,
            total_liabilities=78_000_000_000,
            shareholders_equity=20_000_000_000,
        )

        report = validate_row(fs, company)

        recon_issues = [
            i for i in report.issues
            if i.field_name == "total_assets"
        ]
        assert len(recon_issues) == 1
        assert recon_issues[0].severity == "warn"
        assert "gap" in recon_issues[0].message
        assert report.ok  # warn only, no errors


# --- validate_row: period type + sector_metrics ---------------------------

class TestValidatePeriodAndSector:
    def test_non_annual_is_error(self):
        company = _make_company()
        fs = _make_fs(period_type="interim")

        report = validate_row(fs, company)

        errors = [i for i in report.issues if i.field_name == "period_type"]
        assert len(errors) == 1
        assert not report.ok

    def test_bank_missing_sector_metrics_is_warn(self):
        company = _make_company(sector="Banking")
        fs = _make_fs(sector_metrics=None)

        report = validate_row(fs, company)

        warns = [i for i in report.issues if i.field_name == "sector_metrics"]
        assert len(warns) == 1
        assert report.ok  # warn only, not an error

    def test_bank_with_sector_metrics_passes(self):
        company = _make_company(sector="Banking")
        fs = _make_fs(sector_metrics={"npl_ratio": 0.15, "capital_adequacy_ratio": 0.18})

        report = validate_row(fs, company)

        assert all(i.field_name != "sector_metrics" for i in report.issues)

    def test_non_bank_does_not_require_sector_metrics(self):
        company = _make_company(sector="Telecommunications")
        fs = _make_fs(sector_metrics=None)

        report = validate_row(fs, company)

        assert all(i.field_name != "sector_metrics" for i in report.issues)


# --- audit_company (integration through DB session) -----------------------

class TestAuditCompany:
    def test_returns_rows_in_fiscal_year_order(self, db, company):
        fs2023 = FinancialStatement(
            company_id=company.id, fiscal_year=2023, period_type="annual",
            net_income=10_000_000, shareholders_equity=100_000_000,
        )
        fs2024 = FinancialStatement(
            company_id=company.id, fiscal_year=2024, period_type="annual",
            net_income=12_000_000, shareholders_equity=110_000_000,
        )
        db.add_all([fs2024, fs2023])
        db.flush()

        results = audit_company(db, company)

        assert len(results) == 2
        assert [fs.fiscal_year for fs, _ in results] == [2023, 2024]
        for _, report in results:
            assert isinstance(report, QualityReport)


# --- check_extraction_is_annual (ingest-side gate) ------------------------

class TestExtractionGate:
    def _bank(self) -> Company:
        return _make_company(shares_outstanding=1_000_000_000)

    def test_accepts_clean_annual_record(self):
        record = {
            "fiscal_year": 2024, "period_type": "annual",
            "report_date": date(2024, 12, 31),
            "net_income": 15_000_000_000, "earnings_per_share": 15.0,
            "shareholders_equity": 100_000_000_000,
        }
        ok, reasons = check_extraction_is_annual(
            record, company=self._bank(), today=date(2025, 4, 15)
        )
        assert ok, reasons

    def test_rejects_period_type_interim(self):
        record = {"fiscal_year": 2024, "period_type": "interim"}
        ok, reasons = check_extraction_is_annual(record, today=date(2025, 6, 1))
        assert not ok
        assert any("period_type" in r for r in reasons)

    def test_rejects_future_fiscal_year(self):
        # NCBA-FY2026-in-Sept-2026 pattern
        record = {
            "fiscal_year": 2027,
            "net_income": 25_000_000_000,
        }
        ok, reasons = check_extraction_is_annual(record, today=date(2026, 9, 13))
        assert not ok
        assert any("future" in r for r in reasons)

    def test_rejects_current_year_before_audit_publish(self):
        # KCB-FY2025 record uploaded in Feb 2026 — before audits publish
        record = {"fiscal_year": 2026, "net_income": 50_000_000_000}
        ok, reasons = check_extraction_is_annual(record, today=date(2026, 2, 15))
        assert not ok
        assert any("before typical audit-publish" in r for r in reasons)

    def test_rejects_mid_year_report_date(self):
        # H1 balance sheet dated June 30
        record = {
            "fiscal_year": 2024, "report_date": date(2024, 6, 30),
            "net_income": 12_000_000_000,
        }
        ok, reasons = check_extraction_is_annual(record, today=date(2025, 4, 1))
        assert not ok
        assert any("mid-year" in r for r in reasons)

    def test_rejects_when_ni_collapses_vs_prev_year(self):
        # H1 filing masquerading as full year: NI ~50% of last year
        prev = _make_fs(fiscal_year=2023, net_income=50_000_000_000)
        record = {
            "fiscal_year": 2024, "net_income": 22_000_000_000,
            "report_date": date(2024, 12, 31),
        }
        ok, reasons = check_extraction_is_annual(
            record, prev_row=prev, today=date(2025, 4, 15)
        )
        assert not ok
        assert any("net_income dropped" in r for r in reasons)

    def test_rejects_when_equity_collapses_vs_prev_year(self):
        # EQTY-FY2025 pattern: interim balance sheet halves equity
        prev = _make_fs(fiscal_year=2024, shareholders_equity=246_000_000_000)
        record = {
            "fiscal_year": 2025, "shareholders_equity": 130_000_000_000,
            "report_date": date(2025, 12, 31),
        }
        ok, reasons = check_extraction_is_annual(
            record, prev_row=prev, today=date(2026, 4, 15)
        )
        assert not ok
        assert any("equity dropped" in r for r in reasons)

    def test_rejects_eps_vs_ni_mismatch(self):
        # KCB-FY2025 pattern: interim EPS in full-year row
        company = _make_company(shares_outstanding=3_213_462_815)
        record = {
            "fiscal_year": 2024, "net_income": 48_900_000_000,
            "earnings_per_share": 4.93,  # implied 15.22, off ~68%
            "report_date": date(2024, 12, 31),
        }
        ok, reasons = check_extraction_is_annual(
            record, company=company, today=date(2025, 4, 15)
        )
        assert not ok
        assert any("EPS=" in r for r in reasons)

    def test_accepts_when_no_signals_available(self):
        # Sparse historical record with just fiscal_year — no signals to reject on
        record = {"fiscal_year": 2023}
        ok, reasons = check_extraction_is_annual(record, today=date(2025, 6, 1))
        assert ok, reasons

    def test_rejects_current_year_without_report_date(self):
        # NCBA-FY2026-in-Sept-2026 pattern: no report_date provided
        record = {
            "fiscal_year": 2026,
            "net_income": 23_400_000_000,
            "shareholders_equity": 127_000_000_000,
        }
        ok, reasons = check_extraction_is_annual(record, today=date(2026, 9, 13))
        assert not ok
        assert any("no report_date" in r for r in reasons)

    def test_report_date_string_parsed(self):
        record = {"fiscal_year": 2024, "report_date": "2024-06-30"}
        ok, reasons = check_extraction_is_annual(record, today=date(2025, 4, 15))
        assert not ok
        assert any("mid-year" in r for r in reasons)
