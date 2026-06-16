"""Goals router — read access to extracted goals and progress."""

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models.company import Company
from app.models.company_goal import CompanyGoal
from app.schemas.goals import CompanyGoalRead, GoalScorecardRow

router = APIRouter(prefix="/api/stocks/companies/{company_id}/goals", tags=["goals"])


def _ensure_company(db: Session, company_id: int) -> Company:
    company = db.query(Company).filter(Company.id == company_id).first()
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return company


@router.get("", response_model=list[CompanyGoalRead])
def list_goals(
    company_id: int,
    db: Session = Depends(get_db),
):
    """List all goals for a company with their progress timeline.

    Ordered by ``fiscal_year_set`` descending (most recent first), then by id.
    """
    _ensure_company(db, company_id)
    goals = (
        db.query(CompanyGoal)
        .filter(CompanyGoal.company_id == company_id)
        .options(selectinload(CompanyGoal.progress))
        .order_by(CompanyGoal.fiscal_year_set.desc(), CompanyGoal.id)
        .all()
    )
    return goals


@router.get("/scorecard", response_model=list[GoalScorecardRow])
def goal_scorecard(
    company_id: int,
    db: Session = Depends(get_db),
):
    """Aggregate goal-outcome counts per fiscal_year_set.

    For each year management set goals, returns how many ended up
    achieved / on_track / partially_achieved / missed / abandoned /
    no_mention, plus a ``not_yet_assessed`` count for goals that have no
    progress rows yet (either future horizon, or no later report ingested).
    """
    _ensure_company(db, company_id)
    goals = (
        db.query(CompanyGoal)
        .filter(CompanyGoal.company_id == company_id)
        .options(selectinload(CompanyGoal.progress))
        .all()
    )

    # Aggregate by year. For each goal, take the *latest* progress row as
    # the canonical outcome — that's the most informative status.
    buckets: dict[int, dict[str, int]] = defaultdict(
        lambda: {
            "goals_total": 0,
            "achieved": 0,
            "on_track": 0,
            "partially_achieved": 0,
            "missed": 0,
            "abandoned": 0,
            "no_mention": 0,
            "not_yet_assessed": 0,
        }
    )

    for goal in goals:
        b = buckets[goal.fiscal_year_set]
        b["goals_total"] += 1

        if not goal.progress:
            b["not_yet_assessed"] += 1
            continue

        # Latest assessment year wins.
        latest = max(goal.progress, key=lambda p: p.assessed_in_fiscal_year)
        status = latest.status
        if status in b:
            b[status] += 1
        else:
            b["not_yet_assessed"] += 1

    return [
        GoalScorecardRow(fiscal_year_set=year, **counts)
        for year, counts in sorted(buckets.items(), reverse=True)
    ]
