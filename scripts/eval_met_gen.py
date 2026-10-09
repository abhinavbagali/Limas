#!/usr/bin/env python3
"""Run a compressor benchmark and save its metrics to an Excel workbook."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from context_compressor.evaluation.benchmark import benchmark_rag_pipeline
from context_compressor.evaluation.comparison_metrics import append_comparison_metrics
from context_compressor.types import BenchmarkResult

DEFAULT_WORKBOOK = ROOT / "reports" / "eval_met.xlsx"
WORKSHEET_NAME = "eval_met"


def save_metrics(
    metrics: BenchmarkResult,
    query: str,
    workbook_path: str | Path = DEFAULT_WORKBOOK,
) -> Path:
    """Append one local compression benchmark to the shared evaluation workbook."""
    return append_comparison_metrics(
        {
            "Query": query,
            "Legacy Original Context Word Count": metrics.estimated_original_word_count,
            "Legacy Compressed Context Word Count": metrics.estimated_compressed_word_count,
            "Legacy Estimated Context Reduction (%)": metrics.estimated_word_reduction_percent,
            "Query Complexity Score": metrics.query_complexity_score,
            "Query Intent Type": metrics.query_intent_type,
            "Query Entity Count": metrics.query_entity_count,
            "Dynamic Threshold Used": metrics.dynamic_threshold_used,
            "Dynamic Token Ratio Limit": metrics.dynamic_token_ratio_limit,
            "Preserved Coreferences": metrics.preserved_coreferences_count,
            "Retained Sentence Indices": ",".join(
                str(index) for index in metrics.retained_sentence_indices
            ),
            "Isolated Scoring Latency (ms)": metrics.isolated_scoring_latency_ms,
            "Pairwise Scoring Latency (ms)": metrics.pairwise_scoring_latency_ms,
            "Coreference Analysis Latency (ms)": metrics.coreference_analysis_latency_ms,
            "Compression Latency (ms)": metrics.latency_ms,
            "Legacy Answer Similarity (old benchmark)": metrics.answer_similarity,
        },
        workbook_path,
    )


def _load_input(path: Path | None) -> tuple[str, list[str], str | None]:
    if path is None:
        return (
            "How does climate change affect precipitation?",
            [
                "Climate change alters the global hydrological cycle by increasing evaporation and changing storm tracks.",
                "The office kitchen is closed on Fridays.",
                "Warmer temperatures can increase rainfall in some regions and reduce it in others.",
            ],
            "Climate change changes rainfall patterns through increased evaporation and shifting storm tracks.",
        )

    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    query = payload.get("query")
    documents = payload.get("documents")
    answer = payload.get("answer")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("Input JSON must contain a non-empty string 'query'.")
    if (
        not isinstance(documents, list)
        or not documents
        or any(not isinstance(document, str) for document in documents)
    ):
        raise ValueError("Input JSON must contain a non-empty list of string 'documents'.")
    if answer is not None and not isinstance(answer, str):
        raise ValueError("Input JSON 'answer' must be a string when provided.")
    return query, documents, answer


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a context-compression benchmark and append metrics to Excel."
    )
    parser.add_argument(
        "--input",
        type=Path,
        help="Optional JSON file containing query, documents, and optional answer.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_WORKBOOK,
        help=f"Workbook output path (default: {DEFAULT_WORKBOOK.name}).",
    )
    parser.add_argument("--threshold", type=float, default=0.35)
    parser.add_argument("--top-k", type=int, default=4)
    parser.add_argument("--max-tokens", type=int, default=256)
    args = parser.parse_args()

    query, documents, answer = _load_input(args.input)
    metrics = benchmark_rag_pipeline(
        query=query,
        documents=documents,
        answer=answer,
        threshold=args.threshold,
        top_k=args.top_k,
        max_tokens=args.max_tokens,
    )
    output_path = save_metrics(metrics, query, args.output)

    print(f"Evaluation metrics saved to: {output_path}")
    print(f"Worksheet: {WORKSHEET_NAME}")
    print(f"Original context words (estimated): {metrics.estimated_original_word_count}")
    print(f"Compressed context words (estimated): {metrics.estimated_compressed_word_count}")
    print(f"Estimated word-count reduction: {metrics.estimated_word_reduction_percent:.2f}%")
    print(f"Compression latency: {metrics.latency_ms:.2f} ms")
    print(f"Answer similarity: {metrics.answer_similarity:.4f}")


if __name__ == "__main__":
    main()
