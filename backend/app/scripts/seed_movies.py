"""Load movies.csv into the `movies` table.

Run from the backend/ directory:
    python -m app.scripts.seed_movies

Idempotent — re-running updates existing rows instead of duplicating them.
MovieLens titles embed the year ("Toy Story (1995)"), so release_year is
parsed out and the title is left intact for display.
"""

import csv
import re
import sys

from sqlalchemy.dialects.mysql import insert as mysql_insert

from app.config import settings
from app.database import SessionLocal, engine
from app.models import Movie

YEAR_RE = re.compile(r"\((\d{4})\)\s*$")
BATCH = 500


def parse_year(title: str) -> int | None:
    """'Toy Story (1995)' -> 1995. Returns None when the title has no year."""
    m = YEAR_RE.search(title.strip())
    if not m:
        return None
    year = int(m.group(1))
    return year if 1870 <= year <= 2100 else None


def load_rows() -> list[dict]:
    path = settings.movies_csv_path
    if not path.exists():
        sys.exit(f"movies.csv not found at {path}\nCheck ARTIFACT_DIR in backend/.env")

    rows: list[dict] = []
    with path.open(encoding="utf-8", newline="") as fh:
        for raw in csv.DictReader(fh):
            try:
                movie_id = int(raw["movieId"])
            except (KeyError, TypeError, ValueError):
                continue

            title = (raw.get("title") or "").strip()
            if not title:
                continue

            genres = (raw.get("genres") or "").strip()
            if genres == "(no genres listed)":
                genres = ""

            rows.append(
                {
                    "movie_id": movie_id,
                    "title": title[:255],
                    "genres": genres[:255],
                    "release_year": parse_year(title),
                }
            )
    return rows


def main() -> None:
    rows = load_rows()
    print(f"Parsed {len(rows)} movies from {settings.movies_csv_path}")

    with SessionLocal() as db:
        for i in range(0, len(rows), BATCH):
            chunk = rows[i : i + BATCH]
            stmt = mysql_insert(Movie).values(chunk)
            # Refresh the CSV-derived columns; leave admin-entered fields
            # (overview, poster_url, runtime_minutes, tmdb_id) and the
            # ratings-derived aggregates untouched.
            stmt = stmt.on_duplicate_key_update(
                title=stmt.inserted.title,
                genres=stmt.inserted.genres,
                release_year=stmt.inserted.release_year,
            )
            db.execute(stmt)
            db.commit()
            print(f"  upserted {min(i + BATCH, len(rows))}/{len(rows)}", end="\r")

    with engine.connect() as conn:
        from sqlalchemy import func, select

        total = conn.execute(select(func.count()).select_from(Movie.__table__)).scalar()
        with_year = conn.execute(
            select(func.count()).select_from(Movie.__table__).where(
                Movie.release_year.is_not(None)
            )
        ).scalar()

    print(f"\nDone. movies table now holds {total} rows ({with_year} with a release year).")


if __name__ == "__main__":
    main()
