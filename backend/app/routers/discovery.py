"""Browse, similar movies, watchlist and the taste profile."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.auth import get_current_user
from app.database import get_db
from app.models import Movie, User, WatchlistEntry
from app.schemas import (
    BrowseResponse,
    MovieSummary,
    SimilarMovie,
    TasteProfile,
    WatchlistItem,
    WatchlistRequest,
)
from app.services import discovery

router = APIRouter(tags=["discovery"])

SORTS = {
    "title": Movie.title.asc(),
    "year_desc": Movie.release_year.desc(),
    "year_asc": Movie.release_year.asc(),
    "rating": Movie.avg_rating.desc(),
    "popular": Movie.rating_count.desc(),
}


@router.get("/browse", response_model=BrowseResponse)
def browse(
    q: str = Query("", max_length=100),
    genre: str = Query("", max_length=40),
    year_from: int | None = Query(None, ge=1870, le=2100),
    year_to: int | None = Query(None, ge=1870, le=2100),
    min_rating: float | None = Query(None, ge=0, le=5),
    sort: str = Query("popular"),
    page: int = Query(1, ge=1),
    per_page: int = Query(24, ge=1, le=60),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = select(Movie)
    count_stmt = select(func.count()).select_from(Movie)

    def apply(condition):
        nonlocal stmt, count_stmt
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)

    if q.strip():
        apply(Movie.title.ilike(f"%{q.strip()}%"))
    if genre.strip():
        # Genres are pipe-separated, so match the delimited token to keep
        # "Action" from matching nothing and "Drama" from matching "Docudrama".
        apply(func.concat("|", Movie.genres, "|").like(f"%|{genre.strip()}|%"))
    if year_from:
        apply(Movie.release_year >= year_from)
    if year_to:
        apply(Movie.release_year <= year_to)
    if min_rating:
        apply(Movie.avg_rating >= min_rating)

    total = int(db.execute(count_stmt).scalar_one())
    order = SORTS.get(sort, SORTS["popular"])
    rows = (
        db.execute(stmt.order_by(order, Movie.movie_id).limit(per_page).offset((page - 1) * per_page))
        .scalars()
        .all()
    )

    return BrowseResponse(
        total=total,
        page=page,
        per_page=per_page,
        items=[MovieSummary.model_validate(m) for m in rows],
    )


@router.get("/movie/{movie_id}/similar", response_model=list[SimilarMovie])
def similar(
    movie_id: int,
    limit: int = Query(6, ge=1, le=20),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if db.get(Movie, movie_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Movie not found")
    return [
        SimilarMovie(movie=MovieSummary.model_validate(m), similarity=round(score, 4))
        for m, score in discovery.similar_movies(db, movie_id, limit)
    ]


# ------------------------------------------------------------- watchlist

@router.get("/watchlist", response_model=list[WatchlistItem])
def get_watchlist(
    status_filter: str = Query("", alias="status", max_length=20),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = (
        select(WatchlistEntry)
        .options(joinedload(WatchlistEntry.movie))
        .where(WatchlistEntry.user_id == user.user_id)
    )
    if status_filter:
        stmt = stmt.where(WatchlistEntry.status == status_filter)

    rows = db.execute(stmt.order_by(WatchlistEntry.added_at.desc())).scalars().all()
    return [
        WatchlistItem(
            entry_id=r.entry_id,
            status=r.status,
            added_at=r.added_at,
            movie=MovieSummary.model_validate(r.movie),
        )
        for r in rows
    ]


@router.post("/watchlist", response_model=WatchlistItem, status_code=status.HTTP_201_CREATED)
def set_watchlist(
    payload: WatchlistRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    movie = db.get(Movie, payload.movie_id)
    if movie is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Movie not found")

    entry = db.execute(
        select(WatchlistEntry).where(
            WatchlistEntry.user_id == user.user_id,
            WatchlistEntry.movie_id == payload.movie_id,
        )
    ).scalar_one_or_none()

    if entry is None:
        entry = WatchlistEntry(
            user_id=user.user_id, movie_id=payload.movie_id, status=payload.status
        )
        db.add(entry)
    else:
        entry.status = payload.status

    db.commit()
    db.refresh(entry)
    return WatchlistItem(
        entry_id=entry.entry_id,
        status=entry.status,
        added_at=entry.added_at,
        movie=MovieSummary.model_validate(movie),
    )


@router.delete("/watchlist/{movie_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_watchlist(
    movie_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    entry = db.execute(
        select(WatchlistEntry).where(
            WatchlistEntry.user_id == user.user_id, WatchlistEntry.movie_id == movie_id
        )
    ).scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not on your list")
    db.delete(entry)
    db.commit()


# --------------------------------------------------------- taste profile

@router.get("/profile", response_model=TasteProfile)
def profile(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return TasteProfile(**discovery.taste_profile(db, user.user_id))
