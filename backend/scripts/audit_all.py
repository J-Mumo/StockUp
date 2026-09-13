"""Portfolio-wide data-quality sweep.

Runs ``audit_company`` across every company in the database and prints a
ranked report of the worst offenders (highest error count first, then
warning count).

    docker exec stockup-api-1 python -m scripts.audit_all
    docker exec stockup-api-1 python -m scripts.audit_all --details
    docker exec stockup-api-1 python -m scripts.audit_all --ticker KCB
"""
from __future__ import annotations

import argparse
from collections import defaultdict

from app.database import SessionLocal
from app.models.company import Company
from app.data.quality import audit_company


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--details",
        action="store_true",
        help="Print the full issue list for every ticker (default: top summary).",
    )
    parser.add_argument(
        "--ticker",
        help="Restrict the audit to a single ticker (implies --details).",
    )
    parser.add_argument(
        "--min-issues",
        type=int,
        default=1,
        help="Suppress tickers with fewer than this many issues in the summary.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        query = db.query(Company).order_by(Company.ticker_symbol.asc())
        if args.ticker:
            query = query.filter(Company.ticker_symbol == args.ticker.upper())
        companies = query.all()

        # (ticker, errors, warnings, sector) rows
        summary: list[tuple[str, int, int, str, list[tuple[int, str]]]] = []
        error_field_counts: dict[str, int] = defaultdict(int)
        warn_field_counts: dict[str, int] = defaultdict(int)

        for company in companies:
            audits = audit_company(db, company)
            errors = 0
            warns = 0
            issue_lines: list[tuple[int, str]] = []
            for row, report in audits:
                for issue in report.issues:
                    if issue.severity == "error":
                        errors += 1
                        error_field_counts[issue.field_name] += 1
                    else:
                        warns += 1
                        warn_field_counts[issue.field_name] += 1
                    issue_lines.append(
                        (row.fiscal_year, f"[{issue.severity}] {issue.field_name}: {issue.message}")
                    )
            summary.append(
                (company.ticker_symbol, errors, warns, company.sector or "?", issue_lines)
            )

        if args.ticker or args.details:
            for ticker, errors, warns, sector, lines in summary:
                if not lines and not args.ticker:
                    continue
                print(f"\n{ticker} ({sector})  errors={errors} warns={warns}")
                for fy, line in lines:
                    print(f"  FY{fy}: {line}")
            return

        # Summary mode: rank by errors then warnings.
        summary.sort(key=lambda r: (-r[1], -r[2], r[0]))
        print(f"{'Ticker':<8} {'Sector':<22} {'Errors':>7} {'Warns':>7}")
        print("-" * 50)
        for ticker, errors, warns, sector, _ in summary:
            if errors + warns < args.min_issues:
                continue
            print(f"{ticker:<8} {sector[:22]:<22} {errors:>7} {warns:>7}")

        totals_e = sum(r[1] for r in summary)
        totals_w = sum(r[2] for r in summary)
        clean = sum(1 for r in summary if r[1] == 0 and r[2] == 0)
        print("-" * 50)
        print(f"{'TOTAL':<8} {'':<22} {totals_e:>7} {totals_w:>7}")
        print(f"{clean}/{len(summary)} companies clean.")

        # Field-level pareto.
        if error_field_counts or warn_field_counts:
            print("\nMost common failing fields (errors):")
            for field_name, count in sorted(
                error_field_counts.items(), key=lambda kv: -kv[1]
            )[:10]:
                print(f"  {count:>4}  {field_name}")
            print("\nMost common failing fields (warnings):")
            for field_name, count in sorted(
                warn_field_counts.items(), key=lambda kv: -kv[1]
            )[:10]:
                print(f"  {count:>4}  {field_name}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
