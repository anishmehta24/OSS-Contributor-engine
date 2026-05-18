"""Factory that returns the configured embedder backend.

All app code should call `make_embedder()` instead of importing VoyageClient
or LocalEmbedder directly. Switching backends is then a one-env-var change
(`EMBEDDER_BACKEND=local` vs `EMBEDDER_BACKEND=voyage`).
"""
from __future__ import annotations

from typing import Protocol

from app.core.config import settings
from app.tools.local_embedder import LocalEmbedder
from app.tools.voyage_client import EmbeddingResult, VoyageClient


class Embedder(Protocol):
    """Minimum interface every embedder backend must satisfy."""

    async def embed(self, inputs, *, input_type: str = "document") -> EmbeddingResult: ...
    async def embed_one(self, text: str, *, input_type: str = "document") -> list[float]: ...
    async def close(self) -> None: ...
    async def __aenter__(self): ...
    async def __aexit__(self, *exc): ...


def make_embedder() -> Embedder:
    """Build the embedder picked by `settings.embedder_backend`.

    Raises RuntimeError if `voyage` was chosen without a VOYAGE_API_KEY.
    """
    backend = settings.embedder_backend.lower()
    if backend == "voyage":
        if not settings.voyage_api_key:
            raise RuntimeError(
                "EMBEDDER_BACKEND=voyage but VOYAGE_API_KEY is not set"
            )
        model = settings.embedder_model or None
        return VoyageClient(
            api_key=settings.voyage_api_key,
            model=model or "voyage-3-large",
        )
    if backend == "local":
        return LocalEmbedder(model_name=settings.embedder_model or None)
    raise RuntimeError(
        f"Unknown EMBEDDER_BACKEND={settings.embedder_backend!r}; "
        "use 'local' or 'voyage'"
    )
