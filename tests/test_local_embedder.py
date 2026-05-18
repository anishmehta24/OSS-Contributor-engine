"""Tests for the embedder factory and LocalEmbedder.

We don't load the real sentence-transformers model in unit tests — it's
slow and downloads weights. Instead we verify:
    - The factory picks the right backend based on settings
    - The LocalEmbedder wraps the model correctly (with a mocked model)
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest

from app.tools.embedder import make_embedder
from app.tools.local_embedder import LocalEmbedder
from app.tools.voyage_client import VoyageClient

# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_factory_returns_local_by_default(monkeypatch):
    monkeypatch.setattr(
        "app.tools.embedder.settings",
        SimpleNamespace(
            embedder_backend="local",
            embedder_model="",
            voyage_api_key="",
        ),
    )
    embedder = make_embedder()
    assert isinstance(embedder, LocalEmbedder)


@pytest.mark.unit
def test_factory_returns_voyage_when_configured(monkeypatch):
    monkeypatch.setattr(
        "app.tools.embedder.settings",
        SimpleNamespace(
            embedder_backend="voyage",
            embedder_model="",
            voyage_api_key="abc",
        ),
    )
    embedder = make_embedder()
    assert isinstance(embedder, VoyageClient)


@pytest.mark.unit
def test_factory_voyage_without_key_raises(monkeypatch):
    monkeypatch.setattr(
        "app.tools.embedder.settings",
        SimpleNamespace(
            embedder_backend="voyage",
            embedder_model="",
            voyage_api_key="",
        ),
    )
    with pytest.raises(RuntimeError, match="VOYAGE_API_KEY"):
        make_embedder()


@pytest.mark.unit
def test_factory_unknown_backend_raises(monkeypatch):
    monkeypatch.setattr(
        "app.tools.embedder.settings",
        SimpleNamespace(
            embedder_backend="cohere",
            embedder_model="",
            voyage_api_key="",
        ),
    )
    with pytest.raises(RuntimeError, match="Unknown EMBEDDER_BACKEND"):
        make_embedder()


# ---------------------------------------------------------------------------
# LocalEmbedder (mocked model — never actually downloads weights)
# ---------------------------------------------------------------------------

class _FakeModel:
    """Stand-in for SentenceTransformer that returns a deterministic vector."""

    def __init__(self, dim: int = 384):
        self._dim = dim
        self.encode_calls: list[list[str]] = []

    def encode(self, batch, *, normalize_embeddings=True,
               convert_to_numpy=True, show_progress_bar=False):
        self.encode_calls.append(list(batch))
        # Return deterministic vectors based on string length
        return np.array(
            [[float(len(s) % 10) / 10.0] * self._dim for s in batch],
            dtype=np.float32,
        )

    def get_sentence_embedding_dimension(self) -> int:
        return self._dim


@pytest.mark.unit
async def test_local_embedder_embed_returns_vectors():
    fake = _FakeModel()
    embedder = LocalEmbedder()
    with patch.object(embedder, "_ensure_model", return_value=fake):
        result = await embedder.embed(["hello", "world"])
    assert len(result.embeddings) == 2
    assert len(result.embeddings[0]) == 384
    assert result.model.startswith("sentence-transformers/")


@pytest.mark.unit
async def test_local_embedder_embed_one_returns_single_vector():
    fake = _FakeModel()
    embedder = LocalEmbedder()
    with patch.object(embedder, "_ensure_model", return_value=fake):
        vec = await embedder.embed_one("hi there")
    assert len(vec) == 384


@pytest.mark.unit
async def test_local_embedder_empty_input_returns_empty():
    embedder = LocalEmbedder()
    result = await embedder.embed([])
    assert result.embeddings == []
    assert result.total_tokens == 0


@pytest.mark.unit
async def test_local_embedder_batches_large_inputs():
    fake = _FakeModel()
    embedder = LocalEmbedder()
    with patch.object(embedder, "_ensure_model", return_value=fake):
        from app.tools.local_embedder import MAX_BATCH_SIZE
        n = MAX_BATCH_SIZE * 2 + 5
        inputs = [f"text {i}" for i in range(n)]
        result = await embedder.embed(inputs)
    assert len(result.embeddings) == n
    # 3 encode calls (two full batches + one partial)
    assert len(fake.encode_calls) == 3


@pytest.mark.unit
async def test_local_embedder_close_is_noop():
    embedder = LocalEmbedder()
    await embedder.close()
    # After close, the model should be cleared
    assert embedder._model is None
