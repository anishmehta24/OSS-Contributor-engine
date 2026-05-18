"""CLI: draft a pitch for an existing investigation.

Usage:
    uv run python -m app.agents.pitch <investigation_id>
    uv run python -m app.agents.pitch <investigation_id> --markdown
"""
from __future__ import annotations

import argparse
import json
import sys

from app.agents.pitch.pitch_writer import run_pitch_writer
from app.core.config import settings
from app.core.logging import configure_logging
from app.db.models import Investigation
from app.db.session import get_session
from app.llm import build_router


def main() -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="python -m app.agents.pitch")
    parser.add_argument("investigation_id")
    parser.add_argument("--markdown", action="store_true",
                        help="Print only the comment_md field")
    args = parser.parse_args()

    if not settings.has_any_llm:
        print("ERROR: No LLM provider key set", file=sys.stderr)
        return 1

    router = build_router()
    with get_session() as session:
        inv = session.get(Investigation, args.investigation_id)
        if inv is None:
            print(f"ERROR: Investigation {args.investigation_id} not found", file=sys.stderr)
            return 1
        if inv.status != "completed":
            print(f"ERROR: Investigation is {inv.status} — needs to be completed first",
                  file=sys.stderr)
            return 1
        if inv.report_md is None:
            print("ERROR: Investigation has no report_md", file=sys.stderr)
            return 1

        issue_url = inv.issue.html_url if inv.issue else ""
        repo_full_name = inv.issue.repo.full_name if inv.issue and inv.issue.repo else "?"
        issue_number = inv.issue.number if inv.issue else 0

        pitch = run_pitch_writer(
            router,
            repo_full_name=repo_full_name,
            issue_number=issue_number,
            issue_url=issue_url,
            markdown_report=inv.report_md,
            investigation_id=inv.id,
            user_id=inv.user_id,
            session=session,
        )
        inv.pitch_md = pitch.comment_md
        session.commit()

    if args.markdown:
        print(pitch.comment_md)
    else:
        print(json.dumps(pitch.model_dump(mode="json"), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
