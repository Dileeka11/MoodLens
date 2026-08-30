"""Fill posters, synopses and runtimes from TMDB.

    python -m app.scripts.backfill_tmdb                # everything missing
    python -m app.scripts.backfill_tmdb --limit 50     # try a small batch first
    python -m app.scripts.backfill_tmdb --force        # re-fetch even if present

Needs a free TMDB key in backend/.env as TMDB_API_KEY
(https://www.themoviedb.org/settings/api).

This is the ONLY part of MoodLens that talks to an external service, and it
only fetches catalogue metadata — recommendations are always computed locally.
The script is resumable: it skips rows that already have a tmdb_id, so it can
be stopped and re-run.
"""

from __future__ import annotations

import argparse
import re
import sys
import time

import requests
from sqlalchemy import or_, select

from app.config import settings
from app.database import SessionLocal
from app.models import Movie

SEARCH_URL = "https://api.themoviedb.org/3/search/movie"
DETAIL_URL = "https://api.themoviedb.org/3/movie/{id}"
IMAGE_BASE = "https://image.tmdb.org/t/p/"

# TMDB allows ~50 requests/second; this is well under it and stays polite.
DELAY = 0.06
TIMEOUT = 15

# MovieLens moves the leading article to the end: "Matrix, The".
ARTICLES = {
    "the", "a", "an", "la", "le", "les", "il", "el", "los", "las",
    "der", "die", "das", "l'", "un", "una", "une",
}

YEAR_RE = re.compile(r"\((\d{4})\)\s*$")
PAREN_RE = re.compile(r"\(([^)]*)\)")
AKA_RE = re.compile(r"^(a\.?k\.?a\.?|aka|also known as)\s*:?\s*", re.I)


def parse_title(raw: str) -> tuple[list[str], int | None]:
    """MovieLens title -> (candidate query titles, year).

    "Matrix, The (1999)"                        -> (["The Matrix"], 1999)
    "Nikita (La Femme Nikita) (1990)"           -> (["Nikita", "La Femme Nikita"], 1990)
    "City of Lost Children, The (Cite..., La)"  -> (["The City of Lost Children", ...])
    """
    title = (raw or "").strip()

    year = None
    m = YEAR_RE.search(title)
    if m:
        year = int(m.group(1))
        title = YEAR_RE.sub("", title).strip()

    # Alternate titles live in parentheses and make good fallback queries.
    # Strip the "a.k.a." marker, which is not part of the title and turns
    # "Citizen's Band (a.k.a. Handle with Care)" into a useless query.
    alternates = []
    for a in PAREN_RE.findall(title):
        a = AKA_RE.sub("", a.strip()).strip()
        if a:
            alternates.append(a)
    primary = PAREN_RE.sub("", title).strip()

    candidates = [fix_article(t) for t in [primary, *alternates] if t]
    # De-duplicate while keeping order.
    seen: list[str] = []
    for c in candidates:
        if c and c not in seen:
            seen.append(c)
    return seen, year


def fix_article(title: str) -> str:
    """'Matrix, The' -> 'The Matrix'. Leaves other commas alone."""
    if "," not in title:
        return title.strip()
    head, _, tail = title.rpartition(",")
    tail = tail.strip()
    if tail.lower() in ARTICLES:
        joiner = "" if tail.lower().endswith("'") else " "
        return f"{tail}{joiner}{head.strip()}"
    return title.strip()


def pick_best(results: list[dict], titles: list[str], year: int | None) -> dict | None:
    """Choose the closest result from a pool gathered across all query titles.

    Two failure modes drove this design:
      * Taking TMDB's first result matched "Hate (Haine, La) (1995)" — a
        98-minute film — to a 6-minute short of the same name.
      * Accepting the first *candidate title* meant the alternate title
        ("La Haine") was never tried once "Hate" returned anything at all.
    Vote count is the strongest signal available: the real film has thousands of
    votes, a same-named short has a handful.
    """
    if not results:
        return None

    wanted = {t.strip().lower() for t in titles}

    def result_year(r: dict) -> int | None:
        date = r.get("release_date") or ""
        return int(date[:4]) if date[:4].isdigit() else None

    def score(r: dict) -> tuple:
        ry = result_year(r)
        votes = r.get("vote_count") or 0
        exact_title = (r.get("title") or "").strip().lower() in wanted
        exact_original = (r.get("original_title") or "").strip().lower() in wanted
        exact_year = year is not None and ry == year
        close_year = year is not None and ry is not None and abs(ry - year) <= 1

        # A title+year match on an obscure record loses to a well-known film:
        # obscure same-name shorts are exactly what went wrong before.
        credible = votes >= 50
        return (
            (exact_title or exact_original) and close_year and credible,
            credible and close_year,
            exact_title or exact_original,
            exact_year,
            votes,
        )

    return max(results, key=score)


