"""Background TMDB sync jobs — triggered from the admin panel.

Two jobs:
  posters  — fill poster_url / overview / runtime for existing MovieLens rows
  recent   — import post-2000 films from TMDB Discover
"""

from __future__ import annotations

import logging
import re
import threading
import time
from datetime import date, datetime, timezone
from typing import Any

import requests
from sqlalchemy import func, or_, select

from app.config import settings
from app.database import SessionLocal
from app.models import Movie

log = logging.getLogger(__name__)

# ── TMDB constants ────────────────────────────────────────────────────────────

SEARCH_URL   = "https://api.themoviedb.org/3/search/movie"
DETAIL_URL   = "https://api.themoviedb.org/3/movie/{id}"
DISCOVER_URL = "https://api.themoviedb.org/3/discover/movie"
GENRE_URL    = "https://api.themoviedb.org/3/genre/movie/list"
IMAGE_BASE   = "https://image.tmdb.org/t/p/"
DELAY        = 0.06
TIMEOUT      = 15
MAX_PAGES    = 500
ID_BASE      = 100_000

ARTICLES = {
    "the", "a", "an", "la", "le", "les", "il", "el", "los", "las",
    "der", "die", "das", "l'", "un", "una", "une",
}
YEAR_RE  = re.compile(r"\((\d{4})\)\s*$")
PAREN_RE = re.compile(r"\(([^)]*)\)")
AKA_RE   = re.compile(r"^(a\.?k\.?a\.?|aka|also known as)\s*:?\s*", re.I)

GENRE_MAP = {
    "Action": "Action", "Adventure": "Adventure", "Animation": "Animation",
    "Comedy": "Comedy", "Crime": "Crime", "Documentary": "Documentary",
    "Drama": "Drama", "Family": "Children's", "Fantasy": "Fantasy",
    "History": "Drama", "Horror": "Horror", "Music": "Musical",
    "Mystery": "Mystery", "Romance": "Romance", "Science Fiction": "Sci-Fi",
    "Thriller": "Thriller", "War": "War", "Western": "Western",
    "TV Movie": "Drama",
}

# ── status tracking ───────────────────────────────────────────────────────────

_lock = threading.Lock()
_state: dict[str, Any] = {
    "posters": {
        "running": False, "done": 0, "total": 0,
        "matched": 0, "missed": 0,
        "finished_at": None, "error": None,
    },
    "recent": {
        "running": False, "done": 0, "total": 0,
        "added": 0, "skipped": 0,
        "finished_at": None, "error": None,
    },
}


def get_status() -> dict:
    with _lock:
        return {k: dict(v) for k, v in _state.items()}


def _set(kind: str, **kwargs: Any) -> None:
    with _lock:
        _state[kind].update(kwargs)


# ── shared TMDB helpers ───────────────────────────────────────────────────────

def _fix_article(title: str) -> str:
    if "," not in title:
        return title.strip()
    head, _, tail = title.rpartition(",")
    tail = tail.strip()
    if tail.lower() in ARTICLES:
        joiner = "" if tail.lower().endswith("'") else " "
        return f"{tail}{joiner}{head.strip()}"
    return title.strip()


def _parse_title(raw: str) -> tuple[list[str], int | None]:
    title = (raw or "").strip()
    year: int | None = None
    m = YEAR_RE.search(title)
    if m:
        year = int(m.group(1))
        title = YEAR_RE.sub("", title).strip()
    alternates = []
    for alt in PAREN_RE.findall(title):
        alt = AKA_RE.sub("", alt.strip()).strip()
        if alt:
            alternates.append(alt)
    primary = PAREN_RE.sub("", title).strip()
    seen: list[str] = []
    for c in [_fix_article(t) for t in [primary, *alternates] if t]:
        if c and c not in seen:
            seen.append(c)
    return seen, year


