from __future__ import annotations

import argparse
import json
from pathlib import Path

from .compression.compressor import ContextCompressor
from .evaluation.benchmark import benchmark_query_set, benchmark_rag_pipeline
from .types import CompressedDocument


def _add_feature_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--enable-coref",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Preserve antecedent sentences for discourse-dependent selections.",
    )
    parser.add_argument(
        "--enable-multihop",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Blend isolated sentence scores with contiguous-pair relevance gains.",
    )
    parser.add_argument(
        "--adaptive-gating",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Adapt the relevance cutoff and word budget to query complexity.",
    )


def _print_compression(result: CompressedDocument) -> None:
    print(
        json.dumps(
            {
                "compressed_text": result.compressed_text,
                "selected_sentences": result.selected_sentences,
                "scores": result.scores,
                "estimated_original_word_count": result.estimated_original_word_count,
                "estimated_compressed_word_count": result.estimated_compressed_word_count,
                "estimated_word_reduction_percent": round(
                    result.estimated_word_reduction_percent, 2
                ),
                "compression_ratio": round(result.compression_ratio, 4),
                "query_complexity_score": round(result.query_complexity_score, 4),
                "query_intent_type": result.query_intent_type,
                "complexity_signals": result.complexity_signals,
                "dynamic_threshold_used": round(result.dynamic_threshold_used, 4),
                "dynamic_token_ratio_limit": (
                    round(result.dynamic_token_ratio_limit, 4)
                    if result.dynamic_token_ratio_limit is not None
                    else None
                ),
                "preserved_coreferences_count": result.preserved_coreferences_count,
                "retained_sentence_indices": result.retained_sentence_indices,
                "isolated_scoring_latency_ms": round(
                    result.isolated_scoring_latency_ms, 3
                ),
                "pairwise_scoring_latency_ms": round(
                    result.pairwise_scoring_latency_ms, 3
                ),
                "coreference_analysis_latency_ms": round(
                    result.coreference_analysis_latency_ms, 3
                ),
            },
            indent=2,
        )
    )


def run_demo(
    enable_coref: bool = True,
    enable_multihop: bool = True,
    adaptive_gating: bool = True,
) -> None:
    query = "How does climate change affect precipitation?"
    documents = [
        "Climate change alters the global hydrological cycle by increasing evaporation and changing storm tracks.",
        "The office kitchen is closed on Fridays.",
        "Warmer temperatures intensify evaporation, which can increase rainfall in some regions and reduce it in others.",
    ]
    result = ContextCompressor().compress(
        query=query,
        documents=documents,
        threshold=None if adaptive_gating else 0.25,
        max_tokens=80,
        enable_coref=enable_coref,
        enable_multihop=enable_multihop,
        adaptive_gating=adaptive_gating,
    )
    _print_compression(result)


def run_benchmark(
    cases_path: str | None = None,
    enable_coref: bool = True,
    enable_multihop: bool = True,
    adaptive_gating: bool = True,
) -> None:
    query = "How does climate change affect precipitation?"
    documents = [
        "Climate change alters the global hydrological cycle by increasing evaporation and changing storm tracks.",
        "The office kitchen is closed on Fridays.",
        "Warmer temperatures intensify evaporation, which can increase rainfall in some regions and reduce it in others.",
    ]
    if cases_path:
        cases = json.loads(Path(cases_path).read_text(encoding="utf-8"))
        if not isinstance(cases, list):
            raise ValueError(
                "Benchmark cases JSON must contain a list of query/document objects."
            )
        report = benchmark_query_set(
            cases,
            enable_coref=enable_coref,
            enable_multihop=enable_multihop,
            adaptive_gating=adaptive_gating,
        )
    else:
        metrics = benchmark_rag_pipeline(
            query,
            documents,
            answer=(
                "Climate change changes rainfall patterns by increasing evaporation "
                "and shifting storms."
            ),
            enable_coref=enable_coref,
            enable_multihop=enable_multihop,
            adaptive_gating=adaptive_gating,
        )
        report = {
            "estimated_original_word_count": metrics.estimated_original_word_count,
            "estimated_compressed_word_count": metrics.estimated_compressed_word_count,
            "estimated_word_reduction_percent": round(
                metrics.estimated_word_reduction_percent, 2
            ),
            "baseline_latency_ms": round(metrics.baseline_latency_ms, 2),
            "enhanced_latency_ms": round(metrics.latency_ms, 2),
            "latency_overhead_ms": round(metrics.latency_overhead_ms, 2),
            "baseline_answer_similarity_proxy": round(
                metrics.baseline_answer_similarity, 4
            ),
            "enhanced_answer_similarity_proxy": round(metrics.answer_similarity, 4),
            "answer_similarity_gain_proxy": round(
                metrics.answer_similarity_gain, 4
            ),
            "query_complexity_score": round(metrics.query_complexity_score, 4),
            "query_intent_type": metrics.query_intent_type,
        }
    print(json.dumps(report, indent=2))


def run_compress(
    path: str | None = None,
    enable_coref: bool = True,
    enable_multihop: bool = True,
    adaptive_gating: bool = True,
) -> None:
    query = "What causes climate change?"
    docs = [
        "Greenhouse gases trap heat in the atmosphere and raise the average temperature of the planet.",
        "The meeting starts at 4 p.m. and the room is on the third floor.",
        "Human activities such as fossil fuel combustion emit carbon dioxide that amplifies the greenhouse effect.",
    ]
    if path:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        query = payload.get("query", query)
        docs = payload.get("documents", docs)

    result = ContextCompressor().compress(
        query=query,
        documents=docs,
        threshold=None if adaptive_gating else 0.3,
        max_tokens=80,
        enable_coref=enable_coref,
        enable_multihop=enable_multihop,
        adaptive_gating=adaptive_gating,
    )
    _print_compression(result)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Token-aware semantic context compressor CLI"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    demo_parser = subparsers.add_parser(
        "demo", help="Run the built-in demonstration pipeline"
    )
    _add_feature_flags(demo_parser)

    compress_parser = subparsers.add_parser(
        "compress", help="Compress a query-document payload"
    )
    compress_parser.add_argument(
        "--payload",
        type=str,
        default=None,
        help="Optional JSON file with query and documents",
    )
    _add_feature_flags(compress_parser)

    benchmark_parser = subparsers.add_parser(
        "benchmark", help="Compare fixed-rule and research-feature compression"
    )
    benchmark_parser.add_argument(
        "--cases",
        type=str,
        default=None,
        help="Optional JSON list of query/document/answer cases, grouped by inferred intent.",
    )
    _add_feature_flags(benchmark_parser)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    feature_flags = (args.enable_coref, args.enable_multihop, args.adaptive_gating)
    if args.command == "demo":
        run_demo(*feature_flags)
    elif args.command == "benchmark":
        run_benchmark(args.cases, *feature_flags)
    elif args.command == "compress":
        run_compress(args.payload, *feature_flags)


if __name__ == "__main__":
    main()
