import hashlib
import math
import re
from functools import lru_cache
from typing import Protocol

import httpx

from aos.config import get_settings

_STOPWORD_TEXT = (
    "a an and are as at be by for from has have in is it its of on or our the to was were "
    "what which who will with this that these those then than into about using use"
)
STOPWORDS = frozenset(_STOPWORD_TEXT.split())


class Embedder(Protocol):
    name: str
    min_similarity: float
    consolidate_similarity: float

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashEmbedder:
    """Words and word pairs hashed into a fixed-size vector.

    Deterministic and offline, which keeps tests stable; it matches requests that share
    vocabulary, not paraphrases.
    """

    name = "hash"
    # Unrelated texts score close to zero here, so a low bar still filters noise, and
    # paraphrases of one lesson land around 0.55 to 0.75.
    min_similarity = 0.15
    consolidate_similarity = 0.55

    def __init__(self, dim: int = 512) -> None:
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def _embed(self, text: str) -> list[float]:
        words = [_stem(w) for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOPWORDS]
        features = [(w, 1.0) for w in words] + [
            (f"{a} {b}", 0.5) for a, b in zip(words, words[1:], strict=False)
        ]
        vector = [0.0] * self.dim
        for feature, weight in features:
            digest = int.from_bytes(hashlib.blake2b(feature.encode(), digest_size=8).digest())
            vector[digest % self.dim] += weight if digest >> 63 else -weight
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]


class OllamaEmbedder:
    name = "ollama"
    min_similarity = 0.35
    consolidate_similarity = 0.85

    def __init__(self, model: str, base_url: str) -> None:
        self.model = model
        self._client = httpx.Client(base_url=base_url.rstrip("/").removesuffix("/v1"), timeout=120)

    def embed(self, texts: list[str]) -> list[list[float]]:
        response = self._client.post("/api/embed", json={"model": self.model, "input": texts})
        response.raise_for_status()
        return response.json()["embeddings"]


class OpenAIEmbedder:
    name = "openai"
    min_similarity = 0.35
    consolidate_similarity = 0.85

    def __init__(self, model: str, api_key: str) -> None:
        import openai

        self.model = model
        self._client = openai.OpenAI(api_key=api_key)

    def embed(self, texts: list[str]) -> list[list[float]]:
        response = self._client.embeddings.create(model=self.model, input=texts)
        return [item.embedding for item in response.data]


@lru_cache
def get_embedder() -> Embedder:
    settings = get_settings()
    if settings.llm_mode == "mock" or settings.embedding_provider == "hash":
        return HashEmbedder()
    if settings.embedding_provider == "ollama":
        return OllamaEmbedder(
            settings.embedding_model or "nomic-embed-text", settings.ollama_base_url
        )
    return OpenAIEmbedder(
        settings.embedding_model or "text-embedding-3-small", settings.openai_api_key
    )


def _stem(word: str) -> str:
    return word[:-1] if len(word) > 4 and word.endswith("s") and not word.endswith("ss") else word
