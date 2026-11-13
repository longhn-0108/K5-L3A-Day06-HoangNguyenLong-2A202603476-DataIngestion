"""Real local embedding provider using Sentence Transformers."""
from __future__ import annotations

from typing import Protocol


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in the same order."""
        ...

    def embed_query(self, question: str) -> list[float]:
        """Return a query vector compatible with the stored document vectors."""
        ...


class MyEmbedder:
    """SentenceTransformer local embedder; never falls back to mock vectors."""

    def __init__(self, model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2") -> None:
        self.model_name = model_name
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(model_name)
            dim = self._model.get_sentence_embedding_dimension()
            if dim is None:
                raise RuntimeError(f"Could not determine embedding dimensions for {model_name}")
            self.dimensions = int(dim)
        except Exception as exc:
            raise RuntimeError(f"Failed to initialize embedding model '{model_name}': {exc}") from exc

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._model.encode(
            texts,
            batch_size=32,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [vec.tolist() for vec in vectors]

    def embed_query(self, question: str) -> list[float]:
        vec = self._model.encode(
            question,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return vec.tolist()
