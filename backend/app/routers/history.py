"""GET /history — the user's past recommendations."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.auth import get_current_user
from app.database import get_db
from app.models import Recommendation, User
from app.schemas import HistoryItem, HistoryResponse, MovieSummary

router = APIRouter(tags=["history"])


@router.get("/history", response_model=HistoryResponse)
def history(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    total = int(
        db.execute(
            select(func.count())
            .select_from(Recommendation)
            .where(Recommendation.user_id == user.user_id)
        ).scalar_one()
    )

    rows = (
        db.execute(
            select(Recommendation)
            .options(joinedload(Recommendation.movie))
            .where(Recommendation.user_id == user.user_id)
            .order_by(Recommendation.recommended_at.desc(), Recommendation.rec_id.desc())
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )

    return HistoryResponse(
        total=total,
        items=[
            HistoryItem(
                rec_id=r.rec_id,
                mood_input=r.mood_input,
                score=r.score,
                explanation=r.explanation,
                recommended_at=r.recommended_at,
                movie=MovieSummary.model_validate(r.movie),
            )
            for r in rows
        ],
    )
