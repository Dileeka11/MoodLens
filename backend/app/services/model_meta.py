"""Model metadata + offline evaluation for the admin dashboard.

IMPORTANT: nothing here trains the NCF model. The checkpoint is treated as
read-only, per the project constraint. `evaluate()` scores the model against
the ratings your own users have submitted and records an RMSE — it changes no
weights. The admin "Retrain" action is wired to this evaluation, and the UI
says so plainly.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Rating, User
from app.services.ncf_service import ncf_service

log = logging.getLogger(__name__)

META_FILE = "model_meta.json"

# The checkpoint's sigmoid output is on 0-1. Ratings are 0.5-5 stars, so
# targets are divided by 5 for comparison and the resulting RMSE is scaled
# back into stars for display.
RATING_SCALE = 5.0


def _path():
    return settings.cache_dir / META_FILE


def read_meta() -> dict:
    p = _path()
    if not p.exists():
        # First run: record the checkpoint's own mtime as the training date.
        trained = None
        if settings.ncf_model_path.exists():
            trained = datetime.fromtimestamp(
                settings.ncf_model_path.stat().st_mtime, tz=timezone.utc
            ).isoformat()
        return {
            "last_trained": trained,
            "rmse": None,
            "evaluated_at": None,
            "evaluated_on_ratings": None,
        }
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.warning("model_meta.json unreadable — falling back to defaults")
        return {"last_trained": None, "rmse": None, "evaluated_at": None,
                "evaluated_on_ratings": None}


def write_meta(meta: dict) -> None:
    _path().write_text(json.dumps(meta, indent=2), encoding="utf-8")


def evaluate(db: Session) -> dict:
    """RMSE of the model's predictions against real user ratings.

    Only ratings from users mapped onto a trained NCF embedding
    (users.ncf_user_index IS NOT NULL) can be evaluated — for anyone else the
    model has no personal embedding to predict from.
    """
    rows = db.execute(
        select(User.ncf_user_index, Rating.movie_id, Rating.rating_value)
        .join(Rating, Rating.user_id == User.user_id)
        .where(User.ncf_user_index.is_not(None), Rating.source == "user")
    ).all()

    meta = read_meta()
    meta["evaluated_at"] = datetime.now(timezone.utc).isoformat()

    usable = [
        (int(idx), int(mid), float(val))
        for idx, mid, val in rows
        if ncf_service.has_embedding(int(mid))
    ]
    if not usable:
        meta["rmse"] = None
        meta["evaluated_on_ratings"] = 0
        meta["note"] = (
            "No ratings from users mapped to an NCF embedding yet — "
            "set users.ncf_user_index to evaluate."
        )
        write_meta(meta)
        return meta

    errors: list[float] = []
    for user_index, movie_id, value in usable:
        scores, _ = ncf_service.scores_for(user_index)
        pos = ncf_service.position_of(movie_id)
        if pos is None:
            continue
        errors.append(float(scores[pos]) - (value / RATING_SCALE))

    rmse_stars = float(np.sqrt(np.mean(np.square(errors)))) * RATING_SCALE
    meta["rmse"] = round(rmse_stars, 4)
    meta["evaluated_on_ratings"] = len(errors)
    meta["note"] = "Evaluation only — model weights were not modified."
    write_meta(meta)
    log.info("Evaluated NCF on %d ratings: RMSE=%.4f stars", len(errors), rmse_stars)
    return meta
