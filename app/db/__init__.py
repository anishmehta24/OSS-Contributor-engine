"""Database layer: SQLAlchemy 2.0 + aiosqlite + sqlite-vec.

Public API:
    from app.db import Base, get_session, init_db
    from app.db.models import User, UserSkill, Repo, Issue, Investigation, AgentRun
    from app.db.vector import insert_vector, search_similar
"""
from app.db.base import Base
from app.db.session import get_session, init_db, reset_db, sessionmaker_factory
from app.db.vector import insert_vector, search_similar

__all__ = [
    "Base",
    "get_session",
    "init_db",
    "insert_vector",
    "reset_db",
    "search_similar",
    "sessionmaker_factory",
]
