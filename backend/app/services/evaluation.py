"""Offline evaluation of the pre-trained NCF checkpoint.

Nothing here trains. It measures the model that already exists.

Ground truth comes from a MovieLens ratings file, which is NOT shipped with
this project. Drop `ratings.dat` (ml-1m) or `ratings.csv` (ml-latest) next to
the other artifacts and this module will find it. Without that file there is no
ground truth, and the metrics endpoint says so rather than inventing numbers.
"""

from __future__ import annotations

import csv
import logging
import time
from pathlib import Path

import numpy as np
import torch

from app.config import settings
from app.services.ncf_service import ncf_service

log = logging.getLogger(__name__)

RATING_SCALE = 5.0
BATCH = 8192

# Checked in order.
CANDIDATE_FILES = ("ratings.dat", "ratings.csv")


def find_ratings_file() -> Path | None:
    for name in CANDIDATE_FILES:
        path = settings.artifacts / name
        if path.exists():
            return path
    return None


def _load_ratings(path: Path, limit: int | None = None) -> list[tuple[int, int, float]]:
    """-> [(userId, movieId, rating)]. Handles ml-1m '::' and CSV formats."""
    rows: list[tuple[int, int, float]] = []

    with path.open(encoding="utf-8", errors="replace", newline="") as fh:
        if path.suffix == ".dat":
            for line in fh:
                parts = line.strip().split("::")
                if len(parts) < 3:
                    continue
                try:
                    rows.append((int(parts[0]), int(parts[1]), float(parts[2])))
                except ValueError:
                    continue
                if limit and len(rows) >= limit:
                    break
        else:
            reader = csv.DictReader(fh)
            for row in reader:
                try:
                    rows.append(
                        (int(row["userId"]), int(row["movieId"]), float(row["rating"]))
                    )
                except (KeyError, TypeError, ValueError):
                    continue
                if limit and len(rows) >= limit:
                    break

    return rows


@torch.no_grad()
def _predict(pairs: list[tuple[int, int]]) -> np.ndarray:
    """Sigmoid output for (user_index, movie_index) pairs, batched."""
    model = ncf_service._require()
    users = torch.tensor([p[0] for p in pairs], dtype=torch.long)
    movies = torch.tensor([p[1] for p in pairs], dtype=torch.long)

    out = np.empty(len(pairs), dtype=np.float32)
    for start in range(0, len(pairs), BATCH):
        u = users[start : start + BATCH]
        m = movies[start : start + BATCH]
        out[start : start + len(u)] = torch.atleast_1d(model(u, m)).numpy()
    return out


def _ndcg_at_k(relevances: list[float], k: int) -> float:
    """Standard NDCG with 2^rel - 1 gain."""
    rel = np.asarray(relevances[:k], dtype=np.float64)
    if rel.size == 0:
        return 0.0
    discounts = 1.0 / np.log2(np.arange(2, rel.size + 2))
    dcg = float(((2**rel - 1) * discounts).sum())

    ideal = np.sort(np.asarray(relevances, dtype=np.float64))[::-1][:k]
    idiscounts = 1.0 / np.log2(np.arange(2, ideal.size + 2))
    idcg = float(((2**ideal - 1) * idiscounts).sum())

    return dcg / idcg if idcg > 0 else 0.0


def evaluate_against_ground_truth(
    k: int = 5,
    max_ratings: int | None = 200_000,
    relevance_threshold: float = 4.0,
) -> dict:
    """Rating-prediction and ranking metrics over the MovieLens ratings file.

    RMSE/MAE are reported in stars. The model outputs 0-1, so targets are
    scaled by 1/5 and the error is scaled back up.
    """
    path = find_ratings_file()
    if path is None:
        return {
            "available": False,
            "reason": (
                "No ratings file found. Place ratings.dat (MovieLens 1M) or "
                f"ratings.csv in {settings.artifacts} to enable evaluation."
            ),
        }

    if not ncf_service.is_loaded:
        return {"available": False, "reason": "NCF model is not loaded."}

    t0 = time.perf_counter()
    raw = _load_ratings(path, limit=max_ratings)

    # Keep only ids the model was actually trained on.
    usable: list[tuple[int, int, float, int, int]] = []
    for user_id, movie_id, value in raw:
        u_idx = ncf_service.user2idx.get(user_id)
        m_idx = ncf_service.movie2idx.get(movie_id)
        if u_idx is not None and m_idx is not None:
            usable.append((user_id, movie_id, value, u_idx, m_idx))

    if not usable:
        return {
            "available": False,
            "reason": f"No rows in {path.name} matched the model's user/movie indices.",
        }

    preds = _predict([(r[3], r[4]) for r in usable])
    truth = np.asarray([r[2] for r in usable], dtype=np.float32)

    errors = preds * RATING_SCALE - truth
    rmse = float(np.sqrt(np.mean(np.square(errors))))
    mae = float(np.mean(np.abs(errors)))

    # --- ranking metrics, per user ---
    by_user: dict[int, list[tuple[float, float]]] = {}
    for (user_id, _movie_id, value, _u, _m), pred in zip(usable, preds):
        by_user.setdefault(user_id, []).append((float(pred), float(value)))

    precisions: list[float] = []
    recalls: list[float] = []
    ndcgs: list[float] = []

    for items in by_user.values():
        if len(items) < k:
            continue
        items.sort(key=lambda x: -x[0])                 # rank by prediction
        top = items[:k]
        hits = sum(1 for _, actual in top if actual >= relevance_threshold)
        total_relevant = sum(1 for _, actual in items if actual >= relevance_threshold)

        precisions.append(hits / k)
        if total_relevant:
            recalls.append(hits / total_relevant)
        ndcgs.append(_ndcg_at_k([actual for _, actual in items], k))

    return {
        "available": True,
        "source_file": path.name,
        "k": k,
        "ratings_evaluated": len(usable),
        "ratings_in_file": len(raw),
        "users_evaluated": len(precisions),
        "rmse": round(rmse, 4),
        "mae": round(mae, 4),
        "precision_at_k": round(float(np.mean(precisions)), 4) if precisions else None,
        "recall_at_k": round(float(np.mean(recalls)), 4) if recalls else None,
        "ndcg_at_k": round(float(np.mean(ndcgs)), 4) if ndcgs else None,
        "relevance_threshold": relevance_threshold,
        "took_seconds": round(time.perf_counter() - t0, 2),
        "note": (
            "Evaluation only — the checkpoint was not modified. RMSE/MAE assume "
            "the model's sigmoid output maps to rating/5."
        ),
    }
