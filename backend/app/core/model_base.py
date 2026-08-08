"""SQLAlchemy declarative base without runtime configuration side effects."""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
