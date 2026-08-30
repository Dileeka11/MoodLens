"""Create (or promote) the admin account.

    python -m app.scripts.create_admin
    python -m app.scripts.create_admin --email me@example.com --password secret123

Prompts for a password when one isn't supplied, so it never has to be typed
into shell history.
"""

import argparse
import getpass
import sys

from sqlalchemy import select

from app.auth import hash_password
from app.database import SessionLocal
from app.models import User


def main() -> None:
    ap = argparse.ArgumentParser(description="Create or promote a MoodLens admin")
    # Not a .local / .localhost / .invalid address: those are special-use names
    # and the EmailStr validator on POST /login rejects them, which would make
    # the account unusable from the UI.
    ap.add_argument("--email", default="admin@moodlens.app")
    ap.add_argument("--username", default="Admin")
    ap.add_argument("--password", default=None)
    args = ap.parse_args()

    password = args.password or getpass.getpass("Admin password: ")
    if len(password) < 8:
        sys.exit("Password must be at least 8 characters")

    email = args.email.lower()
    with SessionLocal() as db:
        user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if user is None:
            user = User(
                username=args.username,
                email=email,
                password_hash=hash_password(password),
                role="admin",
                onboarded=True,
            )
            db.add(user)
            action = "Created"
        else:
            user.role = "admin"
            user.password_hash = hash_password(password)
            action = "Updated"
        db.commit()
        db.refresh(user)

    print(f"{action} admin account: {user.email} (user_id={user.user_id})")


if __name__ == "__main__":
    main()
