"""NCF model loading and scoring.

The checkpoint is a plain state_dict for the architecture below, so the class
must stay byte-for-byte compatible with the one used at training time.
Nothing here trains — the model is loaded once at startup and only ever run
under torch.no_grad() in eval mode.
"""

from __future__ import annotations

import logging
import pickle
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

from app.config import settings

log = logging.getLogger(__name__)

# How many trained MovieLens users to average when an app account has no
# ncf_user_index of its own (cold start). Seeded, so the prior is stable
# across restarts.
PRIOR_SAMPLE_SIZE = 256
PRIOR_SEED = 42

# Movies are scored in chunks to keep peak memory flat.
SCORE_CHUNK = 4096


class NCF(nn.Module):
    """Must match the training-time architecture exactly."""

    def __init__(self, num_users, num_movies, embedding_size=50):
        super(NCF, self).__init__()
        self.user_embedding = nn.Embedding(num_users, embedding_size)
        self.movie_embedding = nn.Embedding(num_movies, embedding_size)
        self.fc1 = nn.Linear(embedding_size * 2, 128)
        self.fc2 = nn.Linear(128, 64)
        self.fc3 = nn.Linear(64, 32)
        self.fc4 = nn.Linear(32, 1)
        self.relu = nn.ReLU()
        self.sigmoid = nn.Sigmoid()
        self.dropout = nn.Dropout(0.2)

    def forward(self, user_ids, movie_ids):
        user_emb = self.user_embedding(user_ids)
        movie_emb = self.movie_embedding(movie_ids)
        x = torch.cat([user_emb, movie_emb], dim=1)
        x = self.dropout(self.relu(self.fc1(x)))
        x = self.dropout(self.relu(self.fc2(x)))
        x = self.relu(self.fc3(x))
        x = self.sigmoid(self.fc4(x))
        return x.squeeze()


def _load_pickle(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(
            f"{path.name} not found at {path}. Check ARTIFACT_DIR in backend/.env"
        )
    with path.open("rb") as fh:
        return pickle.load(fh)


class NCFService:
    """Loads the checkpoint once and scores movies for a user."""

    def __init__(self) -> None:
        self.model: NCF | None = None
        self.movie2idx: dict[int, int] = {}
        self.user2idx: dict[int, int] = {}

        # Canonical candidate ordering, shared with the SBERT service so the
        # two score vectors can be blended element-wise.
        self.movie_ids: np.ndarray = np.array([], dtype=np.int64)
        self.movie_indices: torch.Tensor = torch.empty(0, dtype=torch.long)

        self.num_users = 0
        self.num_movies = 0
        self._prior: np.ndarray | None = None

    # ---------------------------------------------------------------- load

    def load(self) -> None:
        # The pickles' keys are numpy int64; cast so plain int lookups work.
        raw_movie2idx = _load_pickle(settings.movie2idx_path)
        raw_user2idx = _load_pickle(settings.user2idx_path)
        self.movie2idx = {int(k): int(v) for k, v in raw_movie2idx.items()}
        self.user2idx = {int(k): int(v) for k, v in raw_user2idx.items()}

        self.num_users = len(self.user2idx)
        self.num_movies = len(self.movie2idx)

        path = settings.ncf_model_path
        if not path.exists():
            raise FileNotFoundError(
                f"ncf_model.pth not found at {path}. Check ARTIFACT_DIR in backend/.env"
            )

        model = NCF(self.num_users, self.num_movies, settings.ncf_embedding_size)
        # weights_only=True is safe: the checkpoint holds only tensors.
        state = torch.load(path, map_location="cpu", weights_only=True)
        if not isinstance(state, dict) or "user_embedding.weight" not in state:
            raise ValueError(
                "ncf_model.pth does not look like a state_dict for the NCF architecture"
            )
        model.load_state_dict(state, strict=True)
        model.eval()          # disables the 0.2 dropout — essential for stable scores
        self.model = model

        # Sorted by MovieLens movieId so the ordering is deterministic.
        ids = sorted(self.movie2idx)
        self.movie_ids = np.asarray(ids, dtype=np.int64)
        self.movie_indices = torch.tensor(
            [self.movie2idx[i] for i in ids], dtype=torch.long
        )

        log.info(
            "NCF loaded: %d users, %d movies, embedding=%d",
            self.num_users,
            self.num_movies,
            settings.ncf_embedding_size,
        )

    @property
    def is_loaded(self) -> bool:
        return self.model is not None

    def _require(self) -> NCF:
        if self.model is None:
            raise RuntimeError("NCF model not loaded — call load() at startup")
        return self.model

    # --------------------------------------------------------------- score

    @torch.no_grad()
    def _score_user_index(self, user_index: int) -> np.ndarray:
        """Raw sigmoid output for every candidate movie, in self.movie_ids order."""
        model = self._require()
        if not 0 <= user_index < self.num_users:
            raise ValueError(f"user_index {user_index} outside 0..{self.num_users - 1}")

        out = np.empty(len(self.movie_indices), dtype=np.float32)
        for start in range(0, len(self.movie_indices), SCORE_CHUNK):
            chunk = self.movie_indices[start : start + SCORE_CHUNK]
            users = torch.full((len(chunk),), user_index, dtype=torch.long)
            # forward() squeezes, which collapses a length-1 batch to a scalar.
            preds = torch.atleast_1d(model(users, chunk))
            out[start : start + len(chunk)] = preds.numpy()
        return out

    @torch.no_grad()
    def _population_prior(self) -> np.ndarray:
        """Mean score across a seeded sample of trained users.

        Used for app accounts with no ncf_user_index: it carries the model's
        learned notion of broad appeal without pretending to be one specific
        MovieLens person. Computed once, then cached in memory.
        """
        if self._prior is not None:
            return self._prior

        rng = np.random.default_rng(PRIOR_SEED)
        sample = rng.choice(
            self.num_users, size=min(PRIOR_SAMPLE_SIZE, self.num_users), replace=False
        )
        acc = np.zeros(len(self.movie_ids), dtype=np.float64)
        for u in sample:
            acc += self._score_user_index(int(u))
        self._prior = (acc / len(sample)).astype(np.float32)
        log.info("NCF population prior built from %d sampled users", len(sample))
        return self._prior

    def scores_for(self, ncf_user_index: int | None) -> tuple[np.ndarray, bool]:
        """Scores for every candidate movie.

        Returns (scores aligned to self.movie_ids, used_personal_embedding).
        """
        if ncf_user_index is None:
            return self._population_prior(), False
        return self._score_user_index(int(ncf_user_index)), True

    # ---------------------------------------------------------- lookup help

    def has_embedding(self, movie_id: int) -> bool:
        """False for the 177 movies in movies.csv that were never trained on."""
        return int(movie_id) in self.movie2idx

    def position_of(self, movie_id: int) -> int | None:
        """Index into self.movie_ids / score arrays, or None if untrained."""
        if int(movie_id) not in self.movie2idx:
            return None
        pos = int(np.searchsorted(self.movie_ids, int(movie_id)))
        if pos < len(self.movie_ids) and self.movie_ids[pos] == movie_id:
            return pos
        return None


ncf_service = NCFService()
