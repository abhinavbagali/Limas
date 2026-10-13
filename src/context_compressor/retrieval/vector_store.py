from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from threading import RLock
from typing import Sequence

from ..ingestion.chunker import TextChunk
from .lexical import is_technical_lookup, technical_match_count, term_frequencies

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk: TextChunk
    score: float
    rank: int


@dataclass(slots=True)
class DocumentIndex:
    doc_id: str
    chunks: list[TextChunk]
    vectors: list[list[float]]
    backend: str
    term_frequencies: list[Counter[str]] = field(default_factory=list)
    document_frequency: Counter[str] = field(default_factory=Counter)
    average_length: float = 0.0


class VectorStore:
    """Process-local cosine index with a lazy MiniLM backend and safe offline fallback."""

    def __init__(self, model_name: str = EMBEDDING_MODEL) -> None:
        self.model_name = model_name
        self._model = None
        self._indexes: dict[str, DocumentIndex] = {}
        self._lock = RLock()

    def _load_model(self) -> None:
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
        except Exception:
            self._model = False

    @staticmethod
    def _fallback_embed(text: str, dimensions: int = 2048) -> list[float]:
        vector = [0.0] * dimensions
        tokens = re.findall(r"\w+", text.lower())
        counts = Counter(tokens)
        for token, count in counts.items():
            # Stable signed feature hashing; this is only for offline development.
            value = 2166136261
            for char in token:
                value = ((value ^ ord(char)) * 16777619) & 0xFFFFFFFF
            index = value % dimensions
            vector[index] += (1.0 if value & 1 else -1.0) * (1.0 + math.log(count))
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector

    def _encode(self, texts: Sequence[str]) -> tuple[list[list[float]], str]:
        self._load_model()
        if self._model:
            encoded = self._model.encode(list(texts), normalize_embeddings=True, show_progress_bar=False)
            return [[float(value) for value in row] for row in encoded], "sentence-transformers"
        return [self._fallback_embed(text) for text in texts], "offline-hash-fallback"

    def index(self, doc_id: str, chunks: Sequence[TextChunk], force: bool = False) -> DocumentIndex:
        with self._lock:
            if doc_id in self._indexes and not force:
                return self._indexes[doc_id]
            if not chunks:
                raise ValueError("Cannot index a document with no text chunks.")
            if any(chunk.doc_id != doc_id for chunk in chunks):
                raise ValueError("All chunks must belong to the indexed doc_id.")
            vectors, backend = self._encode([chunk.text for chunk in chunks])
            frequencies = [term_frequencies(chunk.text) for chunk in chunks]
            document_frequency: Counter[str] = Counter()
            for frequencies_for_chunk in frequencies:
                document_frequency.update(frequencies_for_chunk.keys())
            average_length = sum(sum(item.values()) for item in frequencies) / len(frequencies)
            result = DocumentIndex(doc_id, list(chunks), vectors, backend, frequencies, document_frequency, average_length)
            self._indexes[doc_id] = result
            return result

    def retrieve(self, doc_id: str, query: str, top_k: int = 30) -> list[RetrievedChunk]:
        if top_k < 1:
            raise ValueError("top_k must be positive.")
        index = self._indexes.get(doc_id)
        if index is None:
            raise KeyError(f"Document {doc_id} is not indexed.")
        query_vector, _ = self._encode([query])
        dense_scores = [sum(a * b for a, b in zip(query_vector[0], vector)) for vector in index.vectors]
        query_terms = term_frequencies(query)
        n_documents = len(index.chunks)
        k1, b = 1.5, 0.75
        lexical_scores: list[float] = []
        for frequencies in index.term_frequencies:
            document_length = sum(frequencies.values())
            score = 0.0
            for term, query_frequency in query_terms.items():
                term_frequency = frequencies.get(term, 0)
                if not term_frequency:
                    continue
                document_frequency = index.document_frequency.get(term, 0)
                inverse_frequency = math.log1p(
                    (n_documents - document_frequency + 0.5)
                    / (document_frequency + 0.5)
                )
                denominator = term_frequency + k1 * (
                    1 - b + b * document_length / max(index.average_length, 1.0)
                )
                contribution = inverse_frequency * term_frequency * (k1 + 1) / denominator
                score += contribution * min(1.5, 1 + 0.05 * (query_frequency - 1))
            lexical_scores.append(score)

        max_lexical = max(lexical_scores, default=0.0)
        exact_counts = [technical_match_count(query, chunk.text) for chunk in index.chunks]
        max_exact = max(exact_counts, default=0)
        technical_query = is_technical_lookup(query)
        combined_scores = []
        for offset, dense_score in enumerate(dense_scores):
            dense_normalized = max(0.0, min(1.0, (dense_score + 1.0) / 2.0))
            lexical_normalized = lexical_scores[offset] / max_lexical if max_lexical else 0.0
            exact_normalized = (
                exact_counts[offset] / max_exact
                if technical_query and max_exact
                else 0.0
            )
            if technical_query:
                score = 0.25 * dense_normalized + 0.50 * lexical_normalized + 0.25 * exact_normalized
            else:
                score = 0.60 * dense_normalized + 0.40 * lexical_normalized
            combined_scores.append(score)
        ranked = sorted(enumerate(combined_scores), key=lambda item: (-item[1], item[0]))[:top_k]
        return [RetrievedChunk(index.chunks[offset], float(score), rank) for rank, (offset, score) in enumerate(ranked, 1)]

    def has_index(self, doc_id: str) -> bool:
        return doc_id in self._indexes

    def backend_for(self, doc_id: str) -> str | None:
        index = self._indexes.get(doc_id)
        return index.backend if index else None
