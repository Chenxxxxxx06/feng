"""Admin-only preparation endpoint for the deterministic competition demo."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import require_role
from app.database import get_db
from app.models import User
from app.services.competition_demo_service import (
    CompetitionDemoError,
    replay_latest_completed_workorder,
)
from scripts.seed_competition_demo import seed_demo


router = APIRouter()


@router.post("/competition-demo/prepare")
async def prepare_competition_demo(
    _user: User = Depends(require_role("admin")),
) -> dict[str, int | str]:
    """Reset the labelled demo scenario and prune known legacy demo clutter."""
    return await seed_demo(prune_legacy_demo=True)


@router.post("/competition-demo/incidents/{incident_id}/time-replay")
async def replay_competition_demo_time(
    incident_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_role("admin")),
) -> dict[str, int | str]:
    """Simulate 25 elapsed hours for the latest completed demo work order."""
    try:
        return await replay_latest_completed_workorder(db, incident_id=incident_id)
    except CompetitionDemoError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
