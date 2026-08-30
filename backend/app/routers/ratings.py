"""POST /rate — save or update a user's rating."""

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Movie, Rating, User
from app.schemas import RateRequest, RatingOut

router = APIRouter(tags=["ratings"])


def refresh_movie_aggregate(db: Session, movie_id: int) -> None:
    """Recompute avg_rating / rating_count from real user ratings only."""
    avg, count = db.execute(
        select(func.avg(Rating.rating_value), func.count())
        .where(Rating.movie_id == movie_id, Rating.source == "user")
    ).one()

    movie = db.get(Movie, movie_id)
    if movie is not None:
        movie.avg_rating = Decimal(str(round(float(avg), 2))) if avg else Decimal("0.00")
        movie.rating_count = int(count or 0)


@router.post("/rate", response_model=RatingOut, status_code=status.HTTP_201_CREATED)
def rate(
    payload: RateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if db.get(Movie, payload.movie_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Movie not found")

    existing = db.execute(
        select(Rating).where(
            Rating.user_id == user.user_id, Rating.movie_id == payload.movie_id
        )
    ).scalar_one_or_none()

    if existing is not None:
        # Re-rating replaces the old value, and promotes an onboarding seed
        # to a real rating.
        existing.rating_value = payload.rating_value
        existing.source = "user"
        rating = existing
    else:
        rating = Rating(
            user_id=user.user_id,
            movie_id=payload.movie_id,
            rating_value=payload.rating_value,
            source="user",
        )
        db.add(rating)

    db.flush()
    refresh_movie_aggregate(db, payload.movie_id)
    db.commit()
    db.refresh(rating)
    return RatingOut.model_validate(rating)


@router.get("/ratings", response_model=list[RatingOut])
def my_ratings(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.execute(
        select(Rating)
        .where(Rating.user_id == user.user_id)
        .order_by(Rating.rated_at.desc())
    ).scalars().all()
    return [RatingOut.model_validate(r) for r in rows]
