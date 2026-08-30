"""Startup warm-up: loads NCF + SBERT and builds the content bridge.

The catalogue comes from the database, not movies.csv, so films added after
the training data (TMDB imports, admin entries) are ranked too. Three pieces
have to stay aligned on one ordering — the sorted list of every movie_id in
the DB:

    sbert_service.embeddings[i]  ->  catalogue[i]
    bridge.movie_ids[i]          ->  catalogue[i]
    bridge.expand(ncf_scores)[i] ->  catalogue[i]

NCF keeps its own, smaller ordering over the 3706 trained films; the bridge is
what maps between the two.
"""

from __future__ import annotations

import logging
import time

from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models import Movie
from app.services.bridge import bridge
from app.services.ncf_service import ncf_service
from app.services.sbert_service import sbert_service

log = logging.getLogger(__name__)


def _read_catalogue() -> list[tuple[int, str, str, str]]:
    """Every movie in the DB, ordered by id: [(id, title, genres, overview)]."""
    with SessionLocal() as db:
        rows = db.execute(
            select(Movie.movie_id, Movie.title, Movie.genres, Movie.overview)
            .order_by(Movie.movie_id)
        ).all()
    return [
        (int(mid), title or "", genres or "", overview or "")
        for mid, title, genres, overview in rows
    ]


def warmup() -> None:
    """Called once from the FastAPI lifespan handler."""
    t0 = time.perf_counter()

    ncf_service.load()

    catalogue = _read_catalogue()
    if not catalogue:
        raise RuntimeError(
            "The movies table is empty. Run:  python -m app.scripts.seed_movies"
        )

    sbert_service.load(catalogue)
    bridge.build([row[0] for row in catalogue], ncf_service, sbert_service)

    if len(sbert_service.movie_ids) != len(bridge.movie_ids):
        raise RuntimeError(
            "SBERT and bridge catalogues are misaligned "
            f"({len(sbert_service.movie_ids)} vs {len(bridge.movie_ids)})"
        )

    log.info(
        "Models ready in %.1fs — %d films rankable "
        "(%d scored by the model, %d estimated via the content bridge)",
        time.perf_counter() - t0,
        len(catalogue),
        bridge.num_trained,
        bridge.num_estimated,
    )


def status() -> dict:
    """Small health payload for GET /health and the admin dashboard."""
    return {
        "ncf_loaded": ncf_service.is_loaded,
        "sbert_loaded": sbert_service.is_loaded,
        "num_users": ncf_service.num_users,
        "num_movies": ncf_service.num_movies,
        "candidates": int(len(bridge.movie_ids)),
        "trained_movies": bridge.num_trained,
        "estimated_movies": bridge.num_estimated,
        "sbert_model": settings.sbert_model,
        "sbert_dim": sbert_service.dim,
    }
