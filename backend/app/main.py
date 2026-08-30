"""MoodLens FastAPI application."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import (
    admin,
    auth_routes,
    discovery,
    history,
    movies,
    onboarding,
    password_reset,
    ratings,
    recommend,
)
from app.services import model_registry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("moodlens")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Models load once here rather than per request. First boot also builds
    # the SBERT embedding cache, which takes a minute or two.
    log.info("Loading models from %s", settings.artifacts)
    try:
        model_registry.warmup()
    except Exception:
        # Serve anyway so /health and the admin screens still respond and can
        # report what went wrong; /recommend returns 503 until this succeeds.
        log.exception("Model warm-up failed — /recommend will return 503")
    yield


app = FastAPI(
    title="MoodLens API",
    description="Mood-based movie recommendations — NCF + SBERT hybrid",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_routes.router)
app.include_router(password_reset.router)
app.include_router(onboarding.router)
app.include_router(recommend.router)
app.include_router(ratings.router)
app.include_router(movies.router)
app.include_router(history.router)
app.include_router(discovery.router)
app.include_router(admin.router)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok", **model_registry.status()}
