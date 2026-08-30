"""Hybrid recommendation service.

    hybrid = 0.7 * norm(NCF score) + 0.3 * norm(SBERT cosine similarity)

Both terms are min-max normalised to 0-1 across the candidate pool *before*
blending, so neither can dominate through scale alone. Viewing-context
preferences (who you're watching with, how long you have) are applied after
the blend as a small, explicit adjustment — they shape the ranking without
distorting the two model scores that get stored.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Movie, Rating, User, WatchlistEntry
from app.services import explainer
from app.services.bridge import bridge
from app.services.ncf_service import ncf_service
from app.services.sbert_service import sbert_service

log = logging.getLogger(__name__)

# Runtime ceilings per dropdown option. Movies with an unknown runtime are
# never filtered out — almost all of them are, since movies.csv has no runtime.
TIME_LIMITS: dict[str, int] = {"~1hr": 80, "~2hrs": 140, "~3hrs+": 10_000}

# Post-blend nudges. Small on purpose: the 0.7/0.3 hybrid stays in charge.
COMPANY_BOOST: dict[str, dict[str, float]] = {
    "Alone": {},
    "Partner": {"Romance": 0.05, "Drama": 0.03, "Thriller": 0.02},
    "Family": {
        "Children's": 0.08, "Animation": 0.06, "Comedy": 0.04, "Adventure": 0.03,
        "Horror": -0.60, "Film-Noir": -0.10, "Crime": -0.08, "War": -0.05,
    },
    "Friends": {"Comedy": 0.06, "Action": 0.05, "Horror": 0.04, "Adventure": 0.03},
}

WATCHING_WITH = tuple(COMPANY_BOOST)
TIME_OPTIONS = tuple(TIME_LIMITS)

# At most this many picks may share a primary genre. Without it the top 5 are
# often five near-identical films, which reads as a broken recommender even
# when the scores are right.
MAX_PER_GENRE = 2

# When the query clearly names a genre (via explainer.implied_genres — "scary"
# -> Horror/Thriller), results are gated to those genres so a horror search can
# never return a rom-com. Matching films also get a boost so they lead the
# ranking. The gate relaxes to boost-only if fewer than top_k films match, so
# an unusual request still returns something instead of a 404.
GENRE_GATE_BOOST = 0.35


@dataclass
class Recommendation:
    movie: Movie
    score: float
    ncf_score: float
    sbert_score: float
    explanation: str
    rank: int
    # False when the NCF part was borrowed from similar films because this
    # title is not in the trained model. Surfaced to the UI, never hidden.
    model_scored: bool = True


@dataclass
class RecommendationResult:
    items: list[Recommendation] = field(default_factory=list)
    personalised: bool = False
    mood_terms: list[str] = field(default_factory=list)


def _minmax(x: np.ndarray) -> np.ndarray:
    """Scale to 0-1. A flat vector maps to 0.5 rather than dividing by zero."""
    lo = float(x.min())
    hi = float(x.max())
    if hi - lo < 1e-9:
        return np.full_like(x, 0.5, dtype=np.float32)
    return ((x - lo) / (hi - lo)).astype(np.float32)


def genre_affinity(db: Session, user_id: int) -> dict[str, tuple[float, int, int]]:
    """genre -> (mean rating, total count, count from real user ratings).

    The third element lets the explainer distinguish a genre the user has
    actually rated from one they only picked during onboarding.
    """
    rows = db.execute(
        select(Rating.rating_value, Rating.source, Movie.genres)
        .join(Movie, Movie.movie_id == Rating.movie_id)
        .where(Rating.user_id == user_id)
    ).all()

    totals: dict[str, list[float]] = {}
    real: dict[str, int] = {}
    for value, source, genres in rows:
        for g in (genres or "").split("|"):
            if not g:
                continue
            totals.setdefault(g, []).append(float(value))
            real[g] = real.get(g, 0) + (1 if source == "user" else 0)

    return {
        g: (sum(v) / len(v), len(v), real.get(g, 0)) for g, v in totals.items()
    }


def excluded_movie_ids(db: Session, user_id: int) -> set[int]:
    """Everything the user has rated, watched, or rejected."""
    rated = set(
        db.execute(select(Rating.movie_id).where(Rating.user_id == user_id)).scalars().all()
    )
    suppressed = set(
        db.execute(
            select(WatchlistEntry.movie_id).where(
                WatchlistEntry.user_id == user_id,
                WatchlistEntry.status.in_(["watched", "not_interested"]),
            )
        )
        .scalars()
        .all()
    )
    return rated | suppressed


def _diversify(
    positions: list[int],
    candidate_ids: np.ndarray,
    movies: dict[int, Movie],
    take: int,
) -> list[int]:
    """Greedy pass over score-ordered positions, capping repeats per genre.

    Falls back to plain score order if the cap cannot fill `take` slots.
    """
    picked: list[int] = []
    genre_counts: dict[str, int] = {}

    for pos in positions:
        if len(picked) >= take:
            break
        movie = movies.get(int(candidate_ids[pos]))
        if movie is None:
            continue
        primary = (movie.genre_list or ["Unknown"])[0]
        if genre_counts.get(primary, 0) >= MAX_PER_GENRE:
            continue
        genre_counts[primary] = genre_counts.get(primary, 0) + 1
        picked.append(pos)

    if len(picked) < take:
        for pos in positions:
            if len(picked) >= take:
                break
            if pos not in picked:
                picked.append(pos)

    return picked


def recommend(
    db: Session,
    user: User,
    mood_text: str,
    watching_with: str | None = None,
    time_available: str | None = None,
    top_k: int | None = None,
    exclude_movie_ids: set[int] | None = None,
    diversify: bool = True,
) -> RecommendationResult:
    if not ncf_service.is_loaded or not sbert_service.is_loaded:
        raise RuntimeError("Models are still loading — try again in a moment")

    top_k = top_k or settings.top_k
    # The full catalogue, including films released after the training data.
    candidate_ids = bridge.movie_ids

    # --- the two model scores, both aligned to candidate_ids ---
    trained_ncf, personalised = ncf_service.scores_for(user.ncf_user_index)
    # Trained films keep their real score; the rest borrow one from their
    # nearest trained neighbours in content space.
    raw_ncf = bridge.expand(trained_ncf)
    raw_sbert = sbert_service.similarities(mood_text)

    ncf_norm = _minmax(raw_ncf)
    sbert_norm = _minmax(raw_sbert)
    blended = settings.ncf_weight * ncf_norm + settings.sbert_weight * sbert_norm

    # --- catalogue metadata for the candidates ---
    movies = {
        m.movie_id: m
        # The candidate list is the whole catalogue, so fetch it plainly:
        # an IN clause with thousands of ids is slower and hits statement
        # size limits as the catalogue grows.
        for m in db.execute(select(Movie)).scalars()
    }

    # --- exclusions: rated, watched, rejected, plus anything the caller
    #     already showed (used by "show me 5 more") ---
    seen = excluded_movie_ids(db, user.user_id)
    if exclude_movie_ids:
        seen = seen | {int(m) for m in exclude_movie_ids}

    runtime_cap = TIME_LIMITS.get(time_available or "", None)
    boosts = COMPANY_BOOST.get(watching_with or "", {})

    # Genres the query explicitly asks for. Empty for a vague mood, in which
    # case nothing is gated and the plain hybrid decides.
    mood_terms = explainer.extract_mood_terms(mood_text)
    wanted_genres = set(explainer.implied_genres(mood_terms))

    # `adjusted` is the honest match score shown to the user (blend + viewing
    # context). `genre_boost` steers ranking only, so a boosted film does not
    # display as a saturated 100% match.
    adjusted = blended.copy()
    genre_boost = np.zeros(len(candidate_ids), dtype=np.float32)
    eligible = np.ones(len(candidate_ids), dtype=bool)
    genre_match = np.zeros(len(candidate_ids), dtype=bool)

    for pos, mid in enumerate(candidate_ids):
        movie = movies.get(int(mid))
        if movie is None:
            # In movie2idx but not yet seeded into MySQL.
            eligible[pos] = False
            continue
        if int(mid) in seen:
            eligible[pos] = False
            continue
        # Only enforce the time filter when we actually know the runtime.
        if runtime_cap and movie.runtime_minutes and movie.runtime_minutes > runtime_cap:
            eligible[pos] = False
            continue
        if wanted_genres and any(g in wanted_genres for g in movie.genre_list):
            genre_match[pos] = True
            genre_boost[pos] = GENRE_GATE_BOOST
        if boosts:
            adjusted[pos] += sum(boosts.get(g, 0.0) for g in movie.genre_list)

    if not eligible.any():
        log.warning("No eligible candidates for user %s — filters too tight", user.user_id)
        return RecommendationResult(personalised=personalised)

    # Hard gate: when the query named a genre and enough matching films remain,
    # drop everything off-genre so an explicit request is honoured literally.
    # Too few matches -> keep the gate open and let the boost do the work.
    if wanted_genres:
        gated = eligible & genre_match
        if int(gated.sum()) >= top_k:
            eligible = gated

    # Ranking uses the boost; the displayed score (below) does not.
    scores = np.where(eligible, adjusted + genre_boost, -np.inf)
    take = min(top_k, int(eligible.sum()))

    if diversify:
        # Consider a wider shortlist so the genre cap has room to work.
        pool = min(int(eligible.sum()), max(take * 12, 60))
        shortlist = np.argpartition(-scores, pool - 1)[:pool]
        shortlist = shortlist[np.argsort(-scores[shortlist])]
        top_positions = np.array(
            _diversify([int(p) for p in shortlist], candidate_ids, movies, take)
        )
    else:
        top_positions = np.argpartition(-scores, take - 1)[:take]
        top_positions = top_positions[np.argsort(-scores[top_positions])]

    # --- explanations ---
    affinity = genre_affinity(db, user.user_id)
    # Only genuine ratings count as "your history" in the explanations.
    rating_count = int(
        db.execute(
            select(func.count())
            .select_from(Rating)
            .where(Rating.user_id == user.user_id, Rating.source == "user")
        ).scalar_one()
    )

    items: list[Recommendation] = []
    for rank, pos in enumerate(top_positions, start=1):
        movie = movies[int(candidate_ids[pos])]
        text = explainer.build_explanation(
            title=movie.title,
            genres=movie.genre_list,
            release_year=movie.release_year,
            runtime_minutes=movie.runtime_minutes,
            mood_text=mood_text,
            mood_terms=mood_terms,
            ncf_norm=float(ncf_norm[pos]),
            sbert_norm=float(sbert_norm[pos]),
            personalised=personalised,
            genre_affinity=affinity,
            rating_count=rating_count,
            watching_with=watching_with,
            time_available=time_available,
            model_scored=bool(bridge.trained_mask[pos]),
            seed=user.user_id * 100_003 + int(movie.movie_id),
        )
        items.append(
            Recommendation(
                movie=movie,
                # The honest blend, without the ranking-only genre boost.
                score=float(np.clip(adjusted[pos], 0.0, 1.0)),
                ncf_score=float(ncf_norm[pos]),
                sbert_score=float(sbert_norm[pos]),
                explanation=text,
                rank=rank,
                model_scored=bool(bridge.trained_mask[pos]),
            )
        )

    return RecommendationResult(
        items=items, personalised=personalised, mood_terms=mood_terms
    )
