"""POST /recommend — the main hybrid recommendation endpoint."""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Recommendation, User
from app.schemas import (
    MovieSummary,
    RecommendationOut,
    RecommendRequest,
    RecommendResponse,
)
from app.services import recommender

log = logging.getLogger(__name__)
router = APIRouter(tags=["recommend"])


@router.post("/recommend", response_model=RecommendResponse)
def recommend(
    payload: RecommendRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        result = recommender.recommend(
            db,
            user,
            mood_text=payload.mood_text,
            watching_with=payload.watching_with,
            time_available=payload.time_available,
            exclude_movie_ids=set(payload.exclude_movie_ids),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))

    if not result.items:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No movies matched — try a shorter time limit or a different mood.",
        )

    # Persist every recommendation shown, with the mood, score and explanation.
    rows = [
        Recommendation(
            user_id=user.user_id,
            movie_id=item.movie.movie_id,
            mood_input=payload.mood_text,
            score=item.score,
            ncf_score=item.ncf_score,
            sbert_score=item.sbert_score,
            rank_position=item.rank,
            watching_with=payload.watching_with,
            time_available=payload.time_available,
            explanation=item.explanation,
        )
        for item in result.items
    ]
    db.add_all(rows)
    db.commit()
    for row in rows:
        db.refresh(row)

    return RecommendResponse(
        mood_text=payload.mood_text,
        mood_terms=result.mood_terms,
        personalised=result.personalised,
        results=[
            RecommendationOut(
                rec_id=row.rec_id,
                rank=item.rank,
                movie=MovieSummary.model_validate(item.movie),
                score=item.score,
                ncf_score=item.ncf_score,
                sbert_score=item.sbert_score,
                explanation=item.explanation,
                score_source="model" if item.model_scored else "estimated",
            )
            for item, row in zip(result.items, rows)
        ],
    )
