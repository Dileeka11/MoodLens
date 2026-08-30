"""SQLAlchemy ORM models — mirrors sql/schema.sql exactly."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DECIMAL,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.mysql import TINYINT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(
        Enum("user", "admin", name="user_role"), nullable=False, default="user"
    )

    # NULL until an admin maps this account onto one of the NCF model's
    # 6040 trained user embeddings. See services/recommender.py for the
    # population-prior fallback used while it is NULL.
    ncf_user_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

    onboarded: Mapped[bool] = mapped_column(TINYINT(1), nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.current_timestamp(), nullable=False
    )

    ratings: Mapped[list["Rating"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    recommendations: Mapped[list["Recommendation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_users_role", "role"),)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def has_taste_data(self) -> bool:
        """True once the account has any rating rows — real ratings or the seed
        ratings written when onboarding genres are chosen. Skipping every
        onboarding question leaves this False, so the UI never claims
        recommendations are "tuned to your taste" for a user whose taste is
        still unknown. Distinct from `onboarded`, which only means the flow was
        completed (skipping included)."""
        return bool(self.ratings)


class Movie(Base):
    __tablename__ = "movies"

    # MovieLens movieId — lines up directly with movie2idx.pkl.
    movie_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    tmdb_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    genres: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    # 'movielens' rows are the 3706 the NCF model was trained on. Anything
    # else has no embedding and is scored through the content bridge.
    source: Mapped[str] = mapped_column(
        Enum("movielens", "tmdb", "manual", name="movie_source"),
        nullable=False,
        default="movielens",
    )
    overview: Mapped[str | None] = mapped_column(Text, nullable=True)
    poster_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    release_year: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    runtime_minutes: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    avg_rating: Mapped[Decimal] = mapped_column(
        DECIMAL(3, 2), nullable=False, default=Decimal("0.00")
    )
    rating_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # TMDB's own audience signals — the only quality prior available for
    # films released after the training data ends.
    tmdb_vote_average: Mapped[Decimal | None] = mapped_column(DECIMAL(3, 1), nullable=True)
    tmdb_vote_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tmdb_popularity: Mapped[float | None] = mapped_column(Float, nullable=True)

    ratings: Mapped[list["Rating"]] = relationship(
        back_populates="movie", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_movies_title", "title"),
        Index("ix_movies_year", "release_year"),
    )

    @property
    def genre_list(self) -> list[str]:
        return [g for g in self.genres.split("|") if g]


class Rating(Base):
    __tablename__ = "ratings"

    rating_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    movie_id: Mapped[int] = mapped_column(
        ForeignKey("movies.movie_id", ondelete="CASCADE"), nullable=False
    )
    rating_value: Mapped[Decimal] = mapped_column(DECIMAL(2, 1), nullable=False)
    source: Mapped[str] = mapped_column(
        Enum("user", "onboarding", name="rating_source"), nullable=False, default="user"
    )
    rated_at: Mapped[datetime] = mapped_column(
        server_default=func.current_timestamp(),
        server_onupdate=func.current_timestamp(),
        nullable=False,
    )

    user: Mapped["User"] = relationship(back_populates="ratings")
    movie: Mapped["Movie"] = relationship(back_populates="ratings")

    __table_args__ = (
        UniqueConstraint("user_id", "movie_id", name="uq_ratings_user_movie"),
        CheckConstraint(
            "rating_value >= 0.5 AND rating_value <= 5.0", name="ck_ratings_value"
        ),
        Index("ix_ratings_movie", "movie_id"),
    )


class PasswordReset(Base):
    """One-time password reset token.

    The raw token is emailed and never stored; only its SHA-256 lives here.
    """

    __tablename__ = "password_resets"

    reset_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.current_timestamp(), nullable=False
    )

    user: Mapped["User"] = relationship()

    __table_args__ = (Index("ix_password_resets_user", "user_id", "expires_at"),)


class WatchlistEntry(Base):
    """Saved / watched / not-interested. The last two suppress recommendations."""

    __tablename__ = "watchlist"

    entry_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    movie_id: Mapped[int] = mapped_column(
        ForeignKey("movies.movie_id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        Enum("saved", "watched", "not_interested", name="watchlist_status"),
        nullable=False,
        default="saved",
    )
    added_at: Mapped[datetime] = mapped_column(
        server_default=func.current_timestamp(),
        server_onupdate=func.current_timestamp(),
        nullable=False,
    )

    movie: Mapped["Movie"] = relationship()

    __table_args__ = (
        UniqueConstraint("user_id", "movie_id", name="uq_watchlist_user_movie"),
        Index("ix_watchlist_status", "user_id", "status"),
    )


class Recommendation(Base):
    __tablename__ = "recommendations"

    rec_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    movie_id: Mapped[int] = mapped_column(
        ForeignKey("movies.movie_id", ondelete="CASCADE"), nullable=False
    )
    mood_input: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    ncf_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    sbert_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    rank_position: Mapped[int] = mapped_column(TINYINT, nullable=False, default=1)
    watching_with: Mapped[str | None] = mapped_column(String(20), nullable=True)
    time_available: Mapped[str | None] = mapped_column(String(20), nullable=True)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_at: Mapped[datetime] = mapped_column(
        server_default=func.current_timestamp(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="recommendations")
    movie: Mapped["Movie"] = relationship()

    __table_args__ = (
        Index("ix_recs_user_time", "user_id", "recommended_at"),
        Index("ix_recs_movie", "movie_id"),
    )
