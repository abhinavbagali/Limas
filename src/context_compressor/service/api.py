from __future__ import annotations

import asyncio
import io
import logging
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from fastapi.responses import FileResponse
from fastapi import FastAPI, File, HTTPException, UploadFile
from openpyxl import load_workbook
from pydantic import BaseModel, Field
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from ..compression.compressor import ContextCompressor
from ..evaluation.benchmark import _jaccard_similarity
from ..evaluation.comparison_metrics import (
    DEFAULT_WORKBOOK,
    WORKSHEET_NAME,
    append_comparison_metrics,
)
from .groq_client import (
    GroqConfigurationError,
    GroqRequestError,
    generate_answer,
    get_groq_model,
)

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")

class CompressRequest(BaseModel):
    query: str = Field(..., description="User query to evaluate the retrieved context against.")
    documents: List[str] = Field(..., description="Retrieved document chunks or passages.")
    threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    top_k: Optional[int] = Field(default=None, ge=1)
    max_tokens: Optional[int] = Field(default=None, ge=1)
    enable_coref: bool = True
    enable_multihop: bool = True
    adaptive_gating: bool = True


class SentenceAuditResponse(BaseModel):
    sentence_index: int
    text: str
    isolated_score: float
    pairwise_gain: float
    final_weight: float
    retained: bool
    atomic_group_id: Optional[int]
    retention_reason: Optional[str]
    discard_reason: Optional[str]


class CompressResponse(BaseModel):
    compressed_text: str
    selected_sentences: List[str]
    scores: List[float]
    sentence_audit: List[SentenceAuditResponse]
    estimated_original_word_count: int
    estimated_compressed_word_count: int
    estimated_word_reduction_percent: float
    compression_ratio: float
    query_complexity_score: float
    query_intent_type: str
    query_entity_count: int
    complexity_signals: List[str]
    dynamic_threshold_used: float
    dynamic_token_ratio_limit: Optional[float]
    preserved_coreferences_count: int
    retained_sentence_indices: List[int]
    isolated_scoring_latency_ms: float
    pairwise_scoring_latency_ms: float
    coreference_analysis_latency_ms: float


class CompareRequest(BaseModel):
    query: str = Field(..., min_length=1)
    documents: List[str] = Field(..., min_length=1)
    test_case: Optional[str] = None
    expected_answer: Optional[str] = None
    threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    top_k: Optional[int] = Field(default=None, ge=1)
    max_tokens: Optional[int] = Field(default=None, ge=1)
    enable_coref: bool = True
    enable_multihop: bool = True
    adaptive_gating: bool = True


class CompareResponse(BaseModel):
    model: str
    test_case: Optional[str]
    compressed_text: str
    selected_sentences: List[str]
    scores: List[float]
    sentence_audit: List[SentenceAuditResponse]
    estimated_original_word_count: int
    estimated_compressed_word_count: int
    estimated_word_reduction_percent: float
    compression_ratio: float
    query_complexity_score: float
    query_intent_type: str
    query_entity_count: int
    complexity_signals: List[str]
    dynamic_threshold_used: float
    dynamic_token_ratio_limit: Optional[float]
    preserved_coreferences_count: int
    retained_sentence_indices: List[int]
    isolated_scoring_latency_ms: float
    pairwise_scoring_latency_ms: float
    coreference_analysis_latency_ms: float
    compression_latency_ms: float
    without_compressor_answer: str
    with_compressor_answer: str
    without_compressor_llm_latency_ms: float
    with_compressor_llm_latency_ms: float
    without_compressor_prompt_tokens: Optional[int]
    with_compressor_prompt_tokens: Optional[int]
    actual_prompt_tokens_saved: Optional[int]
    actual_prompt_token_reduction_percent: Optional[float]
    without_compressor_completion_tokens: Optional[int]
    with_compressor_completion_tokens: Optional[int]
    without_compressor_answer_similarity: Optional[float]
    with_compressor_answer_similarity: Optional[float]
    metrics_saved: bool
    metrics_save_error: Optional[str]


