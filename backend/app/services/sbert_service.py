"""SBERT (all-MiniLM-L6-v2) encoding of the movie catalogue and mood text.

Runs entirely locally — no external API. Movie embeddings are built once and
cached to backend/cache/, keyed by a fingerprint of the model name plus the
corpus, so a changed catalogue invalidates the cache automatically.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re

import numpy as np

from app.config import settings

# transformers probes for TensorFlow/Flax at import time. On a machine with
# TensorFlow + Keras 3 installed that probe raises, taking sentence-transformers
# down with it. MoodLens is torch-only, so pin the backend before the import.
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_FLAX", "0")
os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")

log = logging.getLogger(__name__)

# Bare genre labels ("Sci-Fi", "Film-Noir") are weak targets for free-text mood
# queries like "dark and mind-blowing". These hints expand each label into the
# vocabulary people actually use to describe how a film feels, which is what
# lifts the cosine signal. Deterministic and offline — no generated content.
GENRE_MOOD_HINTS: dict[str, str] = {
    "Action": "fast paced, thrilling, explosive, adrenaline, high energy",
    "Adventure": "epic journey, exploration, quest, sweeping, escapist",
    "Animation": "animated, imaginative, colourful, playful, stylised",
    "Children's": "family friendly, gentle, wholesome, lighthearted, innocent",
    "Comedy": "funny, humorous, feel good, witty, cheerful, easy watch",
    "Crime": "gritty, criminal underworld, tense, morally grey, streetwise",
    "Documentary": "true story, factual, real events, informative, thought provoking",
    "Drama": "emotional, character driven, moving, serious, heartfelt",
    "Fantasy": "magical, otherworldly, mythical, wondrous, imaginative",
    "Film-Noir": "dark, shadowy, cynical, moody, atmospheric, bleak",
    "Horror": "scary, frightening, disturbing, eerie, terrifying, dread",
    "Musical": "songs, music, uplifting, theatrical, joyful",
    "Mystery": "puzzling, suspenseful, twisty, intriguing, whodunit",
    "Romance": "love story, romantic, tender, heartfelt, relationship",
    "Sci-Fi": "futuristic, mind bending, cerebral, speculative, technology, space",
    "Thriller": "suspenseful, tense, gripping, edge of your seat, twisty",
    "War": "wartime, harrowing, heroic, historical conflict, intense",
    "Western": "frontier, rugged, cowboys, dusty, classic showdown",
}


_YEAR_SUFFIX = re.compile(r"\s*\((\d{4})\)\s*$")


# How much of the synopsis to encode. The whole plot dilutes the mood signal;
# the opening sentences carry the premise, which is what people describe.
OVERVIEW_CHARS = 320


def build_corpus_text(title: str, genres: str, overview: str | None = None) -> str:
    """One short passage per movie, encoded into the catalogue vector.

    The trailing "(1999)" is stripped: it is already a structured column, and
    leaving it in makes the release year dominate the embedding — similarity
    for The Matrix returned nothing but other 1999 films.

    The synopsis matters because genres are a blunt vocabulary: nothing in
    "Action|Sci-Fi" tells you a film is about superheroes, a heist, or time
    travel. With overviews included, a mood like "a superhero blockbuster"
    has something to match against.
    """
    clean_title = _YEAR_SUFFIX.sub("", (title or "").strip())

    labels = [g for g in (genres or "").split("|") if g]
    hints = ", ".join(GENRE_MOOD_HINTS.get(g, g.lower()) for g in labels)
    genre_phrase = ", ".join(labels) if labels else "uncategorised"

    text = f"{clean_title}. A {genre_phrase} film."
    if hints:
        text += f" It feels {hints}."

    synopsis = (overview or "").strip()
    if synopsis:
        text += f" {synopsis[:OVERVIEW_CHARS]}"
    return text


def _fingerprint(model_name: str, texts: list[str]) -> str:
    h = hashlib.sha256()
    h.update(model_name.encode("utf-8"))
    h.update(str(len(texts)).encode("utf-8"))
    for t in texts:
        h.update(t.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:16]


class SBERTService:
    """Holds the encoder plus L2-normalised movie embeddings."""

    def __init__(self) -> None:
        self.model = None
        self.movie_ids: np.ndarray = np.array([], dtype=np.int64)
        self.embeddings: np.ndarray = np.empty((0, 0), dtype=np.float32)
        self.dim = 0

    # ---------------------------------------------------------------- load

    def load(self, catalogue: list[tuple]) -> None:
        """`catalogue` is [(movie_id, title, genres, overview?), ...], ordered."""
        from sentence_transformers import SentenceTransformer  # heavy; import lazily

        self.model = SentenceTransformer(settings.sbert_model, device="cpu")
        self.dim = self.model.get_sentence_embedding_dimension()

        self.movie_ids = np.asarray([m[0] for m in catalogue], dtype=np.int64)
        texts = [
            build_corpus_text(row[1], row[2], row[3] if len(row) > 3 else None)
            for row in catalogue
        ]

        fp = _fingerprint(settings.sbert_model, texts)
        emb_path = settings.cache_dir / f"movie_emb_{fp}.npy"
        meta_path = settings.cache_dir / f"movie_emb_{fp}.json"

        if emb_path.exists():
            cached = np.load(emb_path)
            if cached.shape[0] == len(texts):
                self.embeddings = cached.astype(np.float32, copy=False)
                log.info("SBERT movie embeddings loaded from cache (%s)", emb_path.name)
                return
            log.warning("Cached embeddings had wrong shape — re-encoding")

        log.info("Encoding %d movies with %s (first run, ~1-2 min)…", len(texts), settings.sbert_model)
        self.embeddings = self.model.encode(
            texts,
            batch_size=64,
            convert_to_numpy=True,
            normalize_embeddings=True,   # cosine similarity becomes a dot product
            show_progress_bar=False,
        ).astype(np.float32)

        np.save(emb_path, self.embeddings)
        meta_path.write_text(
            json.dumps(
                {
                    "model": settings.sbert_model,
                    "count": len(texts),
                    "dim": self.dim,
                    "sample_text": texts[0] if texts else "",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        log.info("SBERT embeddings cached to %s", emb_path.name)

    @property
    def is_loaded(self) -> bool:
        return self.model is not None and self.embeddings.size > 0

    # --------------------------------------------------------------- score

    def encode_mood(self, text: str) -> np.ndarray:
        if self.model is None:
            raise RuntimeError("SBERT model not loaded — call load() at startup")
        vec = self.model.encode(
            [text], convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False
        )[0]
        return vec.astype(np.float32)

    def similarities(self, mood_text: str) -> np.ndarray:
        """Cosine similarity of the mood against every movie, in movie_ids order.

        Both sides are L2-normalised, so this is a plain dot product and the
        result lies in [-1, 1].
        """
        if not self.is_loaded:
            raise RuntimeError("SBERT embeddings not built — call load() at startup")
        return self.embeddings @ self.encode_mood(mood_text)


sbert_service = SBERTService()
