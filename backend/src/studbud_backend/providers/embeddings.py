from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import re
from functools import lru_cache
from typing import Protocol

import anyio
import httpx

from ..config import get_settings

logger = logging.getLogger(__name__)

TOKEN_RE = re.compile(r"[a-z0-9]+")


class EmbeddingError(RuntimeError):
    pass


class EmbeddingProvider(Protocol):
    model_id: str
    dimensions: int

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    async def embed_query(self, query: str) -> list[float]: ...


class HashingEmbeddings:
    """Deterministic local fallback embedding.

    A bag-of-words hash, not a semantic model. It exists only so the app can run
    without any provider; use FastEmbed or Groq for real retrieval quality.
    """

    model_id = "local-hash-768-v1"
    dimensions = 768

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    async def embed_query(self, query: str) -> list[float]:
        return self._embed_one(query)

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = TOKEN_RE.findall(text.lower())
        features = tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:], strict=False)]
        for feature in features:
            digest = hashlib.sha256(feature.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm:
            vector = [value / norm for value in vector]
        return vector


class FastEmbeddings:
    """Local ONNX embeddings through FastEmbed.

    Defaults to a quantized Nomic model (768 dimensions) so the vector column and
    search space stay compatible with the Groq Nomic model.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self.model_id = settings.local_embedding_model
        self.dimensions = settings.embedding_dim
        self.cache_dir = settings.fastembed_cache_dir
        self.threads = settings.embedding_threads
        self._model = None

    def _ensure_model(self):
        if self._model is None:
            try:
                from fastembed import TextEmbedding

                self._model = TextEmbedding(
                    model_name=self.model_id,
                    cache_dir=self.cache_dir or None,
                    threads=self.threads,
                    lazy_load=True,
                )
            except Exception as exc:  # dependency, download, or ONNX failure
                raise EmbeddingError(f"Local embedding model could not load: {exc}") from exc
        return self._model

    async def _run(self, texts: list[str], query: bool) -> list[list[float]]:
        if not texts:
            return []

        def compute() -> list[list[float]]:
            model = self._ensure_model()
            method = model.query_embed if query else model.passage_embed
            vectors = [list(map(float, vector)) for vector in method(texts)]
            for vector in vectors:
                if len(vector) != self.dimensions:
                    raise EmbeddingError(
                        f"Local embedding dimension {len(vector)} does not match "
                        f"configured dimension {self.dimensions}."
                    )
            return vectors

        try:
            return await anyio.to_thread.run_sync(compute)
        except EmbeddingError:
            raise
        except Exception as exc:
            raise EmbeddingError(f"Local embedding failed: {exc}") from exc

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._run(texts, query=False)

    async def embed_query(self, query: str) -> list[float]:
        vectors = await self._run([query], query=True)
        return vectors[0]


class GeminiEmbeddings:
    """Hosted Gemini embeddings (768-d output).

    Keeps the backend under Render's 512 MB memory limit because the model runs
    remotely. Free-tier rate limits apply; batch requests and retries are used.
    """

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.gemini_api_key:
            raise EmbeddingError("GEMINI_API_KEY is not configured.")
        self.api_key = settings.gemini_api_key
        self.base_url = settings.gemini_base_url.rstrip("/")
        self.model_id = settings.gemini_embedding_model
        self.dimensions = settings.embedding_dim

    def _headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}

    def _request_object(self, text: str) -> dict:
        return {
            "model": f"models/{self.model_id}",
            "content": {"parts": [{"text": text}]},
            "outputDimensionality": self.dimensions,
        }

    async def _post(self, path: str, payload: dict) -> dict:
        last_error: Exception | None = None
        async with httpx.AsyncClient(timeout=90.0) as client:
            for attempt in range(3):
                try:
                    response = await client.post(
                        f"{self.base_url}/{path}", headers=self._headers(), json=payload
                    )
                    if response.status_code == 429 or response.status_code >= 500:
                        raise EmbeddingError(f"Embedding provider returned {response.status_code}.")
                    if response.status_code >= 400:
                        raise EmbeddingError(
                            f"Embedding provider returned {response.status_code}: "
                            f"{response.text[:160]}"
                        )
                    return response.json()
                except (httpx.HTTPError, KeyError, EmbeddingError) as exc:
                    last_error = exc
                    if isinstance(exc, EmbeddingError) and "returned 4" in str(exc):
                        break
                    if attempt == 2:
                        break
                    await asyncio.sleep(2**attempt)
        raise EmbeddingError(f"Gemini embedding request failed: {last_error}")

    def _validate(self, vectors: list[list[float]], expected: int) -> list[list[float]]:
        if len(vectors) != expected:
            raise EmbeddingError(
                f"Gemini returned {len(vectors)} embeddings for {expected} inputs."
            )
        for vector in vectors:
            if len(vector) != self.dimensions:
                raise EmbeddingError(
                    f"Embedding dimension {len(vector)} does not match "
                    f"configured dimension {self.dimensions}."
                )
        return vectors

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors: list[list[float]] = []
        batch_size = 20
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            data = await self._post(
                f"models/{self.model_id}:batchEmbedContents",
                {"requests": [self._request_object(text) for text in batch]},
            )
            embeddings = data.get("embeddings", [])
            vectors.extend([list(map(float, item.get("values", []))) for item in embeddings])
        return self._validate(vectors, len(texts))

    async def embed_query(self, query: str) -> list[float]:
        data = await self._post(
            f"models/{self.model_id}:embedContent",
            self._request_object(query),
        )
        values = list(map(float, data.get("embedding", {}).get("values", [])))
        return self._validate([values], 1)[0]


class GroqEmbeddings:
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.groq_api_key:
            raise EmbeddingError("GROQ_API_KEY is not configured.")
        self.api_key = settings.groq_api_key
        self.base_url = settings.groq_base_url.rstrip("/")
        self.model_id = settings.embedding_model
        self.dimensions = settings.embedding_dim

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {"model": self.model_id, "input": texts}
        last_error: Exception | None = None

        async with httpx.AsyncClient(timeout=60.0) as client:
            for attempt in range(3):
                try:
                    response = await client.post(
                        f"{self.base_url}/embeddings", headers=headers, json=payload
                    )
                    if response.status_code == 429 or response.status_code >= 500:
                        raise EmbeddingError(f"Embedding provider returned {response.status_code}.")
                    response.raise_for_status()
                    data = response.json()["data"]
                    ordered = sorted(data, key=lambda item: item["index"])
                    vectors = [item["embedding"] for item in ordered]
                    for vector in vectors:
                        if len(vector) != self.dimensions:
                            raise EmbeddingError(
                                f"Embedding dimension {len(vector)} does not match "
                                f"configured dimension {self.dimensions}."
                            )
                    return vectors
                except (httpx.HTTPError, KeyError, EmbeddingError) as exc:
                    last_error = exc
                    if attempt == 2:
                        break
                    await asyncio.sleep(2**attempt)

        raise EmbeddingError(f"Embedding request failed: {last_error}")

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._embed(texts)

    async def embed_query(self, query: str) -> list[float]:
        vectors = await self._embed([query])
        return vectors[0]


@lru_cache
def get_embeddings() -> EmbeddingProvider:
    settings = get_settings()
    provider = settings.embedding_provider.lower()

    if provider == "hash":
        return HashingEmbeddings()

    if provider == "groq":
        return GroqEmbeddings()

    if provider == "gemini":
        return GeminiEmbeddings()

    if provider == "fastembed":
        return FastEmbeddings()

    # auto: local semantic embeddings, then the hash fallback. Groq embeddings
    # must be opted into explicitly because the endpoint is not reliably enabled.
    try:
        return FastEmbeddings()
    except Exception:
        logger.exception("FastEmbed is unavailable; using local hash embeddings.")
        return HashingEmbeddings()