def _tmdb_search(session: requests.Session, title: str, year: int | None) -> list[dict]:
    params: dict = {"api_key": settings.tmdb_api_key, "query": title}
    if year:
        params["year"] = year
    try:
        r = session.get(SEARCH_URL, params=params, timeout=TIMEOUT)
    except requests.RequestException as exc:
        log.warning("TMDB search error: %s", exc)
        return []
    if r.status_code == 401:
        raise RuntimeError("TMDB API key rejected")
    if r.status_code == 429:
        time.sleep(5)
        return []
    if r.status_code != 200:
        return []
    return r.json().get("results") or []


def _search_pool(session: requests.Session, titles: list[str], year: int | None) -> list[dict]:
    pool: dict[int, dict] = {}
    for title in titles:
        for use_year in (year, None):
            for r in _tmdb_search(session, title, use_year):
                if r.get("id") is not None:
                    pool.setdefault(r["id"], r)
            time.sleep(DELAY)
            if use_year is None:
                break
    return list(pool.values())


def _pick_best(results: list[dict], titles: list[str], year: int | None) -> dict | None:
    if not results:
        return None
    wanted = {t.strip().lower() for t in titles}

    def ry(r: dict) -> int | None:
        d = r.get("release_date") or ""
        return int(d[:4]) if d[:4].isdigit() else None

    def key(r: dict) -> tuple:
        ryear = ry(r)
        votes = r.get("vote_count") or 0
        et = (r.get("title") or "").strip().lower() in wanted
        eo = (r.get("original_title") or "").strip().lower() in wanted
        ey = year is not None and ryear == year
        cy = year is not None and ryear is not None and abs(ryear - year) <= 1
        credible = votes >= 50
        return ((et or eo) and cy and credible, credible and cy, et or eo, ey, votes)

    return max(results, key=key)


def _fetch_detail(session: requests.Session, tmdb_id: int) -> dict | None:
    try:
        r = session.get(
            DETAIL_URL.format(id=tmdb_id),
            params={"api_key": settings.tmdb_api_key},
            timeout=TIMEOUT,
        )
    except requests.RequestException:
        return None
    return r.json() if r.status_code == 200 else None


# ── job: poster backfill ──────────────────────────────────────────────────────

def run_poster_sync() -> None:
    """Fill poster_url / overview / runtime for rows that are still missing them."""
    kind = "posters"
    if not settings.tmdb_api_key:
        _set(kind, running=False, error="TMDB_API_KEY not configured in .env")
        return

    _set(kind, running=True, done=0, total=0, matched=0, missed=0, error=None, finished_at=None)
    try:
        session = requests.Session()
        with SessionLocal() as db:
            movies = list(
                db.execute(
                    select(Movie).where(
                        or_(Movie.tmdb_id.is_(None), Movie.poster_url.is_(None))
                    ).order_by(Movie.movie_id)
                ).scalars()
            )
            _set(kind, total=len(movies))

            matched = missed = 0
            for i, movie in enumerate(movies, 1):
                titles, year = _parse_title(movie.title)
                hit = _pick_best(_search_pool(session, titles, year), titles, year)
                if not hit:
                    missed += 1
                else:
                    detail = _fetch_detail(session, hit["id"])
                    time.sleep(DELAY)
                    movie.tmdb_id = hit["id"]
                    if hit.get("poster_path"):
                        movie.poster_url = f"{IMAGE_BASE}{settings.tmdb_image_size}{hit['poster_path']}"
                    if hit.get("overview"):
                        movie.overview = hit["overview"]
                    if detail and detail.get("runtime"):
                        movie.runtime_minutes = int(detail["runtime"])
                    matched += 1

                _set(kind, done=i, matched=matched, missed=missed)
                if i % 25 == 0:
                    db.commit()

            db.commit()

    except Exception as exc:
        log.exception("Poster sync failed")
        _set(kind, running=False, error=str(exc), finished_at=_now())
        return

    _set(kind, running=False, finished_at=_now())
    log.info("Poster sync done: matched=%d missed=%d", matched, missed)


# ── job: recent movie import ──────────────────────────────────────────────────