def search(session: requests.Session, title: str, year: int | None) -> list[dict]:
    """Raw TMDB search results for one title. Ranking happens in pick_best."""
    params = {"api_key": settings.tmdb_api_key, "query": title}
    if year:
        params["year"] = year

    try:
        r = session.get(SEARCH_URL, params=params, timeout=TIMEOUT)
    except requests.RequestException as exc:
        print(f"    network error: {exc}")
        return []

    if r.status_code == 401:
        sys.exit("TMDB rejected the API key. Check TMDB_API_KEY in backend/.env")
    if r.status_code == 429:
        print("    rate limited, sleeping 5s")
        time.sleep(5)
        return []
    if r.status_code != 200:
        return []

    return r.json().get("results") or []


def search_pool(
    session: requests.Session, titles: list[str], year: int | None
) -> list[dict]:
    """Every result across all candidate titles, with and without the year."""
    pool: dict[int, dict] = {}
    for title in titles:
        for use_year in (year, None):
            for r in search(session, title, use_year):
                if r.get("id") is not None:
                    pool.setdefault(r["id"], r)
            time.sleep(DELAY)
            if use_year is None:
                break
    return list(pool.values())


def fetch_detail(session: requests.Session, tmdb_id: int) -> dict | None:
    try:
        r = session.get(
            DETAIL_URL.format(id=tmdb_id),
            params={"api_key": settings.tmdb_api_key},
            timeout=TIMEOUT,
        )
    except requests.RequestException:
        return None
    return r.json() if r.status_code == 200 else None


def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill movie metadata from TMDB")
    ap.add_argument("--limit", type=int, default=None, help="only process N movies")
    ap.add_argument("--force", action="store_true", help="re-fetch rows that already have data")
    ap.add_argument(
        "--refetch-short",
        type=int,
        default=None,
        metavar="MINUTES",
        help="re-check films whose stored runtime is below MINUTES (likely bad matches)",
    )
    args = ap.parse_args()

    if not settings.tmdb_api_key:
        sys.exit(
            "No TMDB_API_KEY in backend/.env\n"
            "Get a free key at https://www.themoviedb.org/settings/api, then add:\n"
            "  TMDB_API_KEY=your_key_here"
        )

    session = requests.Session()

    with SessionLocal() as db:
        stmt = select(Movie).order_by(Movie.movie_id)
        if args.refetch_short:
            stmt = stmt.where(
                Movie.runtime_minutes.is_not(None),
                Movie.runtime_minutes < args.refetch_short,
            )
        elif not args.force:
            # Resumable: anything without a tmdb_id still needs a look.
            stmt = stmt.where(or_(Movie.tmdb_id.is_(None), Movie.poster_url.is_(None)))
        if args.limit:
            stmt = stmt.limit(args.limit)

        movies = list(db.execute(stmt).scalars())
        print(f"{len(movies)} movies to process\n")

        found = missing = 0
        for i, movie in enumerate(movies, start=1):
            titles, year = parse_title(movie.title)

            hit = pick_best(search_pool(session, titles, year), titles, year)

            if not hit:
                missing += 1
                print(f"[{i}/{len(movies)}] MISS  {movie.title}")
                continue

            detail = fetch_detail(session, hit["id"])
            time.sleep(DELAY)

            movie.tmdb_id = hit["id"]
            if hit.get("poster_path"):
                movie.poster_url = f"{IMAGE_BASE}{settings.tmdb_image_size}{hit['poster_path']}"
            if hit.get("overview"):
                movie.overview = hit["overview"]
            if detail and detail.get("runtime"):
                movie.runtime_minutes = int(detail["runtime"])

            found += 1
            runtime = f"{movie.runtime_minutes}m" if movie.runtime_minutes else "no runtime"
            print(f"[{i}/{len(movies)}] ok    {movie.title}  ({runtime})")

            if i % 25 == 0:
                db.commit()

        db.commit()

    print(f"\nDone. matched {found}, missed {missing}.")
    print("Restart the backend so the catalogue reloads.")


if __name__ == "__main__":
    main()
