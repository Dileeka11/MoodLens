"""Content bridge: NCF scores for films the model was never trained on.

The checkpoint holds embeddings for exactly 3706 MovieLens films (1919-2000).
Anything added afterwards — a 2023 release imported from TMDB, a film an admin
typed in — has no embedding, so the collaborative model cannot score it at all.
Retraining is out of scope: the model is served as-is.

The bridge borrows a score instead. For each untrained film we find its nearest
neighbours among the trained films in SBERT space, and estimate its NCF score
as the similarity-weighted mean of those neighbours' scores for this user:

    est(new) = Σ wᵢ · ncf(user, neighbourᵢ)   where wᵢ ∝ cos(new, neighbourᵢ)

If you like Schindler's List and JFK, the model already says so; a film that
sits next to them in content space inherits that signal.

This is an approximation, not collaborative filtering, and it is labelled as
such everywhere it surfaces: the API returns score_source="estimated" and the
UI marks the card. Never present an estimate as a model prediction.
"""

from __future__ import annotations

import logging

import numpy as np

log = logging.getLogger(__name__)

# How many trained neighbours contribute to one estimate. Too few is noisy;
# too many regresses every new film towards the same population average.
NEIGHBOURS = 8

# Weights are proportional to cosine^SHARPNESS, so the closest neighbours
# dominate instead of every one of the k contributing almost equally.
SHARPNESS = 4.0

# Below this cosine a "neighbour" carries no real signal. If a film has no
# neighbour above it, the estimate falls back to the population prior.
MIN_SIMILARITY = 0.25

# Averaging compresses variance: a mean of k scores can never reach the
# extremes the individual scores do, so estimated films would always lose to
# the best trained ones no matter how good a match they are. After averaging,
# estimates are rescaled to the same mean/spread as the trained scores, which
# undoes that artefact without inventing signal. This is the single most
# important step — without it, no post-2000 film ever ranks.
MATCH_DISTRIBUTION = True

# Estimates are still shrunk slightly towards the mean: a borrowed score
# deserves a little less confidence than a real one.
CONFIDENCE = 0.92


