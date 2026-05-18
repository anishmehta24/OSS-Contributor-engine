"""Declarative base for all ORM models. Kept tiny on purpose."""
from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """All ORM models inherit from this."""
