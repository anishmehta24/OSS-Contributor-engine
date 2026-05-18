"""Tiny async Voyage AI embeddings client (no SDK dependency).

We use Voyage because:
    - voyage-3-large produces 1024-dim embeddings (matches our VEC_DIM)
    - Designed for retrieval (RAG / similarity) over raw OpenAI embeddings
    - Generous free tier (~50M tokens)

The API is one POST endpoint, so a 50-line client is plenty.
"""
from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import httpx
import structlog

log = structlog.get_logger(__name__)

VOYAGE_API = "https://api.voyageai.com/v1/embeddings"
DEFAULT_MODEL = "voyage-3-large"
# Smaller default batch keeps us under the 10K tokens/min ceiling of Voyage's
# free tier without a payment method. Bump back up to 128 once you add one.
MAX_BATCH_SIZE = 16
MAX_RETRIES = 4
INITIAL_BACKOFF_S = 2.0

InputType = Literal["query", "document"]


class VoyageError(Exception):
    pass


@dataclass
class EmbeddingResult:
    embeddings: list[list[float]]   # one per input, same order
    model: str
    total_tokens: int


class VoyageClient:
    """Use as `async with VoyageClient(api_key=...) as v: ..."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str = DEFAULT_MODEL,
        timeout: float = 60.0,
    ) -> None:
        if not api_key:
            raise ValueError("Voyage API key is required")
        self._api_key = api_key
        self._model = model
        self._client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    async def __aenter__(self) -> VoyageClient:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    async def embed(
        self,
        inputs: Sequence[str],
        *,
        input_type: InputType = "document",
    ) -> EmbeddingResult:
        """Embed a batch of texts. Auto-chunks if more than MAX_BATCH_SIZE."""
        if not inputs:
            return EmbeddingResult(embeddings=[], model=self._model, total_tokens=0)

        all_embeddings: list[list[float]] = []
        total_tokens = 0

        for start in range(0, len(inputs), MAX_BATCH_SIZE):
            batch = list(inputs[start : start + MAX_BATCH_SIZE])
            payload = await self._post_with_retry(batch, input_type=input_type)
            data = sorted(payload["data"], key=lambda d: d["index"])
            all_embeddings.extend(d["embedding"] for d in data)
            total_tokens += payload.get("usage", {}).get("total_tokens", 0)

        log.info(
            "voyage_embed_completed",
            batch_count=len(inputs),
            tokens=total_tokens,
            model=self._model,
        )
        return EmbeddingResult(
            embeddings=all_embeddings,
            model=self._model,
            total_tokens=total_tokens,
        )

    async def embed_one(self, text: str, *, input_type: InputType = "document") -> list[float]:
        result = await self.embed([text], input_type=input_type)
        return result.embeddings[0]

    async def _post_with_retry(self, batch: list[str], *, input_type: InputType) -> dict:
        """POST one batch with exponential backoff on 429 + transient 5xx.

        Free-tier Voyage (no payment method) is 3 RPM / 10K TPM, so a hunt
        can easily hit 429. We respect the Retry-After header when present.
        """
        backoff = INITIAL_BACKOFF_S
        for attempt in range(MAX_RETRIES + 1):
            response = await self._client.post(
                VOYAGE_API,
                json={
                    "input": batch,
                    "model": self._model,
                    "input_type": input_type,
                },
            )
            if response.status_code == 200:
                return response.json()

            if response.status_code in (429, 502, 503, 504) and attempt < MAX_RETRIES:
                wait = backoff
                retry_after = response.headers.get("Retry-After")
                if retry_after:
                    with contextlib.suppress(ValueError):
                        wait = max(wait, float(retry_after))
                log.warning(
                    "voyage_retrying",
                    status=response.status_code,
                    attempt=attempt + 1,
                    sleep_s=wait,
                    batch_size=len(batch),
                )
                await asyncio.sleep(wait)
                backoff *= 2
                continue

            raise VoyageError(
                f"Voyage returned {response.status_code}: {response.text[:200]}"
            )

        raise VoyageError(f"Voyage exhausted {MAX_RETRIES} retries (batch={len(batch)})")