class UploadedDocumentResponse(BaseModel):
    filename: str
    passages: list[str]
    page_count: int


def _numeric_values(rows: list[dict[str, object]], key: str) -> list[float]:
    return [
        float(value)
        for row in rows
        if isinstance((value := row.get(key)), (int, float)) and not isinstance(value, bool)
    ]


def _average(values: list[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def _load_analytics_rows() -> list[dict[str, object]]:
    if not DEFAULT_WORKBOOK.exists():
        return []
    workbook = load_workbook(DEFAULT_WORKBOOK, read_only=True, data_only=True)
    try:
        if WORKSHEET_NAME not in workbook.sheetnames:
            return []
        worksheet = workbook[WORKSHEET_NAME]
        records = worksheet.iter_rows(values_only=True)
        headers = next(records, ())
        return [
            {str(header): value for header, value in zip(headers, values) if header}
            for values in records
        ]
    finally:
        workbook.close()


def _load_paired_analytics_rows() -> list[dict[str, object]]:
    return [
        row
        for row in _load_analytics_rows()
        if isinstance(row.get("Without Compressor - Total Latency (ms)"), (int, float))
    ]


app = FastAPI(title="Limas — Subcortical Context Compressor", version="0.1.0")
compressor = ContextCompressor()
UI_PATH = Path(__file__).parent / "static" / "index.html"


@app.get("/", include_in_schema=False)
async def pipeline_ui() -> FileResponse:
    return FileResponse(UI_PATH)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "limas"}


@app.get("/config")
async def runtime_config() -> dict[str, str | bool]:
    return {
        "groq_configured": bool(os.getenv("GROQ_API_KEY")),
        "model": get_groq_model(),
    }


@app.post("/upload_pdf", response_model=UploadedDocumentResponse)
def upload_document(file: UploadFile = File(...)) -> UploadedDocumentResponse:
    filename = Path(file.filename or "").name
    extension = Path(filename).suffix.lower()
    if extension not in {".pdf", ".txt"}:
        raise HTTPException(status_code=415, detail="Upload a PDF or plain-text (.txt) file.")

    content = file.file.read(25 * 1024 * 1024 + 1)
    if len(content) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Uploaded files must be 25 MB or smaller.")
    if not content:
        raise HTTPException(status_code=422, detail="The uploaded file is empty.")

    if extension == ".txt":
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=422, detail="Text files must use UTF-8 encoding.") from exc
        normalized_text = text.replace("\r\n", "\n").replace("\r", "\n")
        passages = [part.strip() for part in normalized_text.split("\n\n") if part.strip()]
        page_count = 1
    else:
        try:
            reader = PdfReader(io.BytesIO(content))
            passages = [
                text.strip()
                for page in reader.pages
                if (text := page.extract_text() or "").strip()
            ]
        except (PdfReadError, OSError, ValueError) as exc:
            logger.info("Could not parse uploaded PDF %s: %s", filename, exc)
            raise HTTPException(status_code=422, detail="The uploaded PDF could not be parsed.") from exc
        page_count = len(reader.pages)

    if not passages:
        raise HTTPException(
            status_code=422,
            detail="No extractable text was found. Scanned PDFs require OCR before upload.",
        )
    return UploadedDocumentResponse(filename=filename, passages=passages, page_count=page_count)


