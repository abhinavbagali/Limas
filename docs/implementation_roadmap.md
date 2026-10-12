# Limas retrieval implementation roadmap

Execution branch: `feature/long-pdf-retrieval` (created from local `main`).

| Status | Phase | Objective |
|---|---|---|
| [x] | 0 | Preserve baseline and verify local app |
| [x] | 1 | Define retrieval/compression pipeline contract |
| [x] | 2 | PDF ingestion and page provenance |
| [x] | 3 | Token-aware overlapping chunking |
| [x] | 4 | Dense first-stage retrieval and index cache |
| [x] | 5 | Cross-encoder reranking |
| [x] | 6 | Compression integration and token budget |
| [x] | 7 | Fair paired comparison and prompt accounting |
| [x] | 8 | API modernization with legacy compatibility |
| [x] | 9 | Data-only dashboard wiring |
| [ ] | 10 | Short/medium/long benchmark |
| [x] | 11 | Model lifecycle and memory optimization |

## Phase 0 baseline (2026-10-12)

- Branch created from local `main`; local `main` was 3 commits behind `origin/main`.
- `python tests/test_pipeline.py`: 24 tests, 0 failures, 0 errors, 1 skipped (PyTorch unavailable).
- `pytest tests/` could not run because pytest is not installed in the active Python 3.13 environment. The repository's unittest runner was used instead.
- `.env` is Git-ignored (`git check-ignore .env` returned `.env`).
- Live `/compare` smoke test succeeded through Groq: HTTP 200, 140 baseline prompt tokens, 131 compressed prompt tokens, workbook save succeeded. This added a 13th paired run.
- Current workbook: 13 paired runs, mean actual prompt-token reduction 11.10%, mean net latency saved -212.90 ms. The document's older 9-run/8.4%/-265 ms snapshot is stale.
- `python -m context_compressor.cli --help` succeeded; Uvicorn started with the new startup hook and `GET /health` returned `{"status":"ok","service":"limas"}`.

## Implementation checks

- Phases 2-3: a generated 50-page text PDF extracted all 50 pages, and 500-token/80-token-overlap chunking retained page ranges and stayed within the configured chunk target.
- Phases 6-8: API tests cover upload, indexing, retrieval, provenance-aware compression, paired comparison under mocked generation, TPM preflight, and legacy passage-array compression.
- Phase 9: the dashboard upload now indexes documents and the existing audit text displays page and retrieval/rerank attribution. CSS and Tailwind files were not edited.
- `pytest tests/ -q`: 36 passed with no skips after installing pytest in the active environment. The first sandboxed run could not write temporary XLSX files; the approved rerun completed successfully.
- Frontend `npx tsc --noEmit` and `npm run build` passed. Vite reports the existing large-chunk and TanStack unused-import warnings.
- Phases 4-5: verified real `sentence-transformers/all-MiniLM-L6-v2` inference (384-dimensional, unit-normalized embeddings; index backend reported `sentence-transformers`) and real Hugging Face cross-encoder scoring. On the fixed 10-query/20-candidate smoke set, MS MARCO pairwise accuracy was 1.00 with 66.14 ms total scoring latency; STSB was 0.90 with 287.41 ms. This small hand-curated set is a smoke benchmark, not a representative relevance evaluation.
- Phase 10 remains open: no real short, medium, and 50+ page benchmark PDFs or labeled queries/reference answers are present. The evaluation harness is ready at `scripts/evaluate_pipeline.py`; no synthetic results were written into the benchmark workbook.
- Phase 11: retrieval models load once through FastAPI lifespan; reranker instances are cached by model, inference batches 16 pairs, and `/index` logs RSS using psutil. A synthetic 50-page indexing profile using the real MiniLM backend peaked at 1,396.55 MB RSS (1,140.84 MB start, 1,278.40 MB end), below 10 GB. A representative corpus profile remains part of Phase 10 evaluation.

## Pipeline contract

`Upload PDF -> page extraction/provenance -> overlap chunking -> dense retrieval -> cross-encoder reranking -> sentence compression with source metadata -> paired generation/evaluation -> workbook and dashboard`.

The existing passage-array `/compress` and `/compare` calls remain supported. Retrieval is a separate stage; compression accepts the selected retrieved passages. Document and index caches are process-local and are cleared when the API process restarts.

Model downloads are lazy and optional in minimal installations. The API reports `embedding_backend` from `/index`; `offline-hash-fallback` is a development fallback and should not be treated as dense semantic retrieval. `/compare` defaults to a paired 8,000 TPM budget, reserves completion capacity, splits the prompt allowance across its two calls, and uses `tiktoken` when its `o200k_base` encoding is available. Groq-reported usage remains the authoritative post-request count.
