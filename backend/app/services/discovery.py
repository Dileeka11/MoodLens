"""Similar-movie lookup and personal taste analytics."""

from __future__ import annotations

from collections import Counter

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Movie, Rating, Recommendation
from app.services import explainer
from app.services.bridge import bridge
from app.services.sbert_service import sbert_service


def similar_movies(db: Session, movie_id: int, limit: int = 6) -> list[tuple[Movie, float]]:
    """Nearest neighbours in SBERT space — content similarity, not collaborative.

    Embeddings are L2-normalised, so the dot product is the cosine similarity.
    """
    pos = bridge.position_of(movie_id)
    if pos is None or not sbert_service.is_loaded:
        return []

    sims = sbert_service.embeddings @ sbert_service.embeddings[pos]
    sims[pos] = -np.inf                       # never return the film itself

    top = np.argsort(-sims)[: limit * 3]      # over-fetch: some ids may be unseeded
    ids = [int(sbert_service.movie_ids[p]) for p in top]

    movies = {
        m.movie_id: m
        for m in db.execute(select(Movie).where(Movie.movie_id.in_(ids))).scalars()
    }

    out: list[tuple[Movie, float]] = []
    for p in top:
        mid = int(sbert_service.movie_ids[p])
        movie = movies.get(mid)
        if movie is not None:
            out.append((movie, float(sims[p])))
        if len(out) >= limit:
            break
    return out


def taste_profile(db: Session, user_id: int) -> dict:
    """Everything the taste dashboard needs, in one round of queries."""
    rows = db.execute(
        select(Rating.rating_value, Rating.source, Rating.rated_at, Movie.genres, Movie.release_year)
        .join(Movie, Movie.movie_id == Rating.movie_id)
        .where(Rating.user_id == user_id)
    ).all()

    genre_totals: dict[str, list[float]] = {}
    genre_real: dict[str, int] = {}
    distribution = {str(v / 2): 0 for v in range(1, 11)}   # "0.5" .. "5.0"
    decades: dict[str, int] = {}
    real_count = 0

    for value, source, _rated_at, genres, year in rows:
        value = float(value)
        if source == "user":
            real_count += 1
            key = f"{value:.1f}"
            distribution[key] = distribution.get(key, 0) + 1
        for g in (genres or "").split("|"):
            if not g:
                continue
            genre_totals.setdefault(g, []).append(value)
            if source == "user":
                genre_real[g] = genre_real.get(g, 0) + 1
        if year:
            decade = f"{(year // 10) * 10}s"
            decades[decade] = decades.get(decade, 0) + 1

    top_genres = sorted(
        (
            {
                "genre": g,
                "count": len(vals),
                "rated_count": genre_real.get(g, 0),
                "avg_rating": round(sum(vals) / len(vals), 2),
            }
            for g, vals in genre_totals.items()
        ),
        key=lambda d: (-d["count"], -d["avg_rating"]),
    )[:8]

    # Mood vocabulary pulled from the user's own search history.
    moods = db.execute(
        select(Recommendation.mood_input, func.min(Recommendation.recommended_at))
        .where(Recommendation.user_id == user_id)
        .group_by(Recommendation.mood_input)
    ).all()

    word_counts: Counter[str] = Counter()
    for mood_text, _ in moods:
        for term in explainer.extract_mood_terms(mood_text or ""):
            word_counts[term] += 1

    avg_rating = (
        round(
            sum(float(v) for v, s, *_ in rows if s == "user") / real_count,
            2,
        )
        if real_count
        else None
    )

    return {
        "total_ratings": real_count,
        "onboarding_seeds": len(rows) - real_count,
        "average_rating": avg_rating,
        "total_searches": len(moods),
        "top_genres": top_genres,
        "rating_distribution": [
            {"stars": k, "count": v} for k, v in sorted(distribution.items(), key=lambda x: float(x[0]))
        ],
        "decades": [
            {"decade": k, "count": v} for k, v in sorted(decades.items())
        ],
        "mood_words": [
            {"word": w, "count": c} for w, c in word_counts.most_common(12)
        ],
    }