@app.get("/analytics")
def analytics() -> dict[str, object]:
    rows = _load_paired_analytics_rows()
    prompt_reductions = _numeric_values(rows, "Prompt Token Reduction (%) (Groq actual)")
    latency_savings = _numeric_values(rows, "Latency Saved (ms)")
    quality_scores = _numeric_values(rows, "With Compressor - Reference Similarity")
    coreference_counts = _numeric_values(rows, "Preserved Coreferences")
    intents: dict[str, int] = {}
    for row in rows:
        intent = row.get("Query Intent Type")
        if isinstance(intent, str) and intent.strip():
            label = intent.strip().replace("_", "-").title()
            intents[label] = intents.get(label, 0) + 1
    intent_distribution = [
        {"name": name, "count": count}
        for name, count in sorted(intents.items(), key=lambda item: item[0])
    ]

    history = []
    for index, row in enumerate(rows[-105:], start=max(1, len(rows) - 104)):
        saved = row.get("Prompt Token Reduction (%) (Groq actual)")
        history.append({
            "run_number": index,
            "timestamp": row.get("Timestamp (UTC)"),
            "saved_percent": float(saved) if isinstance(saved, (int, float)) else None,
            "coref_edges": int(row["Preserved Coreferences"]) if isinstance(row.get("Preserved Coreferences"), (int, float)) else 0,
            "latency_saved_ms": float(row["Latency Saved (ms)"]) if isinstance(row.get("Latency Saved (ms)"), (int, float)) else None,
        })

    chart_rows = []
    for index, row in enumerate(rows[-10:], start=max(1, len(rows) - 9)):
        chart_rows.append({
            "run_number": index,
            "test_case": row.get("Test Case") or f"Run {index}",
            "baseline_prompt_tokens": row.get("Without Compressor - Prompt Tokens (Groq actual)"),
            "compressed_prompt_tokens": row.get("With Compressor - Prompt Tokens (Groq actual)"),
            "latency_saved_ms": row.get("Latency Saved (ms)"),
        })

    return {
        "runs_total": len(rows),
        "avg_prompt_token_reduction_percent": _average(prompt_reductions),
        "avg_latency_saved_ms": _average(latency_savings),
        "avg_quality_retention_percent": (
            _average(quality_scores) * 100 if quality_scores else None
        ),
        "coreferences_preserved": int(sum(coreference_counts)),
        "activity": history,
        "performance": chart_rows,
        "intent_distribution": intent_distribution,
        "dynamic_threshold_range": {
            "min": min(_numeric_values(rows, "Dynamic Threshold Used"), default=None),
            "max": max(_numeric_values(rows, "Dynamic Threshold Used"), default=None),
        },
    }


@app.post("/compress", response_model=CompressResponse)
async def compress(request: CompressRequest) -> CompressResponse:
    result = compressor.compress(
        query=request.query,
        documents=request.documents,
        threshold=request.threshold,
        top_k=request.top_k,
        max_tokens=request.max_tokens,
        enable_coref=request.enable_coref,
        enable_multihop=request.enable_multihop,
        adaptive_gating=request.adaptive_gating,
    )
    return CompressResponse(
        compressed_text=result.compressed_text,
        selected_sentences=result.selected_sentences,
        scores=result.scores,
        sentence_audit=[
            SentenceAuditResponse(**asdict(item)) for item in result.sentence_audit
        ],
        estimated_original_word_count=result.estimated_original_word_count,
        estimated_compressed_word_count=result.estimated_compressed_word_count,
        estimated_word_reduction_percent=result.estimated_word_reduction_percent,
        compression_ratio=result.compression_ratio,
        query_complexity_score=result.query_complexity_score,
        query_intent_type=result.query_intent_type,
        query_entity_count=result.query_entity_count,
        complexity_signals=result.complexity_signals,
        dynamic_threshold_used=result.dynamic_threshold_used,
        dynamic_token_ratio_limit=result.dynamic_token_ratio_limit,
        preserved_coreferences_count=result.preserved_coreferences_count,
        retained_sentence_indices=result.retained_sentence_indices,
        isolated_scoring_latency_ms=result.isolated_scoring_latency_ms,
        pairwise_scoring_latency_ms=result.pairwise_scoring_latency_ms,
        coreference_analysis_latency_ms=result.coreference_analysis_latency_ms,
    )


