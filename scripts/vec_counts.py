"""Print row counts for the vec0 virtual tables (not visible to ORM)."""
from sqlalchemy import text

from app.db.session import get_session


def main() -> None:
    with get_session() as s:
        for table in ("issues_vec", "user_skills_vec"):
            n = s.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            print(f"  {table:20s}  {n}")


if __name__ == "__main__":
    main()
