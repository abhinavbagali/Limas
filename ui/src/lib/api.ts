export interface SentenceAudit {
  sentence_index: number;
  text: string;
  isolated_score: number;
  pairwise_gain: number;
  final_weight: number;
  retained: boolean;
  atomic_group_id: number | null;
  retention_reason: string | null;
  discard_reason: string | null;
  doc_id?: string | null;
  page_start?: number | null;
  page_end?: number | null;
  retrieval_rank?: number | null;
  rerank_rank?: number | null;
  retrieval_score?: number | null;
  rerank_score?: number | null;
}

export interface RetrievedChunk {
  chunk_id: string; doc_id: string; text: string; page_start: number; page_end: number;
  section_title: string | null; token_count: number; retrieval_score: number;
  retrieval_rank: number; rerank_score: number | null; rerank_rank: number | null;
}

export interface CompressResult {
  compressed_text: string;
  selected_sentences: string[];
  sentence_audit: SentenceAudit[];
  estimated_original_word_count: number;
  estimated_compressed_word_count: number;
  estimated_word_reduction_percent: number;
  query_complexity_score: number;
  query_intent_type: string;
  dynamic_threshold_used: number;
  preserved_coreferences_count: number;
  retained_sentence_indices: number[];
  retrieved_chunks?: RetrievedChunk[];
}

export interface CompareResult extends CompressResult {
  model: string;
  test_case: string | null;
  without_compressor_answer: string;
  with_compressor_answer: string;
  without_compressor_llm_latency_ms: number;
  with_compressor_llm_latency_ms: number;
  without_compressor_prompt_tokens: number | null;
  with_compressor_prompt_tokens: number | null;
  without_compressor_completion_tokens: number | null;
  with_compressor_completion_tokens: number | null;
  actual_prompt_tokens_saved: number | null;
  actual_prompt_token_reduction_percent: number | null;
  without_compressor_answer_similarity: number | null;
  with_compressor_answer_similarity: number | null;
  metrics_saved: boolean;
  metrics_save_error: string | null;
}

export interface AnalyticsResult {
  runs_total: number;
  avg_prompt_token_reduction_percent: number | null;
  avg_latency_saved_ms: number | null;
  avg_quality_retention_percent: number | null;
  coreferences_preserved: number;
  activity: Array<{
    run_number: number;
    timestamp: string | null;
    saved_percent: number | null;
    coref_edges: number;
    latency_saved_ms: number | null;
  }>;
  performance: Array<{
    run_number: number;
    test_case: string;
    baseline_prompt_tokens: number | null;
    compressed_prompt_tokens: number | null;
    latency_saved_ms: number | null;
  }>;
  intent_distribution: Array<{ name: string; count: number }>;
  dynamic_threshold_range: { min: number | null; max: number | null };
}

export interface RuntimeConfig {
  groq_configured: boolean;
  model: string;
}

export interface UploadResult {
  filename: string;
  passages: string[];
  page_count: number;
  doc_id: string;
  pages: Array<{ doc_id: string; page_number: number; text: string; extraction_status: string; section_title: string | null }>;
  indexed: boolean;
}

export interface IndexResult {
  doc_id: string; page_count: number; chunk_count: number; embedding_backend: string;
  embedding_model: string | null;
}

export interface CompressionOptions {
  query: string;
  documents: string[];
  expected_answer?: string | null;
  test_case?: string | null;
  threshold?: number;
  top_k: number;
  max_tokens: number;
  enable_coref: boolean;
  enable_multihop: boolean;
  adaptive_gating: boolean;
  doc_id?: string | null;
  retrieval_top_k?: number;
  rerank_top_k?: number;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const detail =
      typeof data === "object" && data !== null && "detail" in data
        ? String(data.detail)
        : `Request failed (${response.status}).`;
    throw new Error(detail);
  }
  return data as T;
}

export function getRuntimeConfig() {
  return request<RuntimeConfig>("/config");
}

export function getAnalytics() {
  return request<AnalyticsResult>("/analytics");
}

export function uploadDocument(file: File) {
  const body = new FormData();
  body.append("file", file);
  return request<UploadResult>("/upload_pdf", { method: "POST", body });
}

export function indexDocument(doc_id: string) {
  return request<IndexResult>("/index", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ doc_id }) });
}

export function retrieveDocument(doc_id: string, query: string) {
  return request<RetrievedChunk[]>("/retrieve", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ doc_id, query }) });
}

export function compressContext(options: CompressionOptions) {
  return request<CompressResult>("/compress", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(options),
  });
}

export function compareContexts(options: CompressionOptions) {
  return request<CompareResult>("/compare", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(options),
  });
}
