"""Tests for company_ai_analysis_service — fingerprint & regeneration logic.

The LLM call is monkeypatched to a canned response so these tests exercise
the caching/regeneration decision path without incurring real API costs.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pytest

from app.models.company_ai_analysis import CompanyAIAnalysis
from app.models.financial_statement import FinancialStatement
from app.models.intrinsic_value import IntrinsicValue
from app.models.price_history import PriceHistory
from app.services import company_ai_analysis_service as svc


_CANNED_LLM_RESPONSE = json.dumps(
    {
        "narrative_md": "## Summary\n\nSample analysis narrative.",
        "verdict": "Watch",
        "iv_low_kes": 10.0,
        "iv_high_kes": 25.0,
        "bull_points": ["Cash flow is strong."],
        "bear_points": ["Regulatory risk is material."],
        "key_risks": ["Counterparty concentration"],
        "caveats": ["Data through FY2025 only."],
        "sector_specific_notes": ["Utility ROE hurdle relaxed."],
    }
)


@pytest.fixture()
def stub_llm(monkeypatch):
    """Replace the LLM call with a canned JSON response.

    Yields a mutable dict so tests can flip the response between calls to
    detect that a regeneration actually happened.
    """
    state = {"response": _CANNED_LLM_RESPONSE, "call_count": 0}

    def _fake_call_llm(user_prompt: str, system_prompt: str) -> str:
        state["call_count"] += 1
        return state["response"]

    monkeypatch.setattr(svc, "_call_llm", _fake_call_llm)
    return state


@pytest.fixture()
def kegn_company(db, market):
    """A KEGN-style utility company with financials, price and valuation."""
    from app.models.company import Company

    c = Company(
        market_id=market.id,
        name="Test Power Generator PLC",
        ticker_symbol="TPWR",
        sector="Energy & Petroleum",
        industry="Electricity Generation",
        shares_outstanding=6_500_000_000,
        is_active=True,
    )
    db.add(c)
    db.flush()

    # Five years of stylised utility financials.
    for i, year in enumerate(range(2021, 2026)):
        fs = FinancialStatement(
            company_id=c.id,
            fiscal_year=year,
            period_type="annual",
            revenue=50e9 * (1 + 0.05) ** i,
            net_income=6e9 * (1 + 0.15) ** i,
            earnings_per_share=1.0 + 0.1 * i,
            operating_cash_flow=22e9 * (1 + 0.05) ** i,
            capital_expenditures=10e9,
            free_cash_flow=12e9 * (1 + 0.10) ** i,
            total_assets=500e9,
            total_liabilities=250e9,
            total_equity=250e9,
            return_on_equity=0.03 + 0.005 * i,
            debt_to_equity=0.6,
            dividends_per_share=0.3,
            current_ratio=1.2,
        )
        db.add(fs)

    price = PriceHistory(
        company_id=c.id,
        price_date=date(2026, 9, 1),
        close_price=11.00,
        volume=1_000_000,
        source="test",
        fetched_at=datetime.utcnow(),
    )
    db.add(price)

    iv = IntrinsicValue(
        company_id=c.id,
        valuation_date=date(2026, 9, 1),
        dcf_value=50.68,
        epv_value=5.18,
        book_value_estimate=43.15,
        weighted_intrinsic_value=50.68,
        current_market_price=11.00,
        margin_of_safety_pct=0.783,
        recommendation="Hold",
        recommendation_reason="Quality gate not met",
        model_used="industrial_dcf",
    )
    db.add(iv)
    db.flush()
    return c


class TestFingerprint:
    def test_fingerprint_stable_for_same_inputs(self, db, kegn_company):
        """Same inputs → identical fingerprint (cache-key property)."""
        company, fs, val, price = svc._load_company_inputs(db, kegn_company.id)
        fp1 = svc.compute_input_fingerprint(company, fs, val, price)
        fp2 = svc.compute_input_fingerprint(company, fs, val, price)
        assert fp1 == fp2
        assert len(fp1) == 64  # SHA-256 hex

    def test_fingerprint_changes_when_financials_change(self, db, kegn_company):
        """A new financial statement invalidates the fingerprint."""
        company, fs, val, price = svc._load_company_inputs(db, kegn_company.id)
        fp_before = svc.compute_input_fingerprint(company, fs, val, price)

        new_fs = FinancialStatement(
            company_id=company.id,
            fiscal_year=2026,
            period_type="annual",
            revenue=80e9,
            net_income=12e9,
            free_cash_flow=18e9,
            operating_cash_flow=28e9,
        )
        db.add(new_fs)
        db.flush()

        _, fs2, _, _ = svc._load_company_inputs(db, company.id)
        fp_after = svc.compute_input_fingerprint(company, fs2, val, price)
        assert fp_before != fp_after

    def test_fingerprint_ignores_sub_1pct_price_ticks(self, db, kegn_company):
        """A 0.1% tick shouldn't invalidate the cache — that's noise."""
        company, fs, val, price = svc._load_company_inputs(db, kegn_company.id)
        fp_before = svc.compute_input_fingerprint(company, fs, val, price)

        price.close_price = 11.00 + 0.005  # ~0.04% move
        db.flush()

        fp_after = svc.compute_input_fingerprint(company, fs, val, price)
        assert fp_before == fp_after


class TestRegenerationDecision:
    def test_no_prior_analysis_triggers_regen(self, kegn_company):
        decision = svc.should_regenerate(
            current=None, new_fingerprint="whatever", latest_price=None
        )
        assert decision.regenerate is True
        assert decision.reason == "no_prior_analysis"

    def test_matching_fingerprint_serves_cache(self):
        current = CompanyAIAnalysis(
            id=1,
            company_id=1,
            generated_at=datetime.utcnow(),
            model_name="gpt-4.1",
            prompt_version=svc.PROMPT_VERSION,
            input_fingerprint="abc123",
            narrative_md="cached",
            triggered_by="user_open",
            structured_json={"_context_price": {"close": 10.0}},
        )
        decision = svc.should_regenerate(
            current=current, new_fingerprint="abc123", latest_price=None
        )
        assert decision.regenerate is False
        assert decision.reason == "cache_valid"

    def test_stale_analysis_triggers_regen(self):
        current = CompanyAIAnalysis(
            id=1,
            company_id=1,
            generated_at=datetime.utcnow() - timedelta(days=90),
            model_name="gpt-4.1",
            prompt_version=svc.PROMPT_VERSION,
            input_fingerprint="abc123",
            narrative_md="stale",
            triggered_by="user_open",
            structured_json={"_context_price": None},
        )
        decision = svc.should_regenerate(
            current=current, new_fingerprint="abc123", latest_price=None
        )
        assert decision.regenerate is True
        assert "stale" in decision.reason

    def test_prompt_version_bump_triggers_regen(self):
        current = CompanyAIAnalysis(
            id=1,
            company_id=1,
            generated_at=datetime.utcnow(),
            model_name="gpt-4.1",
            prompt_version="v0.9",  # older prompt version
            input_fingerprint="abc123",
            narrative_md="old",
            triggered_by="user_open",
            structured_json={"_context_price": None},
        )
        decision = svc.should_regenerate(
            current=current, new_fingerprint="abc123", latest_price=None
        )
        assert decision.regenerate is True
        assert decision.reason == "prompt_version_changed"

    def test_large_price_move_triggers_regen(self):
        current = CompanyAIAnalysis(
            id=1,
            company_id=1,
            generated_at=datetime.utcnow(),
            model_name="gpt-4.1",
            prompt_version=svc.PROMPT_VERSION,
            input_fingerprint="abc123",
            narrative_md="stale price",
            triggered_by="user_open",
            structured_json={"_context_price": {"close": 10.0}},
        )

        class _Price:
            close_price = 13.0  # +30% move
            price_date = date(2026, 9, 14)

        decision = svc.should_regenerate(
            current=current, new_fingerprint="abc123", latest_price=_Price()
        )
        assert decision.regenerate is True
        assert "price_moved" in decision.reason


class TestGetOrGenerate:
    def test_first_call_generates(self, db, kegn_company, stub_llm):
        """No prior analysis → LLM is called and a row is persisted."""
        row, decision = svc.get_or_generate_analysis(
            db=db, company_id=kegn_company.id, triggered_by="user_open"
        )
        assert stub_llm["call_count"] == 1
        assert decision.regenerate is True
        assert row.id is not None
        assert row.company_id == kegn_company.id
        assert row.triggered_by == "user_open"
        assert row.prompt_version == svc.PROMPT_VERSION
        assert row.sector_kind is not None
        assert "Sample analysis" in row.narrative_md
        assert row.structured_json["verdict"] == "Watch"

    def test_second_call_serves_cache(self, db, kegn_company, stub_llm):
        """Same inputs on a second call → no additional LLM call."""
        svc.get_or_generate_analysis(
            db=db, company_id=kegn_company.id, triggered_by="user_open"
        )
        assert stub_llm["call_count"] == 1

        # Change canned response so we'd detect a regeneration.
        stub_llm["response"] = json.dumps(
            {**json.loads(_CANNED_LLM_RESPONSE), "narrative_md": "SHOULD NOT SHOW"}
        )

        row2, decision2 = svc.get_or_generate_analysis(
            db=db, company_id=kegn_company.id, triggered_by="user_open"
        )
        assert stub_llm["call_count"] == 1  # unchanged
        assert decision2.regenerate is False
        assert "SHOULD NOT SHOW" not in row2.narrative_md

    def test_force_bypasses_cache(self, db, kegn_company, stub_llm):
        """force=True always regenerates even with matching fingerprint."""
        svc.get_or_generate_analysis(
            db=db, company_id=kegn_company.id, triggered_by="user_open"
        )
        assert stub_llm["call_count"] == 1

        stub_llm["response"] = json.dumps(
            {**json.loads(_CANNED_LLM_RESPONSE), "verdict": "Caution"}
        )
        row2, decision2 = svc.get_or_generate_analysis(
            db=db,
            company_id=kegn_company.id,
            triggered_by="manual",
            force=True,
        )
        assert stub_llm["call_count"] == 2
        assert decision2.regenerate is True
        assert decision2.reason == "forced"
        assert row2.structured_json["verdict"] == "Caution"

    def test_missing_company_raises(self, db, stub_llm):
        with pytest.raises(ValueError):
            svc.get_or_generate_analysis(
                db=db, company_id=9_999_999, triggered_by="user_open"
            )


class TestResponseParsing:
    def test_extracts_fenced_json(self):
        raw = "```json\n" + _CANNED_LLM_RESPONSE + "\n```"
        narrative, structured = svc._parse_response(raw, {"close": 11.0})
        assert "Sample analysis" in narrative
        assert structured["verdict"] == "Watch"
        assert structured["_context_price"] == {"close": 11.0}

    def test_invalid_json_falls_back(self):
        narrative, structured = svc._parse_response("not json at all", None)
        assert narrative == "not json at all"
        assert structured["verdict"] == "Watch"
        assert "not valid JSON" in structured["caveats"][0]
