"""Backfill issue embeddings into issues_vec.

Use when the Hunter persisted issues but the embedding batch didn't land
(e.g. the local sentence-transformers model was still loading and the run
was cut short), leaving `/matches` empty. Re-embeds every issue in one pass.

    uv run python scripts/backfill_embeddings.py
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select, text

from app.db.models import Issue
from app.db.session import sessionmaker_factory
from app.db.vector import insert_vector
from app.tools.embedder import make_embedder
from app.workers.issue_hunter import issue_embed_text


async def main() -> None:
    session_factory = sessionmaker_factory()
    with session_factory() as session:
        issues = session.execute(select(Issue)).scalars().all()
        if not issues:
            print("No issues to embed. Run the hunter first.")
            return

        texts = [issue_embed_text(i.title, i.body, list(i.labels or [])) for i in issues]
        ids = [i.id for i in issues]
        print(f"Embedding {len(texts)} issues...")

        async with make_embedder() as embedder:
            result = await embedder.embed(texts, input_type="document")

        for issue_id, vector in zip(ids, result.embeddings, strict=True):
            insert_vector(session, "issues_vec", issue_id, vector)
        session.commit()

    with session_factory() as session:
        count = session.execute(text("select count(*) from issues_vec")).scalar()
        print(f"Done. issues_vec rows: {count}")


if __name__ == "__main__":
    asyncio.run(main())
