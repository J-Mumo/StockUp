"""One-shot backfill: refresh the recommendation / recommendation_reason
columns on the latest IntrinsicValue row for every active company.

Motivation: ``compute_valuation`` writes IV numbers but does not stamp
``recommendation``/``recommendation_reason`` — those are only set by the
``POST /companies/{id}/analysis`` router path. After a change to the
recommendation-engine gate (see commit ``06f9273``: bank core-factor
indices), listing/dashboard views keep displaying the pre-fix cached
strings until each company is opened in the detail view.

Usage (from ``backend/`` with venv active or inside the api container):

    python -m scripts.backfill_recommendations           # dry-run
    python -m scripts.backfill_recommendations --commit  # persist

Default is dry-run so an operator can preview the delta before writing.
"""

from __future__ import annotations

import argparse

from sqlalchemy import desc

from app.database import SessionLocal
from app.models.company import Company
from app.models.intrinsic_value import IntrinsicValue
from app.services import recommendation_engine


def backfill(commit: bool) -> int:
    session = SessionLocal()
    updated = skipped = 0
    changes: list[str] = []
    try:
        active = session.query(Company).filter(Company.is_active == True).all()  # noqa: E712
        for c in active:
            iv = (
                session.query(IntrinsicValue)
                .filter(IntrinsicValue.company_id == c.id)
                .order_by(desc(IntrinsicValue.valuation_date), desc(IntrinsicValue.id))
                .first()
            )
            if iv is None:
                skipped += 1
                continue
            mos = float(iv.margin_of_safety_pct) if iv.margin_of_safety_pct is not None else None
            rec = recommendation_engine.compute_recommendation(session, c.id, mos)
            if isinstance(rec, str):
                skipped += 1
                continue
            prev_action = iv.recommendation
            prev_reason = iv.recommendation_reason
            iv.recommendation = rec.action
            iv.recommendation_reason = rec.reason
            updated += 1
            action_changed = prev_action != rec.action
            reason_changed = prev_reason != rec.reason
            model = iv.model_used or "?"
            if action_changed:
                changes.append(
                    f"  [action] {c.ticker_symbol:<6} ({model:<24}) "
                    f"{prev_action or 'None':<14} -> {rec.action}"
                )
            elif reason_changed and model.startswith("bank"):
                changes.append(
                    f"  [reason] {c.ticker_symbol:<6} ({model:<24}) same action, new reason"
                )

        if commit:
            session.commit()
            print(f"[commit] updated={updated} skipped={skipped}")
        else:
            session.rollback()
            print(f"[dry-run] updated={updated} skipped={skipped} (rolled back)")

        if changes:
            print("Changes:")
            for line in changes:
                print(line)
        else:
            print("No action or reason changes detected.")
        return 0
    except Exception as e:
        session.rollback()
        print(f"error: {e}")
        return 1
    finally:
        session.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", action="store_true", help="Persist changes (default is dry-run)")
    args = parser.parse_args()
    return backfill(commit=args.commit)


if __name__ == "__main__":
    raise SystemExit(main())
