from __future__ import annotations

import re
import time
from dataclasses import asdict
from typing import Any, Mapping, Sequence

from ..compression.compressor import ContextCompressor
from ..gating import QueryComplexityGater
from ..types import BenchmarkResult


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"\b\w+\b", text.lower()))


def _jaccard_similarity(a: str, b: str) -> float:
    tokens_a = _tokenize(a)
    tokens_b = _tokenize(b)
    if not tokens_a and not tokens_b:
        return 1.0
    union = tokens_a | tokens_b
    if not union:
        return 0.0
    return len(tokens_a & tokens_b) / len(union)


def benchmark_rag_pipeline(
    query: str,
    documents: Sequence[str],
    answer: str | None = None,
    threshold: float = 0.35,
    top_k: int = 4,
    max_tokens: int = 256,
    enable_coref: bool = True,
    enable_multihop: bool = True,
    adaptive_gating: bool = True,
    compressor: ContextCompressor | None = None,
) -> BenchmarkResult:
    """Compare fixed-rule extraction with enabled research features.

    The answer similarity values are lexical context/reference overlap proxies,
    not QA accuracy. Latencies include model scoring and local compression but
    exclude model initialization by reusing one compressor instance.
    """
    documents = list(documents)
    compressor = compressor or ContextCompressor()

    start = time.perf_counter()
    baseline = compressor.compress(
        query=query,
        documents=documents,
        threshold=threshold,
        top_k=top_k,
        max_tokens=max_tokens,
        enable_coref=False,
        enable_multihop=False,
        adaptive_gating=False,
    )
    baseline_latency_ms = (time.perf_counter() - start) * 1000.0

    start = time.perf_counter()
    enhanced = compressor.compress(
        query=query,
        documents=documents,
        threshold=threshold if not adaptive_gating else None,
        top_k=top_k,
        max_tokens=max_tokens,
        enable_coref=enable_coref,
        enable_multihop=enable_multihop,
        adaptive_gating=adaptive_gating,
    )
    enhanced_latency_ms = (time.perf_counter() - start) * 1000.0

    baseline_similarity = _jaccard_similarity(answer, baseline.compressed_text) if answer else 0.0
    enhanced_similarity = _jaccard_similarity(answer, enhanced.compressed_text) if answer else 0.0

    return BenchmarkResult(
        estimated_original_word_count=enhanced.estimated_original_word_count,
        estimated_compressed_word_count=enhanced.estimated_compressed_word_count,
        estimated_word_reduction_percent=enhanced.estimated_word_reduction_percent,
        latency_ms=enhanced_latency_ms,
        answer_similarity=enhanced_similarity,
        compression_ratio=enhanced.compression_ratio,
        baseline_latency_ms=baseline_latency_ms,
        latency_overhead_ms=enhanced_latency_ms - baseline_latency_ms,
        baseline_answer_similarity=baseline_similarity,
        answer_similarity_gain=enhanced_similarity - baseline_similarity,
        query_complexity_score=enhanced.query_complexity_score,
        query_intent_type=enhanced.query_intent_type,
        query_entity_count=enhanced.query_entity_count,
        complexity_signals=enhanced.complexity_signals,
        dynamic_threshold_used=enhanced.dynamic_threshold_used,
        dynamic_token_ratio_limit=enhanced.dynamic_token_ratio_limit,
        preserved_coreferences_count=enhanced.preserved_coreferences_count,
        retained_sentence_indices=enhanced.retained_sentence_indices,
        isolated_scoring_latency_ms=enhanced.isolated_scoring_latency_ms,
        pairwise_scoring_latency_ms=enhanced.pairwise_scoring_latency_ms,
        coreference_analysis_latency_ms=enhanced.coreference_analysis_latency_ms,
    )


def benchmark_query_set(
    cases: Sequence[Mapping[str, Any]],
    *,
    threshold: float = 0.35,
    top_k: int = 4,
    max_tokens: int = 256,
    enable_coref: bool = True,
    enable_multihop: bool = True,
    adaptive_gating: bool = True,
    compressor: ContextCompressor | None = None,
) -> dict[str, Any]:
    """Benchmark and aggregate factual, comparative, and multi-hop query cases.

    Each case requires ``query`` and ``documents`` and may include ``answer``.
    This function reports per-case latency overhead and lexical similarity gain,
    plus averages grouped by the adaptive gater's predicted intent.
    """
    if not cases:
        raise ValueError("At least one benchmark case is required.")
    shared_compressor = compressor or ContextCompressor()
    results: list[dict[str, Any]] = []
    grouped: dict[str, list[BenchmarkResult]] = {}
    gater = QueryComplexityGater()
    for case_index, case in enumerate(cases):
        query = case.get("query")
        documents = case.get("documents")
        answer = case.get("answer")
        if not isinstance(query, str) or not query.strip():
            raise ValueError(f"Benchmark case {case_index} requires a non-empty query.")
        if (
            not isinstance(documents, Sequence)
            or isinstance(documents, str)
            or not documents
            or any(not isinstance(document, str) for document in documents)
        ):
            raise ValueError(
                f"Benchmark case {case_index} requires a non-empty list of document strings."
            )
        if answer is not None and not isinstance(answer, str):
            raise ValueError(f"Benchmark case {case_index} answer must be a string.")

        result = benchmark_rag_pipeline(
            query=query,
            documents=documents,
            answer=answer,
            threshold=threshold,
            top_k=top_k,
            max_tokens=max_tokens,
            enable_coref=enable_coref,
            enable_multihop=enable_multihop,
            adaptive_gating=adaptive_gating,
            compressor=shared_compressor,
        )
        intent = gater.analyze(query).intent_type
        grouped.setdefault(intent, []).append(result)
        row = asdict(result)
        row["case_index"] = case_index
        row["query"] = query
        row["intent_group"] = intent
        results.append(row)

    summary = {
        intent: {
            "case_count": len(items),
            "mean_baseline_latency_ms": sum(item.baseline_latency_ms for item in items)
            / len(items),
            "mean_enhanced_latency_ms": sum(item.latency_ms for item in items) / len(items),
            "mean_latency_overhead_ms": sum(item.latency_overhead_ms for item in items)
            / len(items),
            "mean_answer_similarity_gain": sum(item.answer_similarity_gain for item in items)
            / len(items),
            "mean_query_complexity_score": sum(
                item.query_complexity_score for item in items
            )
            / len(items),
        }
        for intent, items in grouped.items()
    }
    return {"cases": results, "summary_by_intent": summary}
