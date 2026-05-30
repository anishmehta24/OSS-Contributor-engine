"""Cross-agent shared helpers — kept narrow on purpose.

Things in here are imported by multiple agents and would otherwise duplicate.
If only one agent needs it, put it inside that agent's module instead.
"""
from app.agents._shared.file_filters import (
    IGNORE_FRAGMENTS,
    MAX_BLOB_SIZE_BYTES,
    SOURCE_EXTENSIONS,
    is_interesting_path,
)

__all__ = [
    "IGNORE_FRAGMENTS",
    "MAX_BLOB_SIZE_BYTES",
    "SOURCE_EXTENSIONS",
    "is_interesting_path",
]
