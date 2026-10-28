"""Promote (or create) an admin from the server shell, e.g. in the Dokploy api container:

python scripts/make_admin.py owner@example.com            # promote an existing user
python scripts/make_admin.py owner@example.com 'NewPass1'  # create/reset with a password
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db.session import get_session_factory  # noqa: E402
from app.models import User  # noqa: E402


async def main(email: str, password: str | None) -> None:
    async with get_session_factory()() as db:
        user = await db.scalar(select(User).where(User.email == email.lower()))
        if user is None:
            if not password:
                raise SystemExit(f"{email} not found; pass a password to create it")
            user = User(email=email.lower(), password_hash=hash_password(password))
            db.add(user)
        elif password:
            user.password_hash = hash_password(password)
        user.role = "admin"
        user.is_active = True
        await db.commit()
        print(f"{user.email} is now an active admin")


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        raise SystemExit(__doc__)
    asyncio.run(main(sys.argv[1], sys.argv[2] if len(sys.argv) == 3 else None))
