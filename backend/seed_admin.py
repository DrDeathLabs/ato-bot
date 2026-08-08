"""
Seed script — creates the initial system_admin user.

Usage:
    python seed_admin.py [username] [email] [password]

Defaults:
    username: admin
    email:    admin@atobot.local
    password: (prompted if not provided)
"""
import asyncio
import getpass
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.orm import User
from sqlalchemy import select


async def seed(username: str, email: str, password: str) -> None:
    async with AsyncSessionLocal() as db:
        existing = await db.execute(select(User).where(User.username == username))
        if existing.scalar_one_or_none():
            print(f"User '{username}' already exists — skipping.")
            return

        user = User(
            username=username,
            email=email,
            hashed_password=hash_password(password),
            role="system_admin",
            is_active=True,
        )
        db.add(user)
        await db.commit()
        print(f"Created system_admin user: {username} ({email})")


if __name__ == "__main__":
    _username = sys.argv[1] if len(sys.argv) > 1 else "admin"
    _email = sys.argv[2] if len(sys.argv) > 2 else "admin@atobot.local"
    _password = sys.argv[3] if len(sys.argv) > 3 else getpass.getpass(f"Password for {_username}: ")

    asyncio.run(seed(_username, _email, _password))