class ContentBridge:
    """Maps the full catalogue onto the trained subset."""

    def __init__(self) -> None:
        self.movie_ids: np.ndarray = np.array([], dtype=np.int64)   # full catalogue
        self.trained_mask: np.ndarray = np.array([], dtype=bool)

        # For catalogue position i, where its score comes from:
        #   trained -> row in the NCF score vector
        #   untrained -> neighbour rows + weights
        self._trained_row: np.ndarray = np.array([], dtype=np.int64)
        self._neighbour_rows: np.ndarray = np.empty((0, 0), dtype=np.int64)
        self._neighbour_weights: np.ndarray = np.empty((0, 0), dtype=np.float32)
        self._has_neighbours: np.ndarray = np.array([], dtype=bool)

    @property
    def is_built(self) -> bool:
        return self.movie_ids.size > 0

    @property
    def num_trained(self) -> int:
        return int(self.trained_mask.sum())

    @property
    def num_estimated(self) -> int:
        return int((~self.trained_mask).sum())

    # ----------------------------------------------------------------- build

    def build(self, catalogue_ids: list[int], ncf_service, sbert_service) -> None:
        """Precompute the neighbour table once, at startup.

        `catalogue_ids` must be in the same order as sbert_service.embeddings.
        """
        self.movie_ids = np.asarray(catalogue_ids, dtype=np.int64)
        n = len(self.movie_ids)

        self.trained_mask = np.array(
            [ncf_service.has_embedding(int(m)) for m in self.movie_ids], dtype=bool
        )

        # Row of each trained film inside the NCF score vector.
        self._trained_row = np.full(n, -1, dtype=np.int64)
        for i, mid in enumerate(self.movie_ids):
            if self.trained_mask[i]:
                pos = ncf_service.position_of(int(mid))
                if pos is not None:
                    self._trained_row[i] = pos
                else:
                    self.trained_mask[i] = False       # in the pickle but not rankable

        untrained_idx = np.flatnonzero(~self.trained_mask)
        self._neighbour_rows = np.zeros((n, NEIGHBOURS), dtype=np.int64)
        self._neighbour_weights = np.zeros((n, NEIGHBOURS), dtype=np.float32)
        self._has_neighbours = np.zeros(n, dtype=bool)

        if untrained_idx.size == 0:
            log.info("Content bridge: every catalogue film is in the model")
            return

        trained_idx = np.flatnonzero(self.trained_mask)
        trained_emb = sbert_service.embeddings[trained_idx]        # (T, d), L2-normalised

        # Chunked so a large catalogue does not allocate an N x T matrix.
        CHUNK = 512
        for start in range(0, untrained_idx.size, CHUNK):
            rows = untrained_idx[start : start + CHUNK]
            sims = sbert_service.embeddings[rows] @ trained_emb.T   # (chunk, T) cosine

            k = min(NEIGHBOURS, sims.shape[1])
            top = np.argpartition(-sims, k - 1, axis=1)[:, :k]

            for r, row in enumerate(rows):
                cols = top[r]
                vals = sims[r, cols]
                order = np.argsort(-vals)
                cols, vals = cols[order], vals[order]

                keep = vals >= MIN_SIMILARITY
                if not keep.any():
                    continue                     # falls back to the population prior

                cols, vals = cols[keep], vals[keep]
                sharp = np.power(vals, SHARPNESS)
                weights = sharp / sharp.sum()

                self._neighbour_rows[row, : len(cols)] = self._trained_row[trained_idx[cols]]
                self._neighbour_weights[row, : len(weights)] = weights
                self._has_neighbours[row] = True

        bridged = int(self._has_neighbours.sum())
        log.info(
            "Content bridge: %d trained, %d estimated (%d with usable neighbours, "
            "%d fall back to the prior)",
            self.num_trained,
            untrained_idx.size,
            bridged,
            untrained_idx.size - bridged,
        )

    # ----------------------------------------------------------------- score

    def expand(self, trained_scores: np.ndarray) -> np.ndarray:
        """Turn a per-trained-film score vector into a full-catalogue vector.

        Films with no usable neighbour, and the shrinkage baseline, both use
        the mean of `trained_scores` — the model's own view of a typical film
        for whoever this vector belongs to.
        """
        if not self.is_built:
            raise RuntimeError("Content bridge not built — call build() at startup")

        n = len(self.movie_ids)
        out = np.empty(n, dtype=np.float32)

        trained = self.trained_mask
        out[trained] = trained_scores[self._trained_row[trained]]

        untrained = ~trained
        if untrained.any():
            baseline = float(trained_scores.mean())

            rows = self._neighbour_rows[untrained]
            weights = self._neighbour_weights[untrained]
            est = (trained_scores[rows] * weights).sum(axis=1)

            # Rows with no neighbour above the threshold have all-zero weights,
            # which would otherwise produce a score of 0 and bury the film.
            usable = self._has_neighbours[untrained]
            est = np.where(usable, est, baseline)

            if MATCH_DISTRIBUTION and est.size > 1:
                est_std = float(est.std())
                if est_std > 1e-6:
                    trained_std = float(trained_scores.std())
                    est = baseline + (est - est.mean()) * (trained_std / est_std)
                    # Keep estimates inside the range the model actually produces.
                    est = np.clip(est, float(trained_scores.min()), float(trained_scores.max()))

            # A borrowed score is a little less certain than a real one.
            est = CONFIDENCE * est + (1.0 - CONFIDENCE) * baseline
            out[untrained] = est.astype(np.float32)

        return out

    def is_estimated(self, movie_id: int) -> bool:
        pos = self.position_of(movie_id)
        return pos is not None and not bool(self.trained_mask[pos])

    def position_of(self, movie_id: int) -> int | None:
        pos = int(np.searchsorted(self.movie_ids, int(movie_id)))
        if pos < len(self.movie_ids) and self.movie_ids[pos] == movie_id:
            return pos
        return None


bridge = ContentBridge()
