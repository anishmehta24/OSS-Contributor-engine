"""Mocked tests for the Voyage AI embeddings client."""
from __future__ import annotations

import httpx
import pytest
import respx

from app.tools.voyage_client import VoyageClient, VoyageError

API = "https://api.voyageai.com/v1/embeddings"


@pytest.fixture
async def voyage():
    v = VoyageClient(api_key="test-key")
    yield v
    await v.close()


@pytest.mark.unit
@respx.mock
async def test_embed_single_call(voyage):
    respx.post(API).mock(return_value=httpx.Response(
        200,
        json={
            "data": [
                {"embedding": [0.1, 0.2, 0.3], "index": 0},
                {"embedding": [0.4, 0.5, 0.6], "index": 1},
            ],
            "model": "voyage-3-large",
            "usage": {"total_tokens": 42},
        },
    ))
    result = await voyage.embed(["hello", "world"])
    assert len(result.embeddings) == 2
    assert result.embeddings[0] == [0.1, 0.2, 0.3]
    assert result.total_tokens == 42


@pytest.mark.unit
@respx.mock
async def test_embed_preserves_input_order_even_if_api_reorders(voyage):
    respx.post(API).mock(return_value=httpx.Response(
        200,
        json={
            "data": [
                {"embedding": [9.0], "index": 1},
                {"embedding": [1.0], "index": 0},
            ],
            "model": "voyage-3-large",
            "usage": {"total_tokens": 4},
        },
    ))
    result = await voyage.embed(["first", "second"])
    assert result.embeddings == [[1.0], [9.0]]


@pytest.mark.unit
@respx.mock
async def test_embed_chunks_large_inputs(voyage):
    """We auto-chunk into MAX_BATCH_SIZE-sized requests."""
    from app.tools.voyage_client import MAX_BATCH_SIZE

    def _handler(request):
        body = request.read()
        import json
        payload = json.loads(body)
        n = len(payload["input"])
        return httpx.Response(
            200,
            json={
                "data": [{"embedding": [float(i)], "index": i} for i in range(n)],
                "model": "voyage-3-large",
                "usage": {"total_tokens": n},
            },
        )

    n_inputs = MAX_BATCH_SIZE * 2 + 3  # forces 3 chunks
    route = respx.post(API).mock(side_effect=_handler)
    inputs = [f"text {i}" for i in range(n_inputs)]
    result = await voyage.embed(inputs)
    assert route.call_count == 3
    assert len(result.embeddings) == n_inputs
    assert result.total_tokens == n_inputs


@pytest.mark.unit
@respx.mock
async def test_embed_empty_inputs_returns_empty(voyage):
    result = await voyage.embed([])
    assert result.embeddings == []
    assert result.total_tokens == 0


@pytest.mark.unit
@respx.mock
async def test_embed_one_returns_first_embedding(voyage):
    respx.post(API).mock(return_value=httpx.Response(
        200,
        json={
            "data": [{"embedding": [7.7, 8.8], "index": 0}],
            "model": "voyage-3-large",
            "usage": {"total_tokens": 5},
        },
    ))
    vec = await voyage.embed_one("hi")
    assert vec == [7.7, 8.8]


@pytest.mark.unit
@respx.mock
async def test_embed_raises_on_http_error(voyage):
    respx.post(API).mock(return_value=httpx.Response(500, text="upstream down"))
    with pytest.raises(VoyageError, match="500"):
        await voyage.embed(["x"])


@pytest.mark.unit
async def test_voyage_client_requires_api_key():
    with pytest.raises(ValueError):
        VoyageClient(api_key="")