@app.post("/compare", response_model=CompareResponse)
async def compare(request: CompareRequest) -> CompareResponse:
    if not request.query.strip():
        raise HTTPException(status_code=422, detail="Query must not be blank.")
    if any(not document.strip() for document in request.documents):
        raise HTTPException(status_code=422, detail="Passages must not contain blank entries.")

    compression_start = time.perf_counter()
    compressed = compressor.compress(
        query=request.query,
        documents=request.documents,
        threshold=request.threshold,
        top_k=request.top_k,
        max_tokens=request.max_tokens,
        enable_coref=request.enable_coref,
        enable_multihop=request.enable_multihop,
        adaptive_gating=request.adaptive_gating,
    )
    compression_latency_ms = (time.perf_counter() - compression_start) * 1000.0
    original_context = "\n\n".join(request.documents)

    generation_results = await asyncio.gather(
        generate_answer(request.query, original_context),
        generate_answer(request.query, compressed.compressed_text),
        return_exceptions=True,
    )
    baseline_result, compressed_result = generation_results
    configuration_errors: list[str] = []
    request_errors: list[str] = []
    for branch, result in (
        ("baseline", baseline_result),
        ("compressed", compressed_result),
    ):
        if isinstance(result, GroqConfigurationError):
            configuration_errors.append(f"{branch}: {result}")
        elif isinstance(result, GroqRequestError):
            request_errors.append(f"{branch}: {result}")
        elif isinstance(result, BaseException):
            raise result
    if configuration_errors:
        raise HTTPException(
            status_code=503,
            detail="Groq configuration failed: " + "; ".join(configuration_errors),
        )
    if request_errors:
        raise HTTPException(
            status_code=502,
            detail="Groq generation failed: " + "; ".join(request_errors),
        )

    baseline = baseline_result
    compressed_answer = compressed_result

    baseline_similarity = (
        _jaccard_similarity(request.expected_answer, baseline.answer)
        if request.expected_answer and request.expected_answer.strip()
        else None
    )
    compressed_similarity = (
        _jaccard_similarity(request.expected_answer, compressed_answer.answer)
        if request.expected_answer and request.expected_answer.strip()
        else None
    )
    actual_prompt_tokens_saved = None
    actual_prompt_token_reduction_percent = None
    if baseline.prompt_tokens is not None and compressed_answer.prompt_tokens is not None:
        actual_prompt_tokens_saved = baseline.prompt_tokens - compressed_answer.prompt_tokens
        if baseline.prompt_tokens > 0:
            actual_prompt_token_reduction_percent = (
                actual_prompt_tokens_saved / baseline.prompt_tokens * 100.0
            )

    baseline_total_ms = baseline.latency_ms
    compressed_total_ms = compression_latency_ms + compressed_answer.latency_ms

    metric_values = {
        "Test Case": request.test_case or "",
        "Query": request.query,
        "Model": get_groq_model(),
        "Retrieved Passages": len(request.documents),
        "Sentences Retained": len(compressed.selected_sentences),
        "Query Complexity Score": compressed.query_complexity_score,
        "Query Intent Type": compressed.query_intent_type,
        "Dynamic Threshold Used": compressed.dynamic_threshold_used,
        "Dynamic Token Ratio Limit": compressed.dynamic_token_ratio_limit,
        "Preserved Coreferences": compressed.preserved_coreferences_count,
        "Retained Sentence Indices": ",".join(
            str(index) for index in compressed.retained_sentence_indices
        ),
        "Isolated Scoring Latency (ms)": compressed.isolated_scoring_latency_ms,
        "Pairwise Scoring Latency (ms)": compressed.pairwise_scoring_latency_ms,
        "Coreference Analysis Latency (ms)": compressed.coreference_analysis_latency_ms,
        "Compression Latency (ms)": compression_latency_ms,
        "Without Compressor - LLM Latency (ms)": baseline.latency_ms,
        "With Compressor - LLM Latency (ms)": compressed_answer.latency_ms,
        "Without Compressor - Total Latency (ms)": baseline_total_ms,
        "With Compressor - Total Latency (ms)": compressed_total_ms,
        "Latency Saved (ms)": baseline_total_ms - compressed_total_ms,
        "Without Compressor - Prompt Tokens (Groq actual)": baseline.prompt_tokens,
        "With Compressor - Prompt Tokens (Groq actual)": compressed_answer.prompt_tokens,
        "Prompt Tokens Saved (Groq actual)": actual_prompt_tokens_saved,
        "Prompt Token Reduction (%) (Groq actual)": actual_prompt_token_reduction_percent,
        "Without Compressor - Completion Tokens (API)": baseline.completion_tokens,
        "With Compressor - Completion Tokens (API)": compressed_answer.completion_tokens,
        "Without Compressor - Answer": baseline.answer,
        "With Compressor - Answer": compressed_answer.answer,
        "Expected Answer": request.expected_answer or "",
        "Without Compressor - Reference Similarity": baseline_similarity,
        "With Compressor - Reference Similarity": compressed_similarity,
    }

    metrics_saved = True
    metrics_save_error = None
    try:
        append_comparison_metrics(metric_values)
    except (OSError, PermissionError) as exc:
        logger.exception("Could not save comparison metrics workbook")
        metrics_saved = False
        metrics_save_error = (
            "LLM comparison succeeded, but metrics could not be saved. "
            "Close reports/eval_met.xlsx if it is open and try the comparison again."
        )

    return CompareResponse(
        model=get_groq_model(),
        test_case=request.test_case,
        compressed_text=compressed.compressed_text,
        selected_sentences=compressed.selected_sentences,
        scores=compressed.scores,
        sentence_audit=[
            SentenceAuditResponse(**asdict(item)) for item in compressed.sentence_audit
        ],
        estimated_original_word_count=compressed.estimated_original_word_count,
        estimated_compressed_word_count=compressed.estimated_compressed_word_count,
        estimated_word_reduction_percent=compressed.estimated_word_reduction_percent,
        compression_ratio=compressed.compression_ratio,
        query_complexity_score=compressed.query_complexity_score,
        query_intent_type=compressed.query_intent_type,
        query_entity_count=compressed.query_entity_count,
        complexity_signals=compressed.complexity_signals,
        dynamic_threshold_used=compressed.dynamic_threshold_used,
        dynamic_token_ratio_limit=compressed.dynamic_token_ratio_limit,
        preserved_coreferences_count=compressed.preserved_coreferences_count,
        retained_sentence_indices=compressed.retained_sentence_indices,
        isolated_scoring_latency_ms=compressed.isolated_scoring_latency_ms,
        pairwise_scoring_latency_ms=compressed.pairwise_scoring_latency_ms,
        coreference_analysis_latency_ms=compressed.coreference_analysis_latency_ms,
        compression_latency_ms=compression_latency_ms,
        without_compressor_answer=baseline.answer,
        with_compressor_answer=compressed_answer.answer,
        without_compressor_llm_latency_ms=baseline.latency_ms,
        with_compressor_llm_latency_ms=compressed_answer.latency_ms,
        without_compressor_prompt_tokens=baseline.prompt_tokens,
        with_compressor_prompt_tokens=compressed_answer.prompt_tokens,
        actual_prompt_tokens_saved=actual_prompt_tokens_saved,
        actual_prompt_token_reduction_percent=actual_prompt_token_reduction_percent,
        without_compressor_completion_tokens=baseline.completion_tokens,
        with_compressor_completion_tokens=compressed_answer.completion_tokens,
        without_compressor_answer_similarity=baseline_similarity,
        with_compressor_answer_similarity=compressed_similarity,
        metrics_saved=metrics_saved,
        metrics_save_error=metrics_save_error,
    )