def run_recent_sync(
    year_from: int = 2001,
    min_votes: int = 300,
    per_year: int = 200,
) -> None:
    """Import post-2000 films from TMDB Discover into the catalogue."""
    kind = "recent"
    if not settings.tmdb_api_key:
        _set(kind, running=False, error="TMDB_API_KEY not configured in .env")
        return

    this_year = date.today().year
    _set(kind, running=True, done=0, total=0, added=0, skipped=0, error=None, finished_at=None)
    try:
        session = requests.Session()

        r = session.get(GENRE_URL, params={"api_key": settings.tmdb_api_key}, timeout=TIMEOUT)
        if r.status_code == 401:
            raise RuntimeError("TMDB API key rejected")
        r.raise_for_status()
        genre_names: dict[int, str] = {g["id"]: g["name"] for g in r.json().get("genres", [])}

        with SessionLocal() as db:
            existing_tmdb = {
                int(t)
                for t in db.execute(
                    select(Movie.tmdb_id).where(Movie.tmdb_id.is_not(None))
                ).scalars().all()
            }
            next_id = max(
                ID_BASE,
                int(db.execute(select(func.max(Movie.movie_id))).scalar() or 0) + 1,
            )
            years = list(range(year_from, this_year + 1))
            _set(kind, total=len(years) * per_year)

            added = skipped = done = 0
            for year in years:
                year_added = 0
                page = 1
                while year_added < per_year and page <= MAX_PAGES:
                    resp = session.get(
                        DISCOVER_URL,
                        params={
                            "api_key": settings.tmdb_api_key,
                            "primary_release_year": year,
                            "page": page,
                            "sort_by": "vote_count.desc",
                            "vote_count.gte": min_votes,
                            "include_adult": "false",
                            "language": "en-US",
                        },
                        timeout=TIMEOUT,
                    )
                    if resp.status_code == 401:
                        raise RuntimeError("TMDB API key rejected")
                    if resp.status_code == 429:
                        time.sleep(5)
                        continue
                    if resp.status_code != 200:
                        break

                    data = resp.json()
                    results = data.get("results") or []
                    if not results:
                        break

                    for item in results:
                        if year_added >= per_year:
                            break
                        tmdb_id = item.get("id")
                        title = (item.get("title") or "").strip()
                        if not tmdb_id or not title:
                            continue
                        if int(tmdb_id) in existing_tmdb:
                            skipped += 1
                            continue

                        genres_out: list[str] = []
                        for gid in item.get("genre_ids") or []:
                            mapped = GENRE_MAP.get(genre_names.get(gid, ""))
                            if mapped and mapped not in genres_out:
                                genres_out.append(mapped)

                        poster = item.get("poster_path")
                        db.add(Movie(
                            movie_id=next_id,
                            tmdb_id=int(tmdb_id),
                            title=f"{title} ({year})"[:255],
                            genres="|".join(genres_out)[:255],
                            source="tmdb",
                            overview=item.get("overview") or None,
                            poster_url=(
                                f"{IMAGE_BASE}{settings.tmdb_image_size}{poster}"
                                if poster else None
                            ),
                            release_year=year,
                            tmdb_vote_average=item.get("vote_average"),
                            tmdb_vote_count=item.get("vote_count"),
                            tmdb_popularity=item.get("popularity"),
                        ))
                        existing_tmdb.add(int(tmdb_id))
                        next_id += 1
                        added += 1
                        year_added += 1
                        done += 1
                        time.sleep(DELAY)

                    _set(kind, done=done, added=added, skipped=skipped)
                    db.commit()

                    if page >= (data.get("total_pages") or 1):
                        break
                    page += 1
                    time.sleep(DELAY)

            db.commit()

    except Exception as exc:
        log.exception("Recent sync failed")
        _set(kind, running=False, error=str(exc), finished_at=_now())
        return

    _set(kind, running=False, finished_at=_now())
    log.info("Recent sync done: added=%d skipped=%d", added, skipped)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
