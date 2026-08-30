-- ============================================================
--  MoodLens — MySQL schema
--  Run with:  mysql -u root -p < sql/schema.sql
--  (XAMPP:    "C:\xampp\mysql\bin\mysql.exe" -u root < sql\schema.sql)
-- ============================================================

CREATE DATABASE IF NOT EXISTS moodlens
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE moodlens;

-- Drop in FK-safe order so the script is re-runnable.
DROP TABLE IF EXISTS password_resets;
DROP TABLE IF EXISTS watchlist;
DROP TABLE IF EXISTS recommendations;
DROP TABLE IF EXISTS ratings;
DROP TABLE IF EXISTS movies;
DROP TABLE IF EXISTS users;


-- ------------------------------------------------------------
-- users
-- ------------------------------------------------------------
CREATE TABLE users (
    user_id         INT AUTO_INCREMENT PRIMARY KEY,
    username        VARCHAR(50)  NOT NULL,
    email           VARCHAR(255) NOT NULL,
    password_hash   VARCHAR(255) NOT NULL,
    role            ENUM('user', 'admin') NOT NULL DEFAULT 'user',

    -- Bridge to the pre-trained NCF model, which has a fixed 6040 user
    -- embeddings. App users are NOT MovieLens users, so this is NULL until
    -- an admin maps one. When NULL the recommender falls back to a
    -- population prior (see services/recommender.py).
    ncf_user_index  INT NULL,

    -- Set to 1 once the 5-question onboarding has been completed.
    onboarded       TINYINT(1) NOT NULL DEFAULT 0,

    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uq_users_email (email),
    KEY ix_users_role (role)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ------------------------------------------------------------
-- movies
--   movie_id is the MovieLens movieId, so it lines up directly with
--   movie2idx.pkl and movies.csv. No surrogate key.
-- ------------------------------------------------------------
CREATE TABLE movies (
    movie_id        INT PRIMARY KEY,
    tmdb_id         INT NULL,
    title           VARCHAR(255) NOT NULL,
    genres          VARCHAR(255) NOT NULL DEFAULT '',   -- pipe-separated, e.g. "Action|Sci-Fi"
    -- 'movielens' rows are the 3706 the NCF model was trained on; anything
    -- else is scored through the content bridge (see services/bridge.py).
    source          ENUM('movielens','tmdb','manual') NOT NULL DEFAULT 'movielens',
    overview        TEXT NULL,
    poster_url      VARCHAR(500) NULL,
    release_year    SMALLINT NULL,
    runtime_minutes SMALLINT NULL,                      -- not in movies.csv; admin-editable
    avg_rating      DECIMAL(3,2) NOT NULL DEFAULT 0.00, -- maintained from the ratings table
    rating_count    INT NOT NULL DEFAULT 0,

    -- TMDB audience signals: the only quality prior for post-2000 films.
    tmdb_vote_average DECIMAL(3,1) NULL,
    tmdb_vote_count   INT NULL,
    tmdb_popularity   FLOAT NULL,

    KEY ix_movies_title (title),
    KEY ix_movies_year (release_year),
    KEY ix_movies_source (source),
    KEY ix_movies_tmdb (tmdb_id),
    FULLTEXT KEY ft_movies_search (title, genres)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ------------------------------------------------------------
-- ratings
--   One row per (user, movie). Re-rating updates in place.
--   Onboarding writes seed rows here with source='onboarding'.
-- ------------------------------------------------------------
CREATE TABLE ratings (
    rating_id       INT AUTO_INCREMENT PRIMARY KEY,
    user_id         INT NOT NULL,
    movie_id        INT NOT NULL,
    rating_value    DECIMAL(2,1) NOT NULL,
    source          ENUM('user', 'onboarding') NOT NULL DEFAULT 'user',
    rated_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                       ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uq_ratings_user_movie (user_id, movie_id),
    KEY ix_ratings_movie (movie_id),

    CONSTRAINT fk_ratings_user
        FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE,
    CONSTRAINT fk_ratings_movie
        FOREIGN KEY (movie_id) REFERENCES movies (movie_id) ON DELETE CASCADE,
    CONSTRAINT ck_ratings_value
        CHECK (rating_value >= 0.5 AND rating_value <= 5.0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ------------------------------------------------------------
-- recommendations
--   Every movie returned by POST /recommend is logged here.
--   ncf_score / sbert_score are kept for admin inspection of the
--   0.7 / 0.3 hybrid blend; `score` is the final blended value.
-- ------------------------------------------------------------
CREATE TABLE recommendations (
    rec_id          INT AUTO_INCREMENT PRIMARY KEY,
    user_id         INT NOT NULL,
    movie_id        INT NOT NULL,
    mood_input      TEXT NOT NULL,
    score           FLOAT NOT NULL,
    ncf_score       FLOAT NULL,
    sbert_score     FLOAT NULL,
    rank_position   TINYINT NOT NULL DEFAULT 1,         -- 1..5 within one request
    watching_with   VARCHAR(20) NULL,                   -- Alone / Partner / Family / Friends
    time_available  VARCHAR(20) NULL,                   -- ~1hr / ~2hrs / ~3hrs+
    explanation     TEXT NOT NULL,
    recommended_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    KEY ix_recs_user_time (user_id, recommended_at DESC),
    KEY ix_recs_movie (movie_id),

    CONSTRAINT fk_recs_user
        FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE,
    CONSTRAINT fk_recs_movie
        FOREIGN KEY (movie_id) REFERENCES movies (movie_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ------------------------------------------------------------
-- watchlist
--   saved / watched / not_interested. The latter two are excluded
--   from future recommendations.
-- ------------------------------------------------------------
CREATE TABLE watchlist (
    entry_id    INT AUTO_INCREMENT PRIMARY KEY,
    user_id     INT NOT NULL,
    movie_id    INT NOT NULL,
    status      ENUM('saved', 'watched', 'not_interested') NOT NULL DEFAULT 'saved',
    added_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                   ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uq_watchlist_user_movie (user_id, movie_id),
    KEY ix_watchlist_status (user_id, status),

    CONSTRAINT fk_watchlist_user
        FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE,
    CONSTRAINT fk_watchlist_movie
        FOREIGN KEY (movie_id) REFERENCES movies (movie_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ------------------------------------------------------------
-- password_resets
--   Only the SHA-256 of each token is stored, so a leaked database
--   cannot be used to reset anyone's password.
-- ------------------------------------------------------------
CREATE TABLE password_resets (
    reset_id    INT AUTO_INCREMENT PRIMARY KEY,
    user_id     INT NOT NULL,
    token_hash  CHAR(64) NOT NULL,
    expires_at  DATETIME NOT NULL,
    used_at     DATETIME NULL,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uq_password_resets_hash (token_hash),
    KEY ix_password_resets_user (user_id, expires_at),

    CONSTRAINT fk_password_resets_user
        FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ------------------------------------------------------------
-- Movie rows are loaded from movies.csv by:
--     python -m app.scripts.seed_movies
-- The default admin account is created by:
--     python -m app.scripts.create_admin
-- ------------------------------------------------------------
