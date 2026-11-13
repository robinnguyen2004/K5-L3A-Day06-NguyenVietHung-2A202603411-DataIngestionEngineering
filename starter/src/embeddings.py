"""Real embedding provider: a local Sentence Transformers model (no API key, cost 0)."""
import os
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
    """Sentence Transformers adapter.

    E5 models expect the prefixes "query: " / "passage: " (see the model card); they are added
    automatically for model names containing "e5". Vectors are L2-normalized, so cosine
    similarity in pgvector is consistent with the model's training objective.
    Errors are raised; there is no fallback to mock or random vectors.
    """

    def __init__(self, model_name: str | None = None, device: str | None = None,
                 batch_size: int = 32) -> None:
        model_name = model_name or os.getenv("EMBEDDING_MODEL")
        if not model_name:
            raise ValueError("EMBEDDING_MODEL is not set (see starter/.env).")
        from sentence_transformers import SentenceTransformer  # heavy import, load lazily

        self.model_name = model_name
        self.batch_size = batch_size
        self.model = SentenceTransformer(model_name, device=device)
        dim_fn = getattr(self.model, "get_embedding_dimension", None) or \
            self.model.get_sentence_embedding_dimension
        self.dimensions = int(dim_fn())
        self.max_seq_length = int(self.model.max_seq_length)
        self.device = str(self.model.device)
        is_e5 = "e5" in model_name.lower()
        self.query_prefix = "query: " if is_e5 else ""
        self.passage_prefix = "passage: " if is_e5 else ""

    def _encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self.model.encode(texts, batch_size=self.batch_size, normalize_embeddings=True,
                                    convert_to_numpy=True, show_progress_bar=len(texts) > 64)
        if vectors.shape != (len(texts), self.dimensions):
            raise RuntimeError(f"Unexpected embedding shape {vectors.shape}")
        return vectors.tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._encode([self.passage_prefix + t for t in texts])

    def embed_query(self, question: str) -> list[float]:
        return self._encode([self.query_prefix + question])[0]

    def count_tokens(self, texts: list[str]) -> list[int]:
        """Token count per document (with prefix) to detect truncation beyond max_seq_length."""
        tokenizer = self.model.tokenizer
        return [len(tokenizer(self.passage_prefix + t, add_special_tokens=True)["input_ids"])
                for t in texts]

    def describe(self) -> dict:
        return {
            "provider": "sentence-transformers (local)",
            "model_name": self.model_name,
            "dimensions": self.dimensions,
            "max_seq_length": self.max_seq_length,
            "device": self.device,
            "normalize_embeddings": True,
            "query_prefix": self.query_prefix,
            "passage_prefix": self.passage_prefix,
            "cost_usd": 0,
        }
