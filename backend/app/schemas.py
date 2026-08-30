"""Pydantic request/response models."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

WatchingWith = Literal["Alone", "Partner", "Family", "Friends"]
TimeAvailable = Literal["~1hr", "~2hrs", "~3hrs+"]


# --------------------------------------------------------------- auth

class RegisterRequest(BaseModel):
    username: str = Field(min_length=2, max_length=50)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ForgotPasswordResponse(BaseModel):
    message: str
    # False when SMTP is unconfigured and the email was only logged to disk.
    email_sent: bool


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=16, max_length=128)
    new_password: str = Field(min_length=8, max_length=72)


class SimpleMessage(BaseModel):
    message: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    username: str
    email: EmailStr
    role: str
    onboarded: bool
    # True only when the account actually has taste signal (real ratings or
    # onboarding seeds), not merely that the onboarding flow was completed.
    has_taste_data: bool
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# -------------------------------------------------------------- movies

class MovieSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    movie_id: int
    title: str
    genres: str
    source: str = "movielens"
    release_year: int | None = None
    runtime_minutes: int | None = None
    poster_url: str | None = None
    avg_rating: Decimal
    rating_count: int


class MovieDetail(MovieSummary):
    tmdb_id: int | None = None
    overview: str | None = None
    your_rating: Decimal | None = None
    last_explanation: str | None = None
    # True when the NCF checkpoint knows this film directly. False means its
    # score is estimated through the content bridge — still recommendable.
    in_ncf_model: bool = True


# ----------------------------------------------------------- recommend

class RecommendRequest(BaseModel):
    mood_text: str = Field(min_length=3, max_length=1000)
    watching_with: WatchingWith | None = None
    time_available: TimeAvailable | None = None
    # Ids already shown in this session, so "Show me 5 more" returns new films.
    exclude_movie_ids: list[int] = Field(default_factory=list, max_length=200)

    @field_validator("mood_text")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("mood_text cannot be blank")
        return v


class RecommendationOut(BaseModel):
    rec_id: int | None = None
    rank: int
    movie: MovieSummary
    score: float
    ncf_score: float
    sbert_score: float
    explanation: str
    # "model" when the NCF checkpoint scored this film directly; "estimated"
    # when it is newer than the training data and the score was borrowed from
    # similar films via the content bridge.
    score_source: Literal["model", "estimated"] = "model"



class RecommendResponse(BaseModel):
    mood_text: str
    mood_terms: list[str]
    personalised: bool
    results: list[RecommendationOut]


# --------------------------------------------------------- onboarding

class OnboardingOption(BaseModel):
    id: str
    label: str


class OnboardingQuestion(BaseModel):
    id: str
    question: str
    options: list[OnboardingOption]


class OnboardingRequest(BaseModel):
    # question id -> chosen option id. Skipped questions are simply absent.
    answers: dict[str, str] = Field(default_factory=dict)


class OnboardingResponse(BaseModel):
    onboarded: bool
    seeded_movies: int
    preferred_genres: list[str]
    message: str


# ------------------------------------------------------------- ratings

class RateRequest(BaseModel):
    movie_id: int
    rating_value: Decimal = Field(ge=Decimal("0.5"), le=Decimal("5.0"))

    @field_validator("rating_value")
    @classmethod
    def half_steps(cls, v: Decimal) -> Decimal:
        if (v * 2) % 1 != 0:
            raise ValueError("rating_value must be in steps of 0.5")
        return v


class RatingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rating_id: int
    movie_id: int
    rating_value: Decimal
    rated_at: datetime


# ------------------------------------------------------------- history

class HistoryItem(BaseModel):
    rec_id: int
    mood_input: str
    score: float
    explanation: str
    recommended_at: datetime
    movie: MovieSummary


class HistoryResponse(BaseModel):
    total: int
    items: list[HistoryItem]


# ----------------------------------------------------------- watchlist

WatchStatus = Literal["saved", "watched", "not_interested"]


class WatchlistRequest(BaseModel):
    movie_id: int
    status: WatchStatus = "saved"


class WatchlistItem(BaseModel):
    entry_id: int
    status: WatchStatus
    added_at: datetime
    movie: MovieSummary


# ------------------------------------------------------------- discovery

class SimilarMovie(BaseModel):
    movie: MovieSummary
    similarity: float


class BrowseResponse(BaseModel):
    total: int
    page: int
    per_page: int
    items: list[MovieSummary]


# --------------------------------------------------------- taste profile

class GenreAffinityOut(BaseModel):
    genre: str
    count: int
    rated_count: int
    avg_rating: float


class RatingBucket(BaseModel):
    stars: str
    count: int


class DecadeBucket(BaseModel):
    decade: str
    count: int


class MoodWord(BaseModel):
    word: str
    count: int


class TasteProfile(BaseModel):
    total_ratings: int
    onboarding_seeds: int
    average_rating: float | None
    total_searches: int
    top_genres: list[GenreAffinityOut]
    rating_distribution: list[RatingBucket]
    decades: list[DecadeBucket]
    mood_words: list[MoodWord]


# ---------------------------------------------------------- evaluation

class EvaluationResult(BaseModel):
    available: bool
    reason: str | None = None
    source_file: str | None = None
    k: int | None = None
    ratings_evaluated: int | None = None
    ratings_in_file: int | None = None
    users_evaluated: int | None = None
    rmse: float | None = None
    mae: float | None = None
    precision_at_k: float | None = None
    recall_at_k: float | None = None
    ndcg_at_k: float | None = None
    relevance_threshold: float | None = None
    took_seconds: float | None = None
    note: str | None = None


# --------------------------------------------------------------- admin

class AdminStats(BaseModel):
    users: int
    movies: int
    ratings: int
    recommendations: int


class MovieCreate(BaseModel):
    movie_id: int | None = None
    title: str = Field(min_length=1, max_length=255)
    genres: str = Field(default="", max_length=255)
    tmdb_id: int | None = None
    overview: str | None = None
    poster_url: str | None = Field(default=None, max_length=500)
    release_year: int | None = Field(default=None, ge=1870, le=2100)
    runtime_minutes: int | None = Field(default=None, ge=1, le=1000)


class MovieUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    genres: str | None = Field(default=None, max_length=255)
    tmdb_id: int | None = None
    overview: str | None = None
    poster_url: str | None = Field(default=None, max_length=500)
    release_year: int | None = Field(default=None, ge=1870, le=2100)
    runtime_minutes: int | None = Field(default=None, ge=1, le=1000)


class AdminUserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=50)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    role: Literal["user", "admin"] = "user"
    ncf_user_index: int | None = None


class PaginatedMovies(BaseModel):
    total: int
    page: int
    per_page: int
    items: list[MovieSummary]


class PaginatedUsers(BaseModel):
    total: int
    page: int
    per_page: int
    items: list[UserOut]


class ModelInfo(BaseModel):
    ncf_loaded: bool
    sbert_loaded: bool
    num_users: int
    num_movies: int
    candidates: int
    trained_movies: int | None = None
    estimated_movies: int | None = None
    sbert_model: str
    sbert_dim: int
    last_trained: str | None = None
    rmse: float | None = None
    evaluated_at: str | None = None
    evaluated_on_ratings: int | None = None
    note: str | None = None
