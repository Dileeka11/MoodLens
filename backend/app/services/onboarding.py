"""Cold-start onboarding: 5 questions -> an initial taste profile.

Answers are turned into seed rows in the `ratings` table with
source='onboarding', so the profile lives in the schema you already have
rather than a separate preferences table. The explanation generator keeps
these separate from real ratings, so it never says "you rated" about a
film the user only implied they'd like.
"""

from __future__ import annotations

import logging
from decimal import Decimal

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Movie, Rating, User
from app.services.bridge import bridge
from app.services.ncf_service import ncf_service

log = logging.getLogger(__name__)

SEED_RATING = Decimal("4.5")
SEEDS_PER_GENRE = 3
MAX_SEEDS = 12

# Each option carries the genres it implies. Question 3 carries a year range
# instead, used to bias which films get seeded.
QUESTIONS: list[dict] = [
    {
        "id": "q1",
        "question": "What kind of story pulls you in?",
        "options": [
            {"id": "q1a", "label": "Mind-bending sci-fi", "genres": ["Sci-Fi", "Mystery"]},
            {"id": "q1b", "label": "Real human drama", "genres": ["Drama"]},
            {"id": "q1c", "label": "Laugh-out-loud comedy", "genres": ["Comedy"]},
            {"id": "q1d", "label": "Edge-of-seat thriller", "genres": ["Thriller", "Crime"]},
        ],
    },
    {
        "id": "q2",
        "question": "It's Friday night. Pick one.",
        "options": [
            {"id": "q2a", "label": "A horror marathon", "genres": ["Horror"]},
            {"id": "q2b", "label": "A romantic classic", "genres": ["Romance"]},
            {"id": "q2c", "label": "An epic adventure", "genres": ["Adventure", "Fantasy"]},
            {"id": "q2d", "label": "A documentary deep-dive", "genres": ["Documentary"]},
        ],
    },
    {
        "id": "q3",
        "question": "How do you feel about older films?",
        "options": [
            {"id": "q3a", "label": "Love the pre-1980 classics", "years": [1900, 1979]},
            {"id": "q3b", "label": "The 80s and 90s are my sweet spot", "years": [1980, 1999]},
            {"id": "q3c", "label": "I prefer recent films", "years": [1995, 2100]},
            {"id": "q3d", "label": "No preference at all", "years": None},
        ],
    },
    {
        "id": "q4",
        "question": "Who do you usually watch with?",
        "options": [
            {"id": "q4a", "label": "On my own", "genres": []},
            {"id": "q4b", "label": "My partner", "genres": ["Romance", "Drama"]},
            {"id": "q4c", "label": "The whole family", "genres": ["Children's", "Animation"]},
            {"id": "q4d", "label": "Friends", "genres": ["Comedy", "Action"]},
        ],
    },
    {
        "id": "q5",
        "question": "Pick the vibe you reach for most.",
        "options": [
            {"id": "q5a", "label": "Dark and gritty", "genres": ["Film-Noir", "Crime"]},
            {"id": "q5b", "label": "Light and funny", "genres": ["Comedy", "Musical"]},
            {"id": "q5c", "label": "Emotional and moving", "genres": ["Drama", "Romance"]},
            {"id": "q5d", "label": "Fast and thrilling", "genres": ["Action", "Thriller"]},
        ],
    },
]

_OPTION_INDEX = {
    opt["id"]: (q["id"], opt) for q in QUESTIONS for opt in q["options"]
}


def public_questions() -> list[dict]:
    """Questions without the internal genre/year mapping."""
    return [
        {
            "id": q["id"],
            "question": q["question"],
            "options": [{"id": o["id"], "label": o["label"]} for o in q["options"]],
        }
        for q in QUESTIONS
    ]


def parse_answers(answers: dict[str, str]) -> tuple[list[str], tuple[int, int] | None]:
    """-> (preferred genres in priority order, optional year range)."""
    genres: list[str] = []
    years: tuple[int, int] | None = None

    for question_id, option_id in answers.items():
        entry = _OPTION_INDEX.get(option_id)
        if entry is None or entry[0] != question_id:
            continue                      # unknown or mismatched option: ignore
        opt = entry[1]
        for g in opt.get("genres", []) or []:
            if g not in genres:
                genres.append(g)
        if opt.get("years"):
            lo, hi = opt["years"]
            years = (int(lo), int(hi))

    return genres, years


def seed_profile(
    db: Session, user: User, genres: list[str], years: tuple[int, int] | None
) -> int:
    """Write seed ratings for the strongest films in the chosen genres.

    "Strongest" comes from the NCF population prior — the model's own view of
    broad appeal — so the seeds are films the model rates highly rather than an
    arbitrary pick.
    """
    if not genres:
        return 0

    already = set(
        db.execute(select(Rating.movie_id).where(Rating.user_id == user.user_id))
        .scalars()
        .all()
    )

    trained_prior, _ = ncf_service.scores_for(None)
    prior = bridge.expand(trained_prior)
    candidate_ids = bridge.movie_ids
    order = np.argsort(-prior)             # best-scoring candidates first

    movies = {
        m.movie_id: m
        # The candidate list is the whole catalogue, so fetch it plainly:
        # an IN clause with thousands of ids is slower and hits statement
        # size limits as the catalogue grows.
        for m in db.execute(select(Movie)).scalars()
    }

    picked: list[int] = []
    per_genre: dict[str, int] = {g: 0 for g in genres}

    for pos in order:
        if len(picked) >= MAX_SEEDS:
            break
        mid = int(candidate_ids[pos])
        if mid in already or mid in picked:
            continue
        movie = movies.get(mid)
        if movie is None:
            continue
        if years and movie.release_year and not (years[0] <= movie.release_year <= years[1]):
            continue
        for g in movie.genre_list:
            if g in per_genre and per_genre[g] < SEEDS_PER_GENRE:
                per_genre[g] += 1
                picked.append(mid)
                break

    # A narrow year range can starve the pick; retry once without it.
    if not picked and years:
        return seed_profile(db, user, genres, None)

    for mid in picked:
        db.add(
            Rating(
                user_id=user.user_id,
                movie_id=mid,
                rating_value=SEED_RATING,
                source="onboarding",
            )
        )

    log.info("Seeded %d onboarding ratings for user %s", len(picked), user.user_id)
    return len(picked)
