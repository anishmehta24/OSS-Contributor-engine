"""Local embedding backend using sentence-transformers.

Same public API as VoyageClient (embed / embed_one / async ctx manager) so
the rest of the app can swap them transparently via the factory in
`app/tools/embedder.py`.

Why local:
    - No rate limits, no per-token cost
    - No external service dependency or API key
    - First call downloads the model (~90MB for all-MiniLM-L6-v2), cached
      under ~/.cache/huggingface/ for all future runs

Tradeoffs vs Voyage:
    - 384 dims (vs 1024) — vectors are 3× smaller, search is faster
    - Slightly weaker retrieval quality (~5-10% on benchmarks)
    - CPU inference — ~100ms per text on a laptop
    - Wraps the synchronous model in asyncio.to_thread so it doesn't block
      the event loop
"""
from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import TYPE_CHECKING, Literal

import structlog

from app.tools.voyage_client import EmbeddingResult

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

log = structlog.get_logger(__name__)

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"  # 384 dims, ~90MB
MAX_BATCH_SIZE = 64  # CPU-bound, larger batches help amortize tokenization

InputType = Literal["query", "document"]


class LocalEmbedder:
    """Drop-in replacement for VoyageClient backed by sentence-transformers."""

    def __init__(self, *, model_name: str | None = None) -> None:
        self._model_name = model_name or DEFAULT_MODEL
        self._model: SentenceTransformer | None = None  # lazy-loaded

    async def __aenter__(self) -> LocalEmbedder:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def close(self) -> None:
        # nothing to clean up — the model lives in memory until GC'd
        self._model = None

    def _ensure_model(self) -> SentenceTransformer:
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            log.info("local_embedder_loading_model", model=self._model_name)
            self._model = SentenceTransformer(self._model_name)
            log.info(
                "local_embedder_model_loaded",
                model=self._model_name,
                dim=self._model.get_sentence_embedding_dimension(),
            )
        return self._model

    def _encode_sync(self, batch: list[str]) -> list[list[float]]:
        model = self._ensure_model()
        vectors = model.encode(
            batch,
            normalize_embeddings=True,  # so cosine distance ≈ 1 - dot product
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return vectors.tolist()

    async def embed(
        self,
        inputs: Sequence[str],
        *,
        input_type: InputType = "document",  # ignored locally; kept for API parity
    ) -> EmbeddingResult:
        if not inputs:
            return EmbeddingResult(embeddings=[], model=self._model_name, total_tokens=0)

        all_embeddings: list[list[float]] = []
        for start in range(0, len(inputs), MAX_BATCH_SIZE):
            batch = list(inputs[start : start + MAX_BATCH_SIZE])
            # encode is CPU-bound, run off the event loop
            vectors = await asyncio.to_thread(self._encode_sync, batch)
            all_embeddings.extend(vectors)

        log.info(
            "local_embed_completed",
            batch_count=len(inputs),
            model=self._model_name,
        )
        return EmbeddingResult(
            embeddings=all_embeddings,
            model=self._model_name,
            total_tokens=0,  # we don't tokenize-count; not meaningful locally
        )

    async def embed_one(
        self,
        text: str,
        *,
        input_type: InputType = "document",
    ) -> list[float]:
        result = await self.embed([text], input_type=input_type)
        return result.embeddings[0]
