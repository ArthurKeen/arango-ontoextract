"""Unit tests for app.services.embedding — batching, retries."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.embedding import embed_texts


def _make_embedding_response(texts: list[str]) -> MagicMock:
    """Build a mock OpenAI embeddings response."""
    resp = MagicMock()
    data = []
    for i, _text in enumerate(texts):
        item = MagicMock()
        item.index = i
        item.embedding = [0.1 * (i + 1)] * 8
        data.append(item)
    resp.data = data
    return resp


@patch("app.services.embedding._get_client")
class TestEmbedTexts:
    def test_single_text(self, mock_get_client: MagicMock):
        client = MagicMock()
        mock_get_client.return_value = client
        client.embeddings.create.return_value = _make_embedding_response(["hello"])

        result = embed_texts(["hello"], model="text-embedding-3-small")

        assert len(result) == 1
        assert isinstance(result[0], list)
        assert len(result[0]) == 8

    def test_multiple_texts(self, mock_get_client: MagicMock):
        client = MagicMock()
        mock_get_client.return_value = client

        texts = [f"text_{i}" for i in range(5)]
        client.embeddings.create.return_value = _make_embedding_response(texts)

        result = embed_texts(texts, model="test-model")
        assert len(result) == 5

    def test_batching(self, mock_get_client: MagicMock):
        client = MagicMock()
        mock_get_client.return_value = client

        texts = [f"text_{i}" for i in range(250)]

        def side_effect(input: list[str], model: str):
            return _make_embedding_response(input)

        client.embeddings.create.side_effect = side_effect

        result = embed_texts(texts, model="test-model", batch_size=100)

        assert len(result) == 250
        assert client.embeddings.create.call_count == 3

    def test_retry_on_rate_limit(self, mock_get_client: MagicMock):
        client = MagicMock()
        mock_get_client.return_value = client

        rate_error = Exception("Rate limit exceeded (429)")
        success_response = _make_embedding_response(["test"])

        client.embeddings.create.side_effect = [rate_error, success_response]

        with patch("app.services.embedding.time.sleep"):
            result = embed_texts(["test"], model="test-model")

        assert len(result) == 1
        assert client.embeddings.create.call_count == 2

    def test_non_rate_limit_error_propagates(self, mock_get_client: MagicMock):
        client = MagicMock()
        mock_get_client.return_value = client

        client.embeddings.create.side_effect = ValueError("bad input")

        with pytest.raises(ValueError, match="bad input"):
            embed_texts(["test"], model="test-model")

    def test_empty_list(self, mock_get_client: MagicMock):
        client = MagicMock()
        mock_get_client.return_value = client

        result = embed_texts([], model="test-model")
        assert result == []
        client.embeddings.create.assert_not_called()
