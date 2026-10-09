from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass(slots=True)
class SentenceItem:
    index: int
    sentence: str
    score: float


@dataclass(slots=True)
class SentenceAudit:
    sentence_index: int
    text: str
    isolated_score: float
    pairwise_gain: float
    final_weight: float
    retained: bool
    atomic_group_id: int | None
    retention_reason: str | None = None
    discard_reason: str | None = None


@dataclass(slots=True)
class CompressedDocument:
    selected_sentences: List[str] = field(default_factory=list)
    scores: List[float] = field(default_factory=list)
    estimated_original_word_count: int = 0
    estimated_compressed_word_count: int = 0
    estimated_word_reduction_percent: float = 0.0
    compressed_text: str = ""
    compression_ratio: float = 0.0
    query_complexity_score: float = 0.0
    query_intent_type: str = "factual"
    query_entity_count: int = 0
    complexity_signals: List[str] = field(default_factory=list)
    dynamic_threshold_used: float = 0.0
    dynamic_token_ratio_limit: float | None = None
    sentence_audit: List[SentenceAudit] = field(default_factory=list)
    preserved_coreferences_count: int = 0
    retained_sentence_indices: List[int] = field(default_factory=list)
    isolated_scoring_latency_ms: float = 0.0
    pairwise_scoring_latency_ms: float = 0.0
    coreference_analysis_latency_ms: float = 0.0


@dataclass(slots=True)
class BenchmarkResult:
    estimated_original_word_count: int
    estimated_compressed_word_count: int
    estimated_word_reduction_percent: float
    latency_ms: float
    answer_similarity: float = 0.0
    compression_ratio: float = 0.0
    baseline_latency_ms: float = 0.0
    latency_overhead_ms: float = 0.0
    baseline_answer_similarity: float = 0.0
    answer_similarity_gain: float = 0.0
    query_complexity_score: float = 0.0
    query_intent_type: str = "factual"
    query_entity_count: int = 0
    complexity_signals: List[str] = field(default_factory=list)
    dynamic_threshold_used: float = 0.0
    dynamic_token_ratio_limit: float | None = None
    preserved_coreferences_count: int = 0
    retained_sentence_indices: List[int] = field(default_factory=list)
    isolated_scoring_latency_ms: float = 0.0
    pairwise_scoring_latency_ms: float = 0.0
    coreference_analysis_latency_ms: float = 0.0
