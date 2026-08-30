"""GET /movie/{id} — full detail for the movie details screen."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Movie, Rating, Recommendation, User
from app.schemas import MovieDetail, MovieSummary
from app.services.ncf_service import ncf_service

router = APIRouter(tags=["movies"])


@router.get("/movie/{movie_id}", response_model=MovieDetail)
def movie_detail(
    movie_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    movie = db.get(Movie, movie_id)
    if movie is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Movie not found")

    your_rating = db.execute(
        select(Rating.rating_value).where(
            Rating.user_id == user.user_id, Rating.movie_id == movie_id
        )
    ).scalar_one_or_none()

    # Powers the "Why we chose this" panel when arriving from a recommendation.
    last_explanation = db.execute(
        select(Recommendation.explanation)
        .where(Recommendation.user_id == user.user_id, Recommendation.movie_id == movie_id)
        .order_by(Recommendation.recommended_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    detail = MovieDetail.model_validate(movie)
    detail.your_rating = your_rating
    detail.last_explanation = last_explanation
    detail.in_ncf_model = ncf_service.has_embedding(movie_id)
    return detail


@router.get("/movies", response_model=list[MovieSummary])
def search_movies(
    q: str = Query("", max_length=100),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Lightweight title search, used by the rating flow."""
    stmt = select(Movie)
    if q.strip():
        stmt = stmt.where(Movie.title.ilike(f"%{q.strip()}%"))
    stmt = stmt.order_by(Movie.rating_count.desc(), Movie.title).limit(limit)
    return [MovieSummary.model_validate(m) for m in db.execute(stmt).scalars()]
