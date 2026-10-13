from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ..ingestion.chunker import TextChunk
from ..models.cross_encoder import CrossEncoderRelevanceScorer
from .lexical import is_technical_lookup, technical_match_count, technical_query_terms
from .vector_store import RetrievedChunk

MS_MARCO_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
BASELINE_MODEL = "cross-encoder/stsb-roberta-base"


@dataclass(frozen=True, slots=True)
class RerankedChunk:
    chunk: TextChunk
    retrieval_score: float
    rerank_score: float
    retrieval_rank: int
    rerank_rank: int


class CrossEncoderReranker:
    def __init__(self, model_name: str = MS_MARCO_MODEL, batch_size: int = 16) -> None:
        if model_name not in {MS_MARCO_MODEL, BASELINE_MODEL}:
            raise ValueError(f"Unsupported reranker model: {model_name}")
        self.model_name = model_name
        self.scorer = CrossEncoderRelevanceScorer(model_name=model_name, batch_size=batch_size)

    def rerank(self, query: str, candidates: Sequence[RetrievedChunk], top_k: int = 8) -> list[RerankedChunk]:
        if top_k < 1:
            raise ValueError("top_k must be positive.")
        scores = self.scorer.score_pairs(query, [item.chunk.text for item in candidates])
        exact_terms = technical_query_terms(query)
        technical_query = is_technical_lookup(query)
        denominator = max(1, len(exact_terms))
        ranked = sorted(
            zip(candidates, scores),
            key=lambda pair: (
                -(
                    float(pair[1])
                    + (0.20 * technical_match_count(query, pair[0].chunk.text) / denominator
                       if technical_query else 0.0)
                ),
                pair[0].rank,
            ),
        )[:top_k]
        return [RerankedChunk(item.chunk, item.score, float(score), item.rank, rank) for rank, (item, score) in enumerate(ranked, 1)]
