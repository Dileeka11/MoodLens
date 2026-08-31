"""Admin endpoints — movie CRUD, user management, stats and model info.

Every route depends on require_admin, so a normal user's token gets a 403.
"""

import threading

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import hash_password, require_admin
from app.database import get_db
from app.models import Movie, Rating, Recommendation, User
from app.schemas import (
    AdminStats,
    AdminUserCreate,
    EvaluationResult,
    ModelInfo,
    MovieCreate,
    MovieSummary,
    MovieUpdate,
    PaginatedMovies,
    PaginatedUsers,
    UserOut,
)
from app.services import evaluation, model_meta, model_registry, tmdb_sync

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


# ----------------------------------------------------------------- stats

@router.get("/stats", response_model=AdminStats)
def stats(db: Session = Depends(get_db)):
    def count(model) -> int:
        return int(db.execute(select(func.count()).select_from(model)).scalar_one())

    return AdminStats(
        users=count(User),
        movies=count(Movie),
        ratings=count(Rating),
        recommendations=count(Recommendation),
    )


# ---------------------------------------------------------------- movies

@router.get("/movies", response_model=PaginatedMovies)
def list_movies(
    q: str = Query("", max_length=100),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    stmt = select(Movie)
    count_stmt = select(func.count()).select_from(Movie)
    if q.strip():
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(Movie.title.ilike(pattern))
        count_stmt = count_stmt.where(Movie.title.ilike(pattern))

    total = int(db.execute(count_stmt).scalar_one())
    rows = (
        db.execute(
            stmt.order_by(Movie.movie_id).limit(per_page).offset((page - 1) * per_page)
        )
        .scalars()
        .all()
    )
    return PaginatedMovies(
        total=total,
        page=page,
        per_page=per_page,
        items=[MovieSummary.model_validate(m) for m in rows],
    )


@router.post("/movies", response_model=MovieSummary, status_code=status.HTTP_201_CREATED)
def create_movie(payload: MovieCreate, db: Session = Depends(get_db)):
    movie_id = payload.movie_id
    if movie_id is None:
        # movie_id is the MovieLens id and has no autoincrement, so allocate
        # the next free one above the imported range.
        highest = db.execute(select(func.max(Movie.movie_id))).scalar() or 0
        movie_id = int(highest) + 1
    elif db.get(Movie, movie_id) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="movie_id already exists")

    movie = Movie(
        movie_id=movie_id,
        title=payload.title,
        genres=payload.genres or "",
        tmdb_id=payload.tmdb_id,
        overview=payload.overview,
        poster_url=payload.poster_url,
        release_year=payload.release_year,
        runtime_minutes=payload.runtime_minutes,
    )
    db.add(movie)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Could not create movie")
    db.refresh(movie)
    return MovieSummary.model_validate(movie)


@router.put("/movies/{movie_id}", response_model=MovieSummary)
def update_movie(movie_id: int, payload: MovieUpdate, db: Session = Depends(get_db)):
    movie = db.get(Movie, movie_id)
    if movie is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Movie not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(movie, field, value)
    db.commit()
    db.refresh(movie)
    return MovieSummary.model_validate(movie)


@router.delete("/movies/{movie_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_movie(movie_id: int, db: Session = Depends(get_db)):
    movie = db.get(Movie, movie_id)
    if movie is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Movie not found")
    # Ratings and recommendations cascade at the FK level.
    db.delete(movie)
    db.commit()


# ----------------------------------------------------------------- users

@router.get("/users", response_model=PaginatedUsers)
def list_users(
    q: str = Query("", max_length=100),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    stmt = select(User)
    count_stmt = select(func.count()).select_from(User)
    if q.strip():
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(User.email.ilike(pattern) | User.username.ilike(pattern))
        count_stmt = count_stmt.where(User.email.ilike(pattern) | User.username.ilike(pattern))

    total = int(db.execute(count_stmt).scalar_one())
    rows = (
        db.execute(stmt.order_by(User.user_id).limit(per_page).offset((page - 1) * per_page))
        .scalars()
        .all()
    )
    return PaginatedUsers(
        total=total, page=page, per_page=per_page,
        items=[UserOut.model_validate(u) for u in rows],
    )


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(payload: AdminUserCreate, db: Session = Depends(get_db)):
    user = User(
        username=payload.username.strip(),
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        role=payload.role,
        ncf_user_index=payload.ncf_user_index,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")
    db.refresh(user)
    return UserOut.model_validate(user)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    if user_id == admin.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot delete the account you are signed in with",
        )
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    db.delete(user)
    db.commit()


# ----------------------------------------------------------------- model

@router.get("/model", response_model=ModelInfo)
def model_info(db: Session = Depends(get_db)):
    return ModelInfo(**model_registry.status(), **_meta_fields(model_meta.read_meta()))


@router.post("/model/retrain", response_model=ModelInfo)
def retrain(db: Session = Depends(get_db)):
    """Re-evaluates the existing checkpoint. It does NOT retrain weights.

    The project ships a pre-trained model that must be served as-is, so this
    scores the current model against your users' real ratings and records the
    RMSE. The dashboard labels the button accordingly.
    """
    meta = model_meta.evaluate(db)
    return ModelInfo(**model_registry.status(), **_meta_fields(meta))


@router.get("/model/metrics", response_model=EvaluationResult)
def metrics(
    k: int = Query(5, ge=1, le=20),
    max_ratings: int = Query(200_000, ge=1000, le=2_000_000),
):
    """Accuracy of the checkpoint against the MovieLens ground-truth ratings.

    Returns available=false with a reason when no ratings file is present —
    there is no ground truth to measure against, and inventing one would be
    worse than reporting nothing.
    """
    return EvaluationResult(**evaluation.evaluate_against_ground_truth(k=k, max_ratings=max_ratings))


def _meta_fields(meta: dict) -> dict:
    return {
        "last_trained": meta.get("last_trained"),
        "rmse": meta.get("rmse"),
        "evaluated_at": meta.get("evaluated_at"),
        "evaluated_on_ratings": meta.get("evaluated_on_ratings"),
        "note": meta.get("note"),
    }


# ----------------------------------------------------------------- tmdb sync

@router.get("/sync/status")
def sync_status():
    return tmdb_sync.get_status()


@router.post("/sync/posters", status_code=status.HTTP_202_ACCEPTED)
def start_poster_sync():
    """Backfill poster_url / overview / runtime from TMDB for existing movies."""
    state = tmdb_sync.get_status()
    if state["posters"]["running"]:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Poster sync already running")
    threading.Thread(target=tmdb_sync.run_poster_sync, daemon=True).start()
    return {"started": True}


@router.post("/sync/recent", status_code=status.HTTP_202_ACCEPTED)
def start_recent_sync(
    year_from: int = Query(2001, ge=2001, le=2100),
    min_votes: int = Query(300, ge=0),
    per_year: int = Query(200, ge=1, le=1000),
):
    """Import post-2000 films from TMDB Discover."""
    state = tmdb_sync.get_status()
    if state["recent"]["running"]:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Recent sync already running")
    threading.Thread(
        target=tmdb_sync.run_recent_sync,
        args=(year_from, min_votes, per_year),
        daemon=True,
    ).start()
    return {"started": True}
