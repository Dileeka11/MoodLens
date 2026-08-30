"""Import films released after the MovieLens data ends (2000).

    python -m app.scripts.import_recent                      # 2001 -> current year
    python -m app.scripts.import_recent --from 2015 --to 2026
    python -m app.scripts.import_recent --min-votes 1000     # only well-known films

Needs TMDB_API_KEY in backend/.env.

These films are NOT in the NCF checkpoint, so they are stored with
source='tmdb' and scored through the content bridge (services/bridge.py),
which borrows a score from their nearest trained neighbours. Nothing here
retrains the model.

New ids start at 100000 so they can never collide with a MovieLens movieId.
Restart the backend afterwards: the catalogue and the bridge are built once at
startup.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date

import requests
from sqlalchemy import func, select

from app.config import settings
from app.database import SessionLocal
from app.models import Movie

DISCOVER_URL = "https://api.themoviedb.org/3/discover/movie"
GENRE_URL = "https://api.themoviedb.org/3/genre/movie/list"
DETAIL_URL = "https://api.themoviedb.org/3/movie/{id}"
IMAGE_BASE = "https://image.tmdb.org/t/p/"

ID_BASE = 100_000          # keeps imported ids clear of MovieLens (max 3952)
DELAY = 0.06
TIMEOUT = 20
MAX_PAGES = 500            # TMDB refuses page > 500

# TMDB's genre names mapped onto the 18 MovieLens labels the rest of the app
# uses. Anything unmapped is dropped rather than inventing a 19th genre that
# the mood lexicon and the Family filter know nothing about.
GENRE_MAP = {
    "Action": "Action",
    "Adventure": "Adventure",
    "Animation": "Animation",
    "Comedy": "Comedy",
    "Crime": "Crime",
    "Documentary": "Documentary",
    "Drama": "Drama",
    "Family": "Children's",
    "Fantasy": "Fantasy",
    "History": "Drama",
    "Horror": "Horror",
    "Music": "Musical",
    "Mystery": "Mystery",
    "Romance": "Romance",
    "Science Fiction": "Sci-Fi",
    "Thriller": "Thriller",
    "War": "War",
    "Western": "Western",
    "TV Movie": "Drama",
}


def fetch_genre_names(session: requests.Session) -> dict[int, str]:
    r = session.get(
        GENRE_URL, params={"api_key": settings.tmdb_api_key}, timeout=TIMEOUT
    )
    if r.status_code == 401:
        sys.exit("TMDB rejected the API key. Check TMDB_API_KEY in backend/.env")
    r.raise_for_status()
    return {g["id"]: g["name"] for g in r.json().get("genres", [])}


def to_movielens_genres(genre_ids: list[int], names: dict[int, str]) -> str:
    out: list[str] = []
    for gid in genre_ids or []:
        mapped = GENRE_MAP.get(names.get(gid, ""))
        if mapped and mapped not in out:
            out.append(mapped)
    return "|".join(out)


def discover(session: requests.Session, year: int, page: int, min_votes: int) -> dict:
    params = {
        "api_key": settings.tmdb_api_key,
        "primary_release_year": year,
        "page": page,
        "sort_by": "vote_count.desc",     # best-known first, so a --limit is meaningful
        "vote_count.gte": min_votes,
        "include_adult": "false",
        "language": "en-US",
    }
    r = session.get(DISCOVER_URL, params=params, timeout=TIMEOUT)
    if r.status_code == 401:
        sys.exit("TMDB rejected the API key. Check TMDB_API_KEY in backend/.env")
    if r.status_code == 429:
        print("    rate limited, sleeping 5s")
        time.sleep(5)
        return {"results": [], "total_pages": 0}
    if r.status_code != 200:
        return {"results": [], "total_pages": 0}
    return r.json()


def fetch_runtime(session: requests.Session, tmdb_id: int) -> int | None:
    try:
        r = session.get(
            DETAIL_URL.format(id=tmdb_id),
            params={"api_key": settings.tmdb_api_key},
            timeout=TIMEOUT,
        )
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    runtime = r.json().get("runtime")
    return int(runtime) if runtime else None


def main() -> None:
    this_year = date.today().year
    ap = argparse.ArgumentParser(description="Import post-2000 films from TMDB")
    ap.add_argument("--from", dest="year_from", type=int, default=2001)
    ap.add_argument("--to", dest="year_to", type=int, default=this_year)
    ap.add_argument(
        "--min-votes",
        type=int,
        default=300,
        help="skip films with fewer TMDB votes (default 300, keeps obscure titles out)",
    )
    ap.add_argument("--per-year", type=int, default=200, help="cap films imported per year")
    ap.add_argument("--no-runtime", action="store_true", help="skip the extra runtime lookup")
    args = ap.parse_args()

    if not settings.tmdb_api_key:
        sys.exit(
            "No TMDB_API_KEY in backend/.env\n"
            "Get a free key at https://www.themoviedb.org/settings/api"
        )

    session = requests.Session()
    genre_names = fetch_genre_names(session)
    print(f"TMDB genres loaded ({len(genre_names)})")

    with SessionLocal() as db:
        existing_tmdb = {
            int(t)
            for t in db.execute(select(Movie.tmdb_id).where(Movie.tmdb_id.is_not(None)))
            .scalars()
            .all()
        }
        next_id = max(
            ID_BASE,
            int(db.execute(select(func.max(Movie.movie_id))).scalar() or 0) + 1,
        )
        print(f"{len(existing_tmdb)} films already have a TMDB id; new ids start at {next_id}\n")

        added = skipped = 0

        for year in range(args.year_from, args.year_to + 1):
            year_added = 0
            page = 1

            while year_added < args.per_year and page <= MAX_PAGES:
                data = discover(session, year, page, args.min_votes)
                results = data.get("results") or []
                if not results:
                    break

                for item in results:
                    if year_added >= args.per_year:
                        break

                    tmdb_id = item.get("id")
                    title = (item.get("title") or "").strip()
                    if not tmdb_id or not title:
                        continue
                    if int(tmdb_id) in existing_tmdb:
                        skipped += 1
                        continue

                    genres = to_movielens_genres(item.get("genre_ids"), genre_names)
                    runtime = None if args.no_runtime else fetch_runtime(session, tmdb_id)
                    if not args.no_runtime:
                        time.sleep(DELAY)

                    poster = item.get("poster_path")
                    db.add(
                        Movie(
                            movie_id=next_id,
                            tmdb_id=int(tmdb_id),
                            # Kept in the MovieLens "Title (year)" shape so the
                            # UI and the SBERT corpus builder behave identically
                            # for imported and original rows.
                            title=f"{title} ({year})"[:255],
                            genres=genres[:255],
                            source="tmdb",
                            overview=item.get("overview") or None,
                            poster_url=(
                                f"{IMAGE_BASE}{settings.tmdb_image_size}{poster}"
                                if poster
                                else None
                            ),
                            release_year=year,
                            runtime_minutes=runtime,
                            tmdb_vote_average=item.get("vote_average"),
                            tmdb_vote_count=item.get("vote_count"),
                            tmdb_popularity=item.get("popularity"),
                        )
                    )
                    existing_tmdb.add(int(tmdb_id))
                    next_id += 1
                    added += 1
                    year_added += 1

                db.commit()
                if page >= (data.get("total_pages") or 1):
                    break
                page += 1
                time.sleep(DELAY)

            print(f"  {year}: +{year_added}")

        db.commit()

    print(f"\nDone. added {added}, skipped {skipped} already present.")
    print("Restart the backend so the catalogue and content bridge rebuild:")
    print("    npm run dev")


if __name__ == "__main__":
    main()
