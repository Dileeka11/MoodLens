"""Onboarding: the 5 cold-start preference questions."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import User
from app.schemas import OnboardingQuestion, OnboardingRequest, OnboardingResponse
from app.services import onboarding as svc

router = APIRouter(tags=["onboarding"])


@router.get("/onboarding/questions", response_model=list[OnboardingQuestion])
def questions():
    """Served from the backend so the mapping stays in one place."""
    return svc.public_questions()


@router.post("/onboarding", response_model=OnboardingResponse)
def submit(
    payload: OnboardingRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    genres, years = svc.parse_answers(payload.answers)
    seeded = svc.seed_profile(db, user, genres, years)

    # Skipping every question still completes onboarding — the user just
    # starts from the population prior instead of a genre profile.
    user.onboarded = True
    db.commit()

    if seeded:
        message = (
            f"Profile ready — we noted {', '.join(genres[:3])} and seeded "
            f"{seeded} starter picks you can adjust any time."
        )
    else:
        message = "Profile saved. Rate a few films and recommendations will sharpen quickly."

    return OnboardingResponse(
        onboarded=True,
        seeded_movies=seeded,
        preferred_genres=genres,
        message=message,
    )
