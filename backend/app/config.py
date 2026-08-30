"""Central configuration, loaded from backend/.env (see .env.example)."""

from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- MySQL ---
    db_host: str = "localhost"
    db_port: int = 3306
    db_user: str = "root"
    db_password: str = ""
    db_name: str = "moodlens"

    # --- JWT ---
    jwt_secret: str = "change-me-to-a-long-random-string"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    # --- Artifacts ---
    artifact_dir: str = ".."

    # --- Models / scoring ---
    sbert_model: str = "all-MiniLM-L6-v2"
    ncf_embedding_size: int = 50
    ncf_weight: float = 0.7
    sbert_weight: float = 0.3
    top_k: int = 5

    # --- TMDB (optional, metadata backfill only) ---
    # Free key from https://www.themoviedb.org/settings/api
    # Used solely to fill posters/synopses/runtimes. Recommendations never
    # call an external API.
    tmdb_api_key: str = ""
    tmdb_image_size: str = "w500"

    # --- SMTP (password reset emails) ---
    # Leave smtp_host empty to run without a mail server: emails are logged and
    # written to backend/cache/sent_emails/ instead of being sent.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True          # STARTTLS on 587
    smtp_use_ssl: bool = False         # implicit TLS on 465

    # Where the reset link points. Must match the running frontend.
    app_base_url: str = "http://localhost:5180"
    reset_token_minutes: int = 60

    # --- CORS ---
    frontend_origin: str = "http://localhost:5173"

    @property
    def database_url(self) -> str:
        """SQLAlchemy URL for MySQL via pymysql."""
        return (
            f"mysql+pymysql://{self.db_user}:{quote_plus(self.db_password)}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}?charset=utf8mb4"
        )

    @property
    def artifacts(self) -> Path:
        """Absolute path to the folder holding the .pth / .pkl / movies.csv files."""
        p = Path(self.artifact_dir)
        return p.resolve() if p.is_absolute() else (BACKEND_DIR / p).resolve()

    @property
    def ncf_model_path(self) -> Path:
        return self.artifacts / "ncf_model.pth"

    @property
    def movie2idx_path(self) -> Path:
        return self.artifacts / "movie2idx.pkl"

    @property
    def user2idx_path(self) -> Path:
        return self.artifacts / "user2idx.pkl"

    @property
    def movies_csv_path(self) -> Path:
        return self.artifacts / "movies.csv"

    @property
    def cache_dir(self) -> Path:
        """Where the SBERT genre/title embedding cache is written."""
        d = BACKEND_DIR / "cache"
        d.mkdir(exist_ok=True)
        return d


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
