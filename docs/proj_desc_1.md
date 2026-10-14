# Limas
## Subcortical Context Compression Middleware for RAG Pipelines
## Technical Project Guide, Implementation Reference, and Team Handoff

This document explains what the project currently does, how its code is organized, how a request travels through it, what techniques and frameworks are used, how to run and test it, and which limitations should be kept in mind. It describes the implementation that exists in this repository; it does not claim that planned integrations or quality guarantees are already present.

---

## 1. Project Purpose

The project explores a context-compression stage for Retrieval-Augmented Generation (RAG):

```text
Question -> Retriever -> Retrieved passages -> Context compressor -> LLM prompt -> Answer
```

The retriever and LLM are normally separate systems. The compressor takes a question and passages already retrieved for that question, splits each passage into sentences, estimates sentence relevance to the question, and selects a smaller context. The goal is to reduce prompt context while keeping useful source text.

The dashboard currently demonstrates this operation in a paired experiment:

```text
                        -> Full supplied passages -> Groq -> Baseline answer
Question + passages ----|
                        -> Compressor -> Selected sentences -> Groq -> Compressed answer
```

Both branches use the same query, Groq model, and grounding instructions. Their generated answers and measured metrics can then be compared.

### What the project currently is

- A working sentence-level compressor foundation
- A FastAPI service exposing compression and paired comparison APIs
- A browser dashboard that runs the real compression and Groq generation paths
- An Excel workbook for recording paired comparison metrics
- A Python CLI and automated test script

### What it is not yet

- It does not retrieve documents from Qdrant, Chroma, or another vector database. A user supplies the passages.
- It does not fine-tune or package a relevance/entailment model.
- Completed Groq requests report provider-reported prompt-token counts, which are authoritative per-request usage values. The compressor's pre-generation pruning budget remains a word-count heuristic, not an exact Groq tokenizer cap.
- It does not run LongBench, Multi-Doc QA, or another rigorous end-to-end quality benchmark.
- It does not guarantee that compressed answers are factually equivalent to baseline answers.

### Project evaluation snapshot (2026-10-09)

This revision is a working local research prototype, not a production-ready RAG
service. The primary React dashboard and FastAPI endpoints have been build-,
type-, and regression-tested; paired comparisons use mocked Groq calls in
automated tests, so those tests do not validate external Groq availability or
answer quality.

At the time of this snapshot, `GET /analytics` reports **9 saved paired runs**:

| Workbook measure | Current value | Interpretation |
|---|---:|---|
| Mean actual prompt-token reduction | 8.4% | Real Groq prompt usage for the recorded runs; small and sample-dependent. |
| Mean net latency saved | -265 ms | Negative means the compressed path was slower after including compression time. |
| Mean compressed-answer Jaccard | 36.4% | Lexical overlap against references where available; not a semantic-quality score. |
| Preserved discourse edges | 2 | Count of edges logged across these runs, not a quality measurement. |

The recorded latency-saved values are negative (one is effectively zero),
indicating that the current workbook does **not** demonstrate net latency
improvement. Nine runs are too few and uncontrolled to establish a general
performance result. Re-run a larger, randomized, representative evaluation
before making product or research claims. Analytics are a changing workbook
snapshot and should not be treated as fixed benchmark results.

---

## 2. End-to-End Runtime Flow

### 2.1 Dashboard comparison, step by step

1. **Input collection:** The user enters a query, retrieved passages, optional expected/reference answer, and pruning controls in the Limas dashboard.
2. **Passage preparation:** The dashboard separates passages on blank lines and sends them as a JSON array. PDF/TXT uploads are extracted through `/upload_pdf`.
3. **Server-side compression:** `POST /compare` runs `ContextCompressor.compress()` over the query and passages. It measures compression elapsed time.
4. **Concurrent LLM generation:** The server builds grounded prompts using the query and (a) every supplied passage and (b) selected compressed text, then sends both Groq requests concurrently with `asyncio.gather()`.
5. **Quality proxy:** If an expected answer was supplied, the server compares each generated answer with it using lexical Jaccard similarity.
6. **Metric persistence:** The server appends a paired row to `reports/eval_met.xlsx`, worksheet `eval_met`.
7. **Response rendering:** The browser displays each prompt context and answer in its own tab, with Groq-reported prompt/completion counts, actual prompt-token savings/reduction, response latencies, the full per-sentence score audit, and saving status. The local word-count budget is not shown as an actual token metric.

The two Groq requests run concurrently, so the generation wait is approximately the slower of the two provider requests rather than their sum. Each comparison still uses two API requests and consumes the user's Groq quota twice. Model service load and network variance can influence latency and answer variation. If either provider request fails, the endpoint returns an error with the failing branch and provider diagnostic; it does not save a partial comparison.

### 2.2 Request/data-flow diagram

```text
Browser UI (primary React/TanStack Start app in `ui/`)
    |
    | Vite dev proxy -> FastAPI at http://127.0.0.1:8000
    | POST /compare (or POST /compress)
    | { query, documents[], expected_answer?, threshold?, top_k?, max_tokens?,
    |   enable_coref?, enable_multihop?, adaptive_gating? }
    v
FastAPI service (`src/context_compressor/service/api.py`)
    |
    +--> ContextCompressor.compress(query, documents, controls)
    |       |
    |       +--> sentence splitting
    |       +--> batched isolated and contiguous-pair scoring
    |       +--> query-complexity adaptive threshold and word-ratio budget
    |       +--> antecedent/pair dependency closure into atomic blocks
    |       +--> top-k and estimated word-budget pruning
    |
    +--> Groq chat completion with all original passages (baseline)
    |
    +--> Groq chat completion with compressed context
    |
    +--> optional expected-answer lexical similarity
    |
    +--> append paired metrics to reports/eval_met.xlsx
    |
    v
JSON response -> React result tabs, sentence diff/audit, and metrics
```

The FastAPI `GET /` endpoint separately serves the self-contained static
fallback at `service/static/index.html`; it is not the React/TanStack frontend.

### 2.3 Current API routes

| Route | Method | Purpose |
|---|---|---|
| `/` | GET | Serves the legacy self-contained static dashboard fallback (the primary React UI runs separately on port 3000). |
| `/health` | GET | Returns a basic service health response. It does not check Groq credentials or call Groq. |
| `/config` | GET | Returns the configured model name and a boolean indicating whether `GROQ_API_KEY` is present. It never returns the key. |
| `/compress` | POST | Compresses supplied passages without calling an LLM. |
| `/compare` | POST | Compresses passages, calls Groq with both full and compressed context, calculates optional quality proxies, and saves a paired workbook row. |
| `/upload_pdf` | POST | Extracts text passages from uploaded PDF or UTF-8 TXT files; scanned PDFs require OCR before upload. |
| `/analytics` | GET | Aggregates successful paired-run metrics from the Excel workbook for dashboard charts and activity history. |

Both `/compress` and `/compare` accept optional `enable_coref`, `enable_multihop`, and `adaptive_gating` Boolean flags; all default to `true`. The `threshold`, `top_k`, and `max_tokens` controls remain optional. A manually supplied `threshold` overrides only the adaptive threshold; `max_tokens` caps the adaptive local word budget.

Both compression responses return `compression_ratio` (fraction of estimated word count removed), `query_complexity_score`, `query_intent_type`, `query_entity_count`, detected `complexity_signals`, `dynamic_threshold_used`, `dynamic_token_ratio_limit` (null when adaptive gating is disabled), `preserved_coreferences_count`, source-order `retained_sentence_indices`, isolated/pairwise/coreference analysis timings, and a `sentence_audit` item for every candidate sentence. Each audit item reports its source index/text, isolated relevance score, pairwise gain, final weight, retention status, atomic group (for retained sentences), and an explanation of the selection or discard decision. Scores are relevance heuristics, not calibrated probabilities. Counts do not contain actual token counts: local counts are regex word estimates. `/compare` additionally returns exact Groq usage values after both generations complete.

### 2.4 Example `/compare` request

```json
{
  "query": "How does climate change affect precipitation?",
  "documents": [
    "Climate change alters the hydrological cycle and can shift rainfall patterns.",
    "The office kitchen is closed on Fridays.",
    "Warmer air can hold more water vapor and may intensify heavy rainfall."
  ],
  "expected_answer": "Climate change can shift rainfall patterns and intensify heavy rain in some areas.",
  "test_case": "Climate · rainfall changes",
  "enable_coref": true,
  "enable_multihop": true,
  "adaptive_gating": true,
  "threshold": 0.35,
  "top_k": 4,
  "max_tokens": 256
}
```

The fields `expected_answer`, `test_case`, controls, and feature flags are optional. `query` and a non-empty `documents` list are required. Blank query text and blank passage entries are rejected.

The response includes the model, compressed text and selected sentences, compression metrics and per-sentence audit, baseline and compressed answers, both LLM latencies, Groq-reported token usage when present, optional answer similarities, and whether metric writing succeeded. The two generations run concurrently. `/compress` returns the compression metadata and sentence audit without calling Groq.

---

## 3. Repository Layout

```text
capstone/
├── .env.example
├── .gitignore
├── README.md
├── pyproject.toml
├── requirements.txt
├── examples/
│   └── demo_rag.py
├── docs/
│   └── proj_desc_1.md
├── reports/
│   ├── eval_met.xlsx
│   └── pipeline_test_results.txt
├── scripts/
│   └── eval_met_gen.py
├── src/
│   └── context_compressor/
│       ├── __init__.py
│       ├── cli.py
│       ├── config.py
│       ├── coreference.py
│       ├── gating.py
│       ├── scorer.py
│       ├── types.py
│       ├── compression/
│       │   ├── __init__.py
│       │   ├── compressor.py
│       │   └── sentence_splitter.py
│       ├── data/
│       │   ├── __init__.py
│       │   └── preprocessing.py
│       ├── evaluation/
│       │   ├── __init__.py
│       │   ├── benchmark.py
│       │   └── comparison_metrics.py
│       ├── models/
│       │   ├── __init__.py
│       │   └── cross_encoder.py
│       └── service/
│           ├── __init__.py
│           ├── api.py
│           ├── groq_client.py
│           └── static/
│               └── index.html
├── ui/
│   ├── package.json                 # React 19/TanStack Start dependencies and scripts
│   ├── vite.config.ts               # Start, Tailwind v4, and FastAPI proxy
│   └── src/                         # Strict TypeScript app, routes, components, and styles
└── tests/
    └── test_pipeline.py
```

### File responsibility map

| File | Responsibility |
|---|---|
| `pyproject.toml` | Package metadata, `src` package discovery, packaged dashboard HTML, optional spaCy extra, CLI entry point, and pytest Python path. |
| `requirements.txt` | Python dependencies for API, NLP/model, tests, Groq HTTP requests, dotenv loading, and Excel writing. |
| `.env.example` | Safe template showing Groq environment variable names and the default model. It must not contain a real key. |
| `.gitignore` | Excludes `.env`, virtual environments, Python caches, and model artifacts from Git. |
| `config.py` | Defines `RuntimeConfig`, including model name, threshold, top-k, token budget, device, and data directory defaults. |
| `types.py` | Dataclasses for scored sentences, compression results, and local benchmark results. |
| `coreference.py` | Optional spaCy-assisted subject-pronoun detection and deterministic adjacent discourse-link fallback. |
| `gating.py` | Rule-based query intent/complexity features and bounded dynamic cutoff/context ratio. |
| `scorer.py` | Batched isolated scoring plus contiguous-pair relevance gain and scoring timings. |
| `compression/sentence_splitter.py` | Regex-based sentence segmentation. |
| `compression/compressor.py` | Candidate creation, integration of all three research features, atomic selection/budget pruning, and enriched result metadata. |
| `models/cross_encoder.py` | Optional Hugging Face batched inference and lexical heuristic fallback scorer. |
| `data/preprocessing.py` | Synthetic labeled examples and preparation hooks; not a real data downloader/trainer. |
| `evaluation/benchmark.py` | Fixed-rule vs. research-feature timing and lexical proxy comparison, including intent-group aggregation. |
| `evaluation/comparison_metrics.py` | Excel schema, migration, formatting, and paired-row appending including feature metadata. |
| `service/groq_client.py` | Authenticated server-side HTTP requests to Groq and parsing of answer/usage/latency. |
| `service/api.py` | Limas FastAPI routes, request/response validation, concurrent paired generation, file extraction, analytics, and metric recording. |
| `service/static/index.html` | Self-contained Limas fallback dashboard served from the FastAPI root route. |
| `ui/src/routes/index.tsx` | Primary Limas single-page React/TanStack Start UI. |
| `ui/src/components/compressor/Playground.tsx` | API-backed query playground, upload zone, paired results, and sentence audit. |
| `ui/src/components/compressor/Analytics.tsx` | Workbook-driven KPI cards, heatmap, and Recharts performance/intent graphs. |
| `ui/src/styles.css` | Reference-derived design tokens, responsive layouts, and light/dark theme rules. |
| `ui_reference.txt` | Detailed supplied visual/layout specification followed by the React UI. |
| `cli.py` | Command-line demo, local benchmark, and sample compression entry points. |
| `scripts/eval_met_gen.py` | Runs compressor-only metrics and appends a local benchmark row to the shared workbook. |
| `tests/test_pipeline.py` | `unittest` suite that writes the formatted report under `reports/`. |
| `reports/eval_met.xlsx` | Generated workbook containing local and paired comparison records. |
| `reports/pipeline_test_results.txt` | Latest saved test summary and per-test results. |
| `docs/proj_desc_1.md` | Detailed project implementation and handoff guide. |

---

## 4. Compression Methodology

### 4.1 Inputs and output

`ContextCompressor.compress()` takes:

- `query`: question or retrieval query string
- `documents`: one passage string or a sequence of strings
- optional `threshold`: minimum relevance score to keep
- optional `top_k`: maximum selected sentence count
- optional `max_tokens`: maximum local word-count proxy used for pre-generation pruning; this is not a provider-enforced token limit

It returns a `CompressedDocument` containing:

- selected sentence text and combined isolated/pairwise relevance weights
- a `sentence_audit` record for every candidate, including retained and discarded sentences, with scores, source index, atomic group where relevant, and retention/discard reason
- local word-count proxy values used internally by the compressor
- local word-count-proxy reduction percentage
- joined compressed text
- estimated compression ratio, query intent/complexity signals, effective cutoff/context ratio, and original sentence indices
- preserved antecedent count and separate isolated/pairwise/coreference analysis timings

The audit's relevance values are heuristic scores, not calibrated probabilities or explanations of model causality. Candidate sentence indices follow source passage order.

### 4.2 Sentence segmentation

`split_document_into_sentences()`:

1. Returns an empty list for blank input.
2. Trims leading/trailing whitespace and collapses runs of whitespace to one space.
3. Splits after `.`, `!`, or `?` when followed by whitespace.
4. Trims and filters empty fragments.

This is a lightweight regex splitter. It is fast and dependency-free but is not a linguistic sentence-boundary detector. Abbreviations, initials, decimals, quotes, and languages with different punctuation conventions can be segmented incorrectly.

### 4.3 Candidate and batched isolated scoring

The compressor creates one `SentenceItem` for every split sentence. Each item carries the sentence text, a relevance weight, and a stable zero-based index across the supplied passage sequence. `CrossEncoderRelevanceScorer.score_pairs()` batches query/sentence pairs according to `RuntimeConfig.batch_size`. A legacy scorer exposing only `score_single()` remains supported through a per-item compatibility fallback.

`CrossEncoderRelevanceScorer` has two paths:

#### Hugging Face path

- Optional imports load PyTorch and `transformers`.
- By default, the model name is `cross-encoder/stsb-roberta-base`.
- The scorer attempts to load `AutoTokenizer` and `AutoModelForSequenceClassification`, move the model to the configured device, and switch it to evaluation mode.
- Query/candidate pairs are tokenized with padding, truncation, PyTorch tensors, and the configured maximum sequence length.
- Forward inference runs under `torch.no_grad()`.
- Multi-class heads use the second-class softmax probability. A one-logit head uses a sigmoid so the result is monotonic rather than applying softmax to one value (which would always return 1).

**Model caveat:** the default STS-B model is generally a similarity/regression model, not a binary entailment classifier. Sigmoid makes its scalar output rankable but does not calibrate it as relevance probability or factual entailment. A task-tuned relevance model and validation are needed before making accuracy claims.

#### Heuristic fallback path

If model libraries are unavailable or model loading raises an exception, the scorer uses a local lexical heuristic:

1. Lowercase and tokenize with a word/apostrophe regex.
2. Count query and candidate terms with `Counter`.
3. Expand selected hard-coded terms using `SEMANTIC_EXPANSIONS` (for example, `climate` is associated with `warming`, `greenhouse`, `temperature`, `atmosphere`, and `emissions`).
4. Compute capped multiset overlap of expanded query and candidate tokens.
5. Divide overlap by expanded query term count and cap the score at 1.

This heuristic is deterministic but limited: it has a small hand-written vocabulary, has no learned contextual representation, and is not a factual entailment check. It can miss paraphrases and can over-score keyword overlap.

### 4.4 Multi-hop pairwise interdependence scoring

`MultiHopInterdependenceScorer` has two batched stages:

1. **Stage A, isolated relevance:** scores all `(query, sentence)` pairs to produce `R(S_i)`.
2. **Stage B, adjacent joint relevance:** when enabled, forms same-passage contiguous pairs for which at least one isolated score meets the low candidate floor. It batches `(query, S_(i-1) + " " + S_i)` pairs. The estimated conditional gain is `Delta(S_i | S_(i-1)) = max(0, joint_score - R(S_(i-1)))`.
3. **Combined weight:** for sentence `i > 0` in the same passage, `W(S_i) = alpha * R(S_i) + (1-alpha) * Delta(S_i | S_(i-1))`; `alpha` defaults to `0.70`. A sentence without a same-passage predecessor keeps its isolated score.
4. **Atomic relation:** a pair with meaningful joint-score synergy (>0.05 above both isolated scores) forms a predecessor dependency. If the following sentence is selected, its predecessor is pulled into the retained set and the word-budget pruning stage treats the pair as indivisible.

This is a conditional *relevance* gain proxy from a cross-encoder, not NLI entailment. Pairwise scoring adds inference time and only tests adjacent pairs; it does not discover arbitrary non-local chains or prove that the pair supports the answer. The stage timings are returned separately.

### 4.5 Discourse-aware antecedent preservation

`DiscoursePreserver` operates on the ordered sentence list but never creates edges across passage boundaries. If spaCy and `en_core_web_sm` are installed, subject-pronoun dependency annotations (such as `nsubj`/`nsubjpass`) are used. Standard spaCy models do not implement general-purpose coreference resolution, so the analyzer conservatively binds a detected reference to the immediately preceding sentence. Without spaCy/model availability, regex rules detect leading pronominals (`it`, `they`, `this company`, `these results`, etc.) and leading discourse markers (`However`, `Therefore`, `As a result`, etc.).

When a dependent sentence is selected, antecedent dependencies are closed transitively and retained as atomic groups. The count returned as `preserved_coreferences_count` is the number of discourse-link edges whose antecedent and dependent are both retained; pairwise-only dependencies are not counted in this metric. Atomic preservation can exceed `top_k` or the approximate word budget because breaking a selected dependent/antecedent pair would defeat the preservation requirement.

This local heuristic is not entity coreference resolution: it does not resolve pronouns to named entities, detect all anaphora, or rank multiple possible antecedents. It can keep the wrong immediate predecessor in noisy text.

### 4.6 Query-complexity adaptive gating

`QueryComplexityGater` emits an interpretable heuristic score in `[0, 1]`, an intent label (`factual`, `comparative`, or `multi_hop`), a capitalized-span entity-count proxy, and detected feature signals. Comparative terms, reasoning question forms, logical/sequential connectives, multiple entity-like spans, and long queries contribute fixed additive weights; this is not a trained classifier.

The bounded settings are:

- `tau(Q) = 0.75 - 0.45 * complexity(Q)`, clipped to `[0.30, 0.75]`.
- `B(Q) = 0.20 + 0.60 * complexity(Q)`, clipped to `[0.20, 0.80]`.

Higher-complexity queries therefore have a lower cutoff and a larger permitted word-count ratio. An explicit `threshold` is a manual override; an explicit `max_tokens` is an upper bound on the resulting local estimated-word budget. With `adaptive_gating=False`, config/manual threshold and budget behavior is used instead. All returned metadata includes both the query-derived score and the effective threshold.

### 4.7 Selection and token-budget algorithm

Let each candidate be `(index, sentence, W(sentence))`.

1. Select candidates with weight at least the effective threshold; if none pass, use the highest-weight `top_k` fallback.
2. Preserve source order and apply the `top_k` limit to the initial selection.
3. Add antecedents for selected discourse dependents and meaningful pairwise transitions.
4. Construct atomic dependency groups, rank groups by their maximum member weight, and greedily fit groups under the approximate word budget. If no group fits, retain the best complete group even if it exceeds the budget.
5. Restore source order, join retained sentences with spaces, and calculate explicitly labeled estimated-word reduction and ratio.

Because antecedents and pairwise dependencies are mandatory, final retained sentence count may exceed `top_k`; the approximate word budget is soft for a single overlong atomic group. Ordinary non-dependent selections remain bounded by `top_k` before dependency expansion.

### 4.8 Actual Groq prompt-token accounting vs. local pruning budget

The project has two different token-related concepts; do not treat them as interchangeable:

- **Actual Groq prompt usage:** after Groq processes a completion request, its response includes `usage.prompt_tokens` (and `usage.completion_tokens`). `groq_client.py` reads these per-request values, `/compare` returns them, the UI displays them, and the workbook saves them. They are the authoritative token counts for the prompts Groq actually processed and the values to compare with per-request usage in Groq's dashboard/console.
- **Actual prompt tokens saved:** baseline prompt tokens minus compressed prompt tokens.
- **Actual prompt-token reduction percent:** `(baseline_prompt_tokens - compressed_prompt_tokens) / baseline_prompt_tokens * 100`, when both usage values exist and baseline is greater than zero. It is not clamped; negative savings are possible.
- **Completion tokens:** Groq's returned output-token usage for each generated answer, tracked separately from input prompt usage.
- **Local pre-generation budget:** `estimate_word_count(text)` in `compression/compressor.py` counts regex word-like matches. It is only used to make a quick sentence-selection decision before calling Groq. It does not equal provider tokenization and is not used as the reported actual prompt-token reduction.

The provider's authoritative usage value is only available after Groq processes a request. This application has no verified token-count-only endpoint or tokenizer/chat-template implementation guaranteed to match Groq for this model, so it does not pretend an offline estimate is exact. The compressor's `max_tokens` UI/API control is consequently an approximate word-count pruning budget, not an exact provider token cap. Compression-only responses and CLI output name these values `estimated_*_word_count`; they are not labeled as actual tokens.

The exact `usage.prompt_tokens` value is for the entire submitted chat prompt, including system instructions and message formatting, not just the retrieved passage body. Since both branches use the same system prompt and wrappers, the difference between the two Groq-reported prompt counts measures the actual token reduction between the prompts Groq processed. It should match per-request token usage for those requests; a workspace-wide Groq usage dashboard may aggregate requests or update at a different time. If Groq omits usage, actual counts/savings are returned as null rather than replaced with an estimate.

---

## 5. Groq LLM Integration

### 5.1 Credential and model configuration

The API loads `.env` at startup using `python-dotenv` from the project root. Configuration:

```text
GROQ_API_KEY=your_actual_groq_api_key
GROQ_MODEL=openai/gpt-oss-120b
```

`GROQ_MODEL` is optional and defaults to `openai/gpt-oss-120b`. `GROQ_API_KEY` is required only for `/compare`; the health, UI, and compressor-only endpoints can work without it.

`/config` exposes the model name and a boolean `groq_configured`; it does not expose the key. `.env` is excluded by `.gitignore`. The `.env.example` file is safe to commit because its value is only a placeholder.

### 5.2 Request construction

`service/groq_client.py` uses `httpx.AsyncClient` against:

```text
https://api.groq.com/openai/v1/chat/completions
```

The request uses:

- Bearer authentication from the server's `GROQ_API_KEY`
- Configured model name (default `openai/gpt-oss-120b`)
- A system instruction to answer from context only and say when context is insufficient
- User content containing `Context:` and `Question:` sections
- `temperature: 0`
- `max_completion_tokens: 1024`
- A 90-second request timeout and 15-second connect timeout

The code reads the first choice's message content, response `usage.prompt_tokens`, and `usage.completion_tokens`, when supplied. The secret is not put in HTML, browser JavaScript, response JSON, query strings, or logs.

### 5.3 Error behavior

- Missing key -> typed `GroqConfigurationError` -> HTTP 503 with setup instructions.
- Network/timeout errors -> `GroqRequestError` -> HTTP 502 with a useful message.
- Non-success Groq response -> HTTP 502, including a bounded provider error message where available.
- Invalid/empty provider response -> HTTP 502.
- Workbook write failure after successful generation -> the answers still return, but `metrics_saved` is false and the UI displays a warning. The server logs the exception.

The code does not substitute a fake answer when Groq is unavailable. A comparison requires both LLM generations; a failure of either request produces an error response.

### 5.4 Interpreting a paired comparison

The baseline answer is generated with all provided passages. The compressed answer is generated after compression. Both share the same query, configured model, system instruction, temperature, and completion limit.

Differences in answers can be caused by context selection, model nondeterminism/service variance, or position/length effects. A single pair is an illustrative run, not a statistically robust experiment. For stronger evidence, repeat each case and average metrics, randomize request order, keep model/settings fixed, and assess answer quality with a suitable rubric or evaluator.

---

## 6. Dashboard Methodology and Interactions

The primary Limas dashboard is the React 19 + TanStack Start application in `ui/`, following the supplied `ui_reference.txt` layout and design tokens. Run its Vite development server at `http://127.0.0.1:3000/`; the configured proxy forwards API requests to FastAPI at `http://127.0.0.1:8000`. The FastAPI root continues to serve a self-contained HTML fallback at `src/context_compressor/service/static/index.html`.

### Visual areas

- **Input card:** query, retrieved passages, optional reference answer, PDF/text drag-and-drop upload, a scenario selector, a manual threshold, top-K sentence count, and an approximate word-count pruning budget.
- **Research controls:** independent toggles for discourse antecedent preservation, pairwise adjacent-sentence scoring, and adaptive complexity gating. They default on; the manual threshold becomes active only when adaptive gating is off.
- **Paired result tabs:** full baseline context/answer and compressed context/answer, with retained source sentences highlighted.
- **Sentence audit:** expandable table populated from the live `/compare` response, showing isolated score, pairwise gain, final weight, retained/discarded status, atomic group, and reason for every input sentence.
- **Pipeline overview:** Query -> supplied passages -> compressor -> Groq LLM -> answer.
- **Metrics:** Groq-reported prompt and completion tokens when available, per-request LLM latency, net latency impact including compression time, actual prompt-token savings, and query intent/complexity metadata.
- **Analytics:** responsive scorecards, prompt-token/net-latency chart, activity heatmap, and query-intent donut populated from successful paired rows in `reports/eval_met.xlsx`. The latency scorecard and chart explicitly label net latency as including compression time. The answer-overlap scorecard is labelled reference-answer Jaccard and notes it is lexical overlap, not semantic quality.
- **Architecture overview:** descriptions of the discourse preserver, relevance scorer, complexity gater, and Groq/metric integration.
- **Theme button:** toggles light/dark appearance, persists the preference in local storage, and applies the theme class to the document root so Radix portal content (dialogs/tooltips) inherits the same variables. The light and dark palettes use distinct indigo/emerald/cyan accents and higher-contrast slate text; small labels, controls, chart axes, and explanatory copy use a more readable minimum text size.

### Test cases

Included examples cover climate/rainfall, solar energy, and corporate Q3 revenue, alongside a custom scenario. Selecting a case fills the query, passages, and expected-answer inputs; both comparison branches then use those same values. The custom scenario starts blank and can be filled manually.

### Browser/server boundary

The React UI calls the local API through its Vite proxy and never receives the Groq key. The API key remains on the FastAPI server and only that server calls Groq.

---

## 7. Evaluation Metrics and Excel Workbook

The workbook is stored at `reports/eval_met.xlsx`; its worksheet is `eval_met`. Comparison rows are appended by `append_comparison_metrics()` after successful paired generations.

### Workbook columns

1. `Timestamp (UTC)`
2. `Test Case`
3. `Query`
4. `Model`
5. `Retrieved Passages`
6. `Without Compressor - Prompt Tokens (Groq actual)`
7. `With Compressor - Prompt Tokens (Groq actual)`
8. `Prompt Tokens Saved (Groq actual)`
9. `Prompt Token Reduction (%) (Groq actual)`
10. `Sentences Retained`
11. `Compression Latency (ms)`
12. `Without Compressor - LLM Latency (ms)`
13. `With Compressor - LLM Latency (ms)`
14. `Without Compressor - Total Latency (ms)`
15. `With Compressor - Total Latency (ms)`
16. `Latency Saved (ms)`
17. `Without Compressor - Completion Tokens (API)`
18. `With Compressor - Completion Tokens (API)`
19. `Without Compressor - Answer`
20. `With Compressor - Answer`
21. `Expected Answer`
22. `Without Compressor - Reference Similarity`
23. `With Compressor - Reference Similarity`
24. `Legacy Original Context Word Count`
25. `Legacy Compressed Context Word Count`
26. `Legacy Estimated Context Reduction (%)`
27. `Legacy Answer Similarity (old benchmark)`
28. `Query Complexity Score`
29. `Query Intent Type`
30. `Query Entity Count`
31. `Dynamic Threshold Used`
32. `Dynamic Token Ratio Limit`
33. `Preserved Coreferences`
34. `Retained Sentence Indices`
35. `Isolated Scoring Latency (ms)`
36. `Pairwise Scoring Latency (ms)`
37. `Coreference Analysis Latency (ms)`

### How key values are derived

- **Actual prompt-token counts:** per-request `usage.prompt_tokens` values returned by Groq, including system text and message formatting.
- **Actual prompt tokens saved/reduction:** difference and percentage calculated from the two Groq usage values. These are blank if either value is unavailable; no approximate value is substituted.
- **Legacy word counts/reduction:** retained only for migrated old rows or local compressor-only benchmarks. These are explicitly marked estimates and are not actual Groq token usage.
- **Compression latency:** elapsed time around the compressor call, measured with a monotonic performance counter.
- **LLM latency:** elapsed time around each HTTP request to Groq. It is request duration, not full UI wait duration.
- **Baseline total latency:** currently equals baseline LLM latency. Retrieval time is not measured, and no compressor is run on the baseline path.
- **Compressed total latency:** compressor elapsed time plus compressed-branch LLM latency.
- **Latency saved:** baseline total minus compressed total. This can be negative if the compression overhead is greater than any generation saving.
- **Prompt/completion tokens:** values Groq returns in its `usage` object; blank if absent. Prompt-token columns are labeled `Groq actual` to distinguish them from local word-count proxies.
- **Reference similarity:** lexical Jaccard similarity between the user-entered expected answer and generated answer:

```text
Jaccard = size(unique_words(reference) intersect unique_words(generated))
          / size(unique_words(reference) union unique_words(generated))
```

  It is only a lexical overlap indicator. It does not measure entailment, factual correctness, completeness, or hallucination.
- **Legacy answer similarity:** holds the old benchmark script's similarity values when the earlier seven-column workbook is migrated.

### Workbook migration behavior

The metric helper recognizes old schemas and maps historical estimates into columns marked `Legacy`. It does not relabel those approximations as actual Groq usage, nor fabricate historical answers or API metrics. When migrating an older comparison schema, if both authentic Groq prompt counts exist, it derives saved-count/reduction fields from those values. New comparison rows record actual Groq prompt usage and the adaptive/discourse/pairwise metadata. Migration preserves prior rows.

The workbook uses a formatted header row, frozen first row, filters, sensible column widths, and wrapped answer text. Excel/LibreOffice may lock a workbook while open; close it if a save fails and retry.

### Compressor-only benchmark script

`scripts/eval_met_gen.py` still runs a local compression-only benchmark without making any LLM requests. It appends its result to the shared workbook using the same schema. It can use built-in sample data or `--input` JSON.

### Enhanced benchmark methodology

`benchmark_rag_pipeline()` runs a fixed-rule reference compression (all three new features off, using the configured fixed threshold) and an enhanced compression on the same passages, reusing one scorer/model instance. It reports elapsed local compression for both, latency overhead, retained-context word estimates, and optional lexical overlap against the expected answer for each run and their delta. These values support controlled research iteration; lexical answer/context overlap is only a proxy, not measured LLM answer quality.

`benchmark_query_set()` accepts cases with `query`, `documents`, and optional `answer`, then returns per-case results and mean latency/overlap deltas grouped by the heuristic `factual`, `comparative`, or `multi_hop` intent. The CLI loads this JSON list with `python -m context_compressor.cli benchmark --cases query_cases.json`. Run repeated trials and controlled query sets before making claims; the helper does not randomize order, bootstrap confidence intervals, or call an LLM judge.

---

## 8. Frameworks, Libraries, and Techniques

### Python and packaging

- Python 3.10+ syntax and typing
- `pyproject.toml` with setuptools package discovery under `src`
- `pip`/virtual environment workflow

### API/backend

- FastAPI async routes and Pydantic request/response models
- Uvicorn development server
- `python-dotenv` for local environment configuration
- `httpx` asynchronous HTTP client for Groq API

### NLP/model runtime

- PyTorch and Hugging Face Transformers support batched cross-encoder inference
- Optional spaCy `en_core_web_sm` dependency parsing; regex-based offline discourse fallback
- Regex sentence segmentation and estimated word counting
- `Counter`-based lexical multiset matching for fallback scoring
- Rule-based complexity signals and adjacent-pair relevance-gain blending
- No live vector database, LangChain/LlamaIndex, or separate semantic-search store is connected

### Frontend

- React 19.2 with TanStack Start/Router and Vite
- Strict TypeScript, Tailwind CSS v4, Radix UI controls, Lucide React, and Recharts
- Reference-derived responsive single-page layout, light/dark mode with persisted preference, readable contrast tokens, and reduced-motion support
- Vite proxy calls `/compress`, `/compare`, `/upload_pdf`, `/analytics`, `/config`, and `/health` on FastAPI
- The API key remains on FastAPI; the UI receives only model/config status and API responses

### Evaluation/output

- `time.perf_counter()` for elapsed duration
- Regex word counts for rough context-size measurement
- Jaccard set similarity for optional reference-answer overlap
- `openpyxl` for workbook generation, formatting, migration, and row append
- Python `unittest`, FastAPI `TestClient`, and mocks for deterministic external API tests

### Error handling and validation techniques

- Pydantic bounds for threshold, top-k, and approximate word budget
- Scorer cardinality checks, parameter validation, and backward-compatible `score_single()` fallback
- Explicit 422 validation for blank query/passages in comparisons
- Typed client exceptions translated to HTTP status errors
- Explicit UI error text and metric-save status
- Mocked provider calls avoid spending API quota during automated tests

---

## 9. Configuration and Default Values

`RuntimeConfig` currently contains:

| Setting | Default | Meaning |
|---|---:|---|
| `model_name` | `cross-encoder/stsb-roberta-base` | HF model attempted by the relevance scorer. Its scalar similarity output is not a calibrated relevance or entailment probability. |
| `max_length` | 256 | Maximum tokenized query/candidate length per cross-encoder input. |
| `batch_size` | 16 | Maximum number of query/candidate pairs per model inference batch. |
| `threshold` | 0.35 | Minimum score used when request does not specify one. |
| `top_k` | 4 | Maximum selected sentences by default. |
| `max_context_tokens` | 512 | Default word-estimated compressed-context budget. |
| `device` | `cpu` | Model device. No automatic CUDA detection is implemented. |
| `data_dir` | package-relative `data` path | Intended data directory; current synthetic data helper does not download corpora. |

The React UI defaults to adaptive gating on, top-k `6`, and a local word-count budget of `512`; its manual threshold defaults to `0.45` and is sent only when adaptive gating is disabled. The API accepts optional `top_k`, `threshold`, and `max_tokens`; omitted values are resolved by the compressor/runtime configuration. These UI word-count limits are not LLM tokenizer token limits. The Groq API model defaults to `openai/gpt-oss-120b`, configurable through `GROQ_MODEL`.

---

## 10. Setup and Running from VS Code on Windows

### 10.1 Open the project

In VS Code, use **File -> Open Folder** and choose:

```text
D:\sic_aiml\capstone
```

Open **Terminal -> New Terminal**. Commands below use PowerShell and assume
the current directory is the project root. If the project is in another
location, use that folder instead.

### 10.2 Create/activate a virtual environment

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If `py` is unavailable:

```powershell
python -m venv .venv
```

If PowerShell blocks activation, either select `.venv` as the VS Code Python interpreter and open a fresh terminal, or permit scripts for only the current process:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

### 10.3 Install dependencies/package

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .
```

The NLP stack can be large. A Hugging Face model download may occur during startup if the configured model is available and cached weights are absent. The local fallback is used if model setup fails.

For spaCy-assisted subject-pronoun dependency parsing, install the optional
extra and English pipeline (the regex fallback remains available without it):

```powershell
python -m pip install -e ".[discourse]"
python -m spacy download en_core_web_sm
```

### 10.4 Configure Groq key

Copy the template and edit `.env` in VS Code:

```powershell
Copy-Item .env.example .env
```

Set:

```text
GROQ_API_KEY=your_actual_groq_api_key
GROQ_MODEL=openai/gpt-oss-120b
```

Keep the key private. `.env` is Git-ignored. Never enter the key into browser form fields or commit it. Restart Uvicorn after changing it. Each dashboard comparison makes two Groq calls and consumes quota.

### 10.5 Run Limas

From the project root, activate `.venv` and start FastAPI in a terminal:

```powershell
python -m uvicorn context_compressor.service.api:app --reload
```

In a second terminal, start the React dashboard:

```powershell
cd .\ui
npm ci
npm run dev
```

Open `http://127.0.0.1:3000/`. Use the upload dropzone to load PDF/TXT text or
enter passages directly; **Compress only** calls `/compress` without LLM
requests, while **Run paired comparison** calls `/compare` and records
successful paired metrics in the workbook. The dashboard fetches workbook
aggregates from `/analytics` and model/key status from `/config`. Vite proxies
the API paths to `http://127.0.0.1:8000` by default. To use another API host,
set `LIMAS_API_URL` in the environment before starting the frontend. Stop both
servers with `Ctrl+C`.

For a quick setup on Windows, the essential sequence from the repository root
is:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install -e .
Copy-Item .env.example .env
```

Edit `.env` to provide `GROQ_API_KEY` if you intend to use paired comparison.
Then start the API and UI in **two separate terminals** using the commands
above. The API can start without a Groq key; `/compress` works without Groq,
but `/compare` requires a valid key. The React UI requires Node.js/npm and its
dependencies are installed with `npm ci` from `ui/`. FastAPI `/` is a separate
static fallback page; use port `3000` for the React UI.

#### If a server is already running or startup fails

Start only one API server on port `8000` and one Vite server on port `3000`.
An error such as `[WinError 10013]` often means the requested socket cannot be
bound because the port is already occupied or reserved. Before retrying,
inspect the listener from any PowerShell window:

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
  Select-Object LocalAddress, LocalPort, OwningProcess
Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue |
  Select-Object LocalAddress, LocalPort, OwningProcess
```

Check a reported PID and its command before stopping anything:

```powershell
Get-CimInstance Win32_Process -Filter "ProcessId = <PID>" |
  Select-Object ProcessId, ParentProcessId, Name, CommandLine
```

If the command line identifies the expected Limas Uvicorn/Vite process, use
`Ctrl+C` in its original terminal. If that terminal is unavailable, stop only
the verified Limas process by its specific PID (for Uvicorn `--reload`, inspect
both the listener worker and its parent). Do not terminate an unidentified
process simply because it owns the port. Verify `/health` for the API or `/`
for the UI before deciding whether a restart is needed. A listener may remain
available even after a tool/terminal session that launched it has exited.

If the React UI fails with `'vite' is not recognized`, restore its installed
packages and restart Vite:

```powershell
Set-Location D:\sic_aiml\capstone\ui
npm ci
npm run dev
```

If port `8000` must be changed, start Uvicorn on a different port (for example,
`8010`) and set `$env:LIMAS_API_URL = "http://127.0.0.1:8010"` in the UI
terminal before starting Vite. The Vite proxy reads that environment variable
when it starts, so restart Vite after changing it.

### 10.6 Other project commands

Open another terminal, activate `.venv` in that terminal, and run from the root:

```powershell
python -m context_compressor.cli demo
python -m context_compressor.cli benchmark
python -m context_compressor.cli compress --no-enable-coref
python .\tests\test_pipeline.py
python .\scripts\eval_met_gen.py
python .\scripts\eval_met_gen.py --input .\benchmark.json
python -m context_compressor.cli benchmark --cases .\query_cases.json
```

CLI commands support `--enable-coref`/`--no-enable-coref`,
`--enable-multihop`/`--no-enable-multihop`, and
`--adaptive-gating`/`--no-adaptive-gating` (features are enabled by default).
A query-case JSON file is a list of objects with `query`, non-empty `documents`,
and optional `answer` fields. The benchmark groups cases by inferred intent and
reports fixed-rule/enhanced latency and lexical similarity-proxy changes.

`benchmark.json` format:

```json
{
  "query": "What causes climate change?",
  "documents": ["Greenhouse gases trap heat.", "An unrelated passage."],
  "answer": "Greenhouse gases contribute to warming."
}
```

---

## 11. Automated Testing

Run the Python backend regression suite from the repository root with the
project virtual environment active:

```powershell
python .\tests\test_pipeline.py
```

This is a Python `unittest` runner with a custom plain-text summary. It writes
`reports/pipeline_test_results.txt` and returns a non-zero process code on
failure. The equivalent pytest invocation in the project environment is:

```powershell
python -m pytest .\tests\test_pipeline.py -q
```

Coverage includes sentence splitting/fallback relevance; pairwise score gain; pronoun/connective link closure and passage boundaries; atomic coreference/pair retention; adaptive query-intent cutoff and ratio bounds; the enriched compression API and disabled-feature flags; fixed-vs-enhanced benchmark output and intent aggregation; paired Groq flow under mocks; provider errors; workbook schema migration; and null-safe missing Groq usage. Ordinary tests do not use real secrets, contact Groq, or consume API quota.

The latest validation on 2026-10-09 completed **24 backend tests with 0
failures and 0 skips** in the project virtual environment. The React frontend
also passed `npm run build` and `npx tsc --noEmit`. Browser checks covered both
themes, persisted theme selection, responsive mobile width, TXT/PDF upload,
compression results, analytics rendering, and a mocked paired response; no
live Groq request was made during those checks. The production build emits
non-fatal chunk-size and TanStack dependency warnings. Automated pass status
does not validate heuristic quality or replace controlled benchmark
evaluation.

### 11.1 Frontend checks

Run from `ui/` with Node.js/npm installed:

```powershell
npm ci
npx tsc --noEmit
npm run build
```

`npm ci` restores the exact dependencies recorded in `package-lock.json`. It is
needed for a first install or if `npm run dev` fails with `'vite' is not
recognized`. Run it from `ui/`, not the repository root. The build/type checks
do not require a Groq key.

### 11.2 Manual local application checks

Start both servers as described in section 10, then check:

1. Open `http://127.0.0.1:3000/` (the React UI; port `8000` is the API/static
   fallback). Confirm the API status pill is populated.
2. Open `http://127.0.0.1:8000/health` and expect a JSON `status` of `ok`.
   Open `http://127.0.0.1:3000/analytics` to verify the Vite proxy reaches the
   workbook-backed API.
3. Switch light/dark theme. Confirm the primary button remains readable, cards
   and text change theme, and reloading preserves the selected theme.
4. At a narrow viewport (for example 390 CSS pixels), check that the page has
   no horizontal scrolling.
5. In the Playground, use **Compress only**. Confirm a compressed context and
   the retained/pruned sentence audit display without making Groq requests.
6. Upload a small text file and a text-based PDF. Confirm extracted passages
   populate the retrieved-passages field. Scanned PDFs do not undergo OCR.
7. For a live paired comparison, configure a valid Groq key, run **Run paired
   comparison**, and confirm answers, prompt-token usage, and an audit appear.
   This makes two external Groq requests and may consume account quota. Do not
   use live comparisons for routine automated checks; use the mocked test suite.
8. Confirm the analytics summary reflects saved workbook history. A successful
   comparison appends a row to `reports/eval_met.xlsx`; close Excel/LibreOffice
   if it has the workbook open and saving fails.

The API-only checks in the automated suite cover health, compression, upload,
analytics, paired comparison behavior under mocks, Groq errors, and workbook
schema migrations. UI/API manual checks complement but do not replace them.

---

## 12. Known Limitations and Risks

### Relevance model/output interpretation

The default STS-B cross-encoder is a sentence-similarity model with a scalar regression-style output. A sigmoid now gives scalar outputs a monotonic ranking transform; it does not calibrate them as relevance or entailment probabilities. The lexical fallback is a hand-built heuristic, not entailment. Validate or fine-tune a task-compatible model before relying on relevance ranking.

### Compression/pruning

- Regex sentence splitting has boundary errors.
- Pairwise scoring evaluates only adjacent sentences in the same supplied passage; it does not find arbitrary non-local multi-hop paths.
- Pairwise cross-encoder score gain is a relevance heuristic, not an entailment/NLI proof. It adds inference overhead.
- The adaptive gate uses hand-authored lexical/structural signals and a capitalized-span entity proxy; its scores are not calibrated or language-independent.
- spaCy subject-pronoun tagging and the regex fallback do not perform full entity coreference resolution. Fallback rules chiefly match leading references/connectives and bind only the immediately preceding sentence.
- Sentence-level score audit records heuristic scores and decisions, but these explanations are not calibrated probability or causal explanations.
- Discourse/pair dependencies are atomic and can exceed top-k or the approximate word budget; preservation is prioritized over those pruning caps.
- A single selected atomic group can exceed the requested max word budget because the budget fallback retains the highest-ranked complete group.
- The compressor's `max_tokens` pruning budget and its internal reduction diagnostics use word-like counts, not tokenizer token IDs. Actual comparison reduction is separately computed from Groq usage.

### Comparison/evaluation

- The two Groq calls are concurrent, but request order is not randomized; latency comparisons remain sensitive to external conditions.
- Baseline total latency excludes retrieval and is currently just baseline Groq-call latency. Compressed total is compression plus compressed Groq-call latency. Network/client bookkeeping around the full endpoint is not included in these workbook totals.
- Groq prompt-token reduction includes the full prompts (fixed system instructions and formatting) rather than only passage text; because the fixed content is shared, comparing complete provider counts measures the actual API prompt reduction.
- Groq completion output may vary; temperature zero does not guarantee identical responses from a hosted service.
- Jaccard similarity can penalize valid paraphrases and reward keyword overlap. It is not an accuracy metric.
- Local enhanced-vs-fixed benchmarks measure compression latency and lexical reference/context overlap only; they do not call Groq or directly measure answer quality. The current helper does not randomize order or calculate confidence intervals.
- No answer judge, entailment verification, source citation check, or hallucination-rate evaluation is implemented.
- If the first LLM succeeds but the second fails, the API reports a failed pair; it does not persist an incomplete comparison row.
- API key and Groq account are user-provided. Real external requests have quotas/cost policies that the application does not control.

### RAG scope

- Retrieved passages are typed by the user; no vector store/indexing/retriever exists.
- The endpoint assembles its own simple grounded chat prompts; it is not integrated into an external LLM orchestration framework.
- No authentication, multi-user case storage, rate limiting, or deployment hardening is configured; run it locally for development.

---

## 13. Recommended Next Improvements

Prioritize:

1. Fine-tune/calibrate a task-appropriate relevance cross-encoder and validate pair-score semantics on labelled data.
2. Replace hand-authored complexity and co-reference heuristics with evaluated multilingual/coreference-aware models or curated rules; measure false antecedent retention.
3. Add non-local graph edges and explicit evidence-chain supervision for multi-hop QA, with human-reviewed ablations.
4. Use a tokenizer aligned with the deployed LLM to enforce actual prompt budgets before generation; retain Groq usage as the post-request authority.
5. Run repeated, randomized paired latency trials and report distributions/confidence intervals, including model initialization and retrieval costs where applicable.
6. Add real labelled MS MARCO/NLI/QA data splits, reproducible fine-tuning, and a held-out benchmark.
7. Integrate Qdrant or Chroma retrieval with source IDs/provenance and measure retrieval quality/latency.
8. Add semantic answer judging and a human rubric. Do not infer accuracy or hallucination reduction from token savings or Jaccard overlap.
9. Add API authentication/rate limits and deployment configuration before exposing Groq-backed endpoints publicly.

---

## 14. Glossary

- **RAG:** Retrieval-Augmented Generation; retrieve relevant content and supply it to a generative model as grounding context.
- **Passage/document:** A retrieved text chunk supplied to the compressor.
- **Candidate sentence:** A sentence extracted from a passage and independently scored against the query.
- **Cross-encoder:** A model that encodes a query and candidate together, allowing interaction between their tokens. Unlike a bi-encoder, it generally scores each pair rather than reusing independent embeddings.
- **Threshold:** Minimum score for a sentence to pass the normal selection filter.
- **Top-k:** Maximum candidate sentence count selected by the current compressor.
- **Prompt tokens:** Groq-reported tokens in the complete API prompt, including system/user formatting when provided by the response.
- **Completion tokens:** Groq-reported generated response token count.
- **Reference similarity:** Lexical set overlap between a supplied expected answer and generated answer; not a correctness guarantee.
- **Baseline:** Groq answer generated from all user-supplied passages, without compression.
- **Compressed run:** Groq answer generated from the compressor's selected text.

---

## 15. Current Status Summary

The repository provides a local interactive comparison application. A user
supplies a query and passages in the React/TanStack UI; the Python compressor
selects sentence spans and returns a complete candidate-sentence audit; the API
requests baseline and compressed Groq answers concurrently; and the server
records successful paired comparisons in Excel. FastAPI also serves a legacy
static fallback at `/`.

The codebase uses FastAPI/Pydantic, `httpx`, `python-dotenv`, optional
PyTorch/Transformers model loading, optional spaCy assistance, React 19/TanStack
Start, strict TypeScript, Tailwind CSS v4, Radix UI, Recharts, regex/lexical
heuristics, `openpyxl`, and `unittest`. The API key must be set locally in
`.env`; automated Groq tests are mocked.

The 2026-10-09 workbook snapshot contains 9 paired runs, averaging 8.4% actual
prompt-token reduction, -265 ms net latency saved (that is, 265 ms slower on
average after compression cost), 36.4% compressed-answer Jaccard against
available references, and 2 logged discourse edges. These are descriptive
statistics from a tiny, uncontrolled sample, not reliable system-level
performance estimates. The latest validation ran 24 backend tests, passed the
frontend production build and TypeScript check, and checked browser interactions
without a live Groq call. The research heuristics and score blends are not a
validated entailment/coreference system or proof of improved QA accuracy.

## 16. Retrieval and Long-PDF Enhancement Update (2026-10-12)

This subsection records the implementation added after the project snapshot above. The original sections are retained as written; this is an appended update.

### Implemented retrieval path

The service now supports an optional document-index workflow alongside the existing raw-passage workflow:

```text
PDF/TXT upload -> page-aware extraction -> overlapping chunks -> MiniLM vectors
               -> top-k retrieval -> cross-encoder reranking -> compression
```

- `POST /upload_pdf` continues to accept PDF and UTF-8 text uploads and returns a `doc_id`, extracted pages, and page provenance. Scanned PDFs still need OCR before upload.
- `POST /index` chunks the uploaded document, stores a process-local index, and reports the embedding backend/model. `/retrieve` performs dense candidate retrieval and optional cross-encoder reranking. `/compress` and `/compare` accept `doc_id` as well as the legacy `documents` passage array.
- PDF page ranges and retrieval/rerank ranks and scores are carried into retrieved chunks and the sentence audit. The index and uploaded document cache are process-local and reset when the API process restarts.
- Existing passage-array routes remain supported. No CSS or Tailwind styling was changed for the retrieval integration.

### Model lifecycle and inference verification

- FastAPI lifespan preloads `sentence-transformers/all-MiniLM-L6-v2` and the MS MARCO cross-encoder once at server startup. Reranker instances are cached by model name. Cross-encoder scoring uses batches of 16 sentence pairs.
- Real model inference was verified from the local Hugging Face cache: MiniLM returned normalized 384-dimensional embeddings and `/index` reported the `sentence-transformers` backend. The offline hashing implementation remains a development fallback if model loading is unavailable; fallback results are not dense semantic retrieval.
- A hand-curated 10-query/20-candidate smoke comparison on CPU produced these results (latency for ten two-candidate queries):

| Cross-encoder | Pairwise accuracy | Mean positive-minus-negative score | Total scoring latency |
|---|---:|---:|---:|
| `cross-encoder/ms-marco-MiniLM-L-6-v2` | 1.00 (10/10) | 0.6647 | 66.14 ms |
| `cross-encoder/stsb-roberta-base` | 0.90 (9/10) | 0.2731 | 287.41 ms |

These measurements are a small smoke comparison, not a representative or statistically controlled reranker benchmark. A labeled retrieval dataset is needed for defensible accuracy claims.

### Startup memory and index profiling

`POST /index` samples process RSS with psutil and returns/logs start, peak, and end memory values. On a synthetic 50-page indexing run using the real MiniLM model, the process used 1,140.84 MB at start, peaked at 1,396.55 MB, and ended at 1,278.40 MB. This is below the 10 GB target for that synthetic run; it is not a profile of a representative production PDF corpus.

### Evaluation status and recorded metrics

`scripts/evaluate_pipeline.py` runs four configurations: direct legacy Limas compression, retrieval only, retrieval plus Limas compression, and retrieval plus a top-four extractive baseline. It writes Recall@k, a lexical quality proxy, prompt-token reduction, and latency fields to the `retrieval_benchmark` worksheet in `reports/eval_met.xlsx`.

The repository does not contain representative 4–10 page, 20–30 page, and 50+ page benchmark PDFs with labeled queries and reference answers. Therefore, no multi-length benchmark rows have been generated, and the full retrieval evaluation is still pending. The script expects a JSON case manifest with each PDF path, query, and optional reference answer. The earlier paired Groq workbook data remains a separate evaluation: its latest recorded 13 runs averaged 11.1% actual prompt-token reduction and -212.9 ms net latency saved. Those values describe that small paired sample, not the retrieval benchmark or a general performance guarantee.

### Verification update

- `pytest tests/`: 36 passed, 0 failed, and 0 skipped after the model dependencies were available.
- `git diff --check` passed.
- Frontend TypeScript check and production build passed earlier in this implementation sequence; existing bundle-size and unused-import warnings remain.
- The project is a working local prototype. It has not completed the corpus-based multi-length retrieval evaluation and should not be presented as having validated long-document QA quality or factual equivalence.

## 17. Quality-First Retention Update (2026-10-13)

This update records the current soft-pruning behavior implemented after the
retrieval and long-PDF work above. Earlier sections are preserved as historical
implementation notes; use this section for the current gating and retention
defaults.

### Adaptive gating defaults

`QueryComplexityGater` now derives its settings from the normalized query
complexity score `C`, clamped to `[0, 1]`:

```text
threshold τ(Q) = clamp(0.15 - 0.10 × C, 0.05, 0.15)
context ratio B(Q) = clamp(0.60 + 0.35 × C, 0.60, 0.95)
```

Thus simpler queries start with a 0.15 relevance cutoff and 60% context ratio;
the cutoff falls to 0.05 and the context ratio grows toward 95% as complexity
increases. The values are heuristic gating parameters, not calibrated model
probabilities. An explicit `threshold` in a `/compress` or `/compare` request
overrides the adaptive cutoff. With adaptive gating disabled and no explicit
threshold, `RuntimeConfig.threshold` defaults to 0.10.

### Minimum evidence and neighboring context

- If fewer candidates pass the cutoff than the retention floor, fallback
  selection keeps the highest-scoring `max(8, floor(0.70 × candidate_count))`
  sentences, capped at the number of available candidates. The floor can exceed
  the configured top-k selection count.
- The compressor adds each selected sentence's immediate predecessor and
  successor before final word-budget packing. Neighbor expansion stays within
  the same input passage, so the last sentence of one retrieved chunk is not
  joined to the first sentence of another.
- Fallback evidence and added neighbors are prioritized/protected during local
  word-budget packing. As a result, selected evidence can exceed the nominal
  `max_tokens` word-proxy cap when preserving it is necessary; the downstream
  Groq prompt-fitting step remains responsible for fitting the provider prompt.
- `RuntimeConfig.max_context_tokens` now defaults to 4,000. Request-level
  `max_tokens` overrides remain supported and cap the local adaptive word
  budget; the internal quantity is a word-count proxy, not exact tokenizer
  tokens.

Example soft-pruning request fields are `"adaptive_gating": true`,
`"threshold": 0.05`, and `"max_tokens": 4000`. These are accepted by both
`/compress` and `/compare`; a manually supplied threshold takes precedence over
the adaptive threshold.

### Verification status

Python compilation passed, `git diff --check` passed, and four focused backend
tests covering adaptive gating, minimum-retention fallback, dependency audit,
and compression metadata passed after this update. A full-suite pass has not
been established for this revision. The existing retrieval evaluation still
needs representative short, medium, and 50+ page PDFs with labeled query cases
before it can support long-document quality claims.

## 18. Retention Defaults Restored (2026-10-13)

This section supersedes the threshold, context-ratio, and fallback-floor values
recorded in Section 17. Neighbor expansion remains enabled, and the 4,000-word
proxy context budget remains the default.

- Adaptive threshold: `τ(Q) = clamp(0.10 + 0.10 × C, 0.10, 0.20)`. More complex
  queries receive a slightly higher score cutoff, up to 0.20.
- Adaptive context ratio: `clamp(0.80 + 0.05 × C, 0.75, 0.85)`. The default
  ratio is 0.80 and rises toward 0.85 with complexity.
- Minimum-retention fallback: when fewer than
  `min(candidate_count, max(5, floor(0.60 × candidate_count)))` sentences pass
  the threshold, the compressor keeps the highest-scoring candidates to reach
  that floor.
- Adjacent predecessor/successor sentences are still added within each input
  passage and protected during local word-budget packing.
- Both `/compress` and `/compare` continue to accept manual `threshold` and
  `max_tokens` overrides. `threshold: 0.10` and `max_tokens: 4000` are the
  documented soft-pruning request values.

The current backend revision was compiled and the focused gating and compressor
tests passed after these defaults were restored. The full test suite has not
been rerun for this restoration.

## 19. Current Implementation Reference and Handoff (2026-10-13)

This section is an additive, code-oriented reference for the implementation
currently present in the repository. It supplements the earlier overview and
records the current runtime behavior after the retrieval, technical-term
matching, compression, and UI work. Where earlier sections describe older
values or architecture, use the explicit current values below when operating
the present code. No earlier section has been rewritten.

### 19.1 Runtime components and responsibility boundaries

The current implementation has two supported input paths:

```text
Document path: upload -> page extraction -> chunk -> embed/index
               -> dense + lexical candidate retrieval -> cross-encoder rerank
               -> compression -> optional Groq generation

Legacy path:   caller-provided passage strings -> compression
               -> optional Groq baseline/compressed comparison
```

- `ingestion/pdf_extractor.py` uses `pypdf.PdfReader` on in-memory bytes. It
  creates a UUID `doc_id` unless one is supplied, emits one `PageMetadata`
  record per PDF page, and keeps page number, extracted text, extraction status,
  and optional section title. Empty, corrupt, and password-protected PDFs
  return actionable errors. It detects pages with no extractable text and
  reports that OCR is required; no OCR engine is implemented.
- `ingestion/chunker.py` combines page text into token-bounded `TextChunk`
  records. Defaults are 500 tokenizer units with 80 units of overlap; the API
  permits target sizes from 100–1,000 and overlap from 0–200. It prefers
  paragraph and sentence boundaries, then splits oversized units into token
  windows. Each chunk carries a UUID, `doc_id`, page start/end, optional section
  title, and token count. The preferred tokenizer is the local Hugging Face
  tokenizer for `sentence-transformers/all-MiniLM-L6-v2`; when unavailable, a
  regex token codec is used. This is a chunk-size tokenizer, separate from the
  Groq prompt token count.
- `retrieval/vector_store.py` keeps `DocumentIndex` objects in process memory,
  including chunks, normalized vectors, token-term frequencies, document
  frequencies, average document length, and backend identity. A reentrant lock
  protects index creation. Indexes and uploaded pages are not persisted and
  disappear on process restart; multiple API workers do not share this state.
- `retrieval/lexical.py` normalizes common LaTeX subscripts such as
  `$d_{model}$` to `d_model`, tokenizes identifiers while preserving
  underscores, detects numeric/formula/parameter lookups, and counts exact
  requested-term matches. It maps natural-language aliases such as “model
  dimensions,” “key dimensions,” “value dimensions,” and “number of heads” to
  common identifiers (`d_model`, `d_k`, `d_v`, `h`).
- `retrieval/reranker.py` applies a cross-encoder to the first-stage candidates
  and returns retrieval and rerank score/rank provenance. Supported models are
  `cross-encoder/ms-marco-MiniLM-L-6-v2` and
  `cross-encoder/stsb-roberta-base`; unsupported names are rejected. The API
  defaults to the MS MARCO model and `/retrieve` permits choosing the listed
  STS-B alternative.
- `compression/compressor.py`, `gating.py`, `scorer.py`, `coreference.py`, and
  `models/cross_encoder.py` implement sentence selection, described below.
- `service/api.py` owns request validation, caches, lifecycle hooks, provenance
  mapping, Groq orchestration, workbook writes, and optional serving of the
  compiled UI. `service/groq_client.py` owns provider request construction and
  usage/latency parsing.

### 19.2 Embedding model, retrieval math, and technical lookup protection

The dense encoder is the Sentence Transformers bi-encoder
`sentence-transformers/all-MiniLM-L6-v2`. `VectorStore._encode()` encodes each
chunk at index time and each query at retrieval time with
`normalize_embeddings=True`; the model's normal output is 384 dimensions.
Cosine similarity is the dot product of the normalized vectors. The model is
loaded lazily by the vector store and, in the API process, preloaded from the
FastAPI lifespan hook. This is a bi-encoder: document vectors can be computed
once and reused independently of a query.

Dense search is combined with a local BM25-style lexical scorer. Terms are
normalized using the lexical module; per-chunk term frequencies and document
frequencies are computed when indexing. The implementation uses `k1 = 1.5`,
`b = 0.75`, a logarithmic inverse-document-frequency term, and a modest query
term-frequency multiplier. Scores are normalized relative to the best lexical
match for that query. Dense cosine is mapped from `[-1, 1]` into `[0, 1]` and
clamped. The combined first-stage score is:

```text
Ordinary query:       0.60 * dense + 0.40 * normalized BM25
Technical exact query: 0.25 * dense + 0.50 * normalized BM25
                      + 0.25 * normalized exact-identifier matches
```

The ranking is deterministic for ties by original chunk order. The exact-term
signal uses identifier/formula matches; exact lookup detection is also used in
the reranker and compressor. In reranking, an exact-match bonus of up to 0.20
is added relative to the number of requested technical terms. During
compression, sentences matching at least one requested technical term are
protected as mandatory selected evidence before context packing. The behavior
helps exact parameter queries but does not prove the value is correct or that
all query aliases are recognized.

When the Sentence Transformers import, cache, or model load fails, the index
uses a deterministic 2,048-dimensional signed feature-hashing vector based on
lowercased regex tokens and token counts. It L2-normalizes the result and
reports backend `offline-hash-fallback`; this is not semantic embedding and
should not be represented as MiniLM inference. `/index` reports the actual
backend and model field (the embedding model is null on fallback).

### 19.3 Cross-encoder inference and score interpretation

The reranker and compressor scorer are cross-encoders: they receive paired
query/text inputs together, allowing token-level interaction. The compressor's
default model is `cross-encoder/stsb-roberta-base`; the retrieval rerank default
is `cross-encoder/ms-marco-MiniLM-L-6-v2`. Both use Hugging Face
`AutoTokenizer` and `AutoModelForSequenceClassification` through
`CrossEncoderRelevanceScorer` in `models/cross_encoder.py`.

The inference path tokenizes paired inputs with padding, truncation, PyTorch
tensors, and a default maximum sequence length of 256. It runs in batches of 16
under `torch.no_grad()`, moves model and tensors to the configured device (CPU
by default), and sets loaded models to evaluation mode. A one-logit output is
transformed with sigmoid; a multi-logit output uses the second-class softmax
probability. These transformations produce bounded, rankable values, but do
not calibrate the STS-B regression output or make it an entailment probability.

If imports or loading fail, the scorer falls back to deterministic expanded
lexical overlap. A small hard-coded expansion dictionary covers terms such as
climate/warming, greenhouse/emissions, cause/result, and effect/impact. It
counts query/candidate token overlap as a fraction of expanded query terms,
capped at 1. `/config` reports whether Transformers are importable and whether
the embedding, retrieval reranker, and compression scorer are loaded in their
real-model paths. Availability is not a model quality or provider-connectivity
test.

The small smoke comparison recorded earlier in Section 16 remains a curated
10-query / 20-candidate CPU comparison, not a broad retrieval benchmark. Its
latency and pairwise accuracy should not be generalized to arbitrary PDFs or
queries. `CrossEncoderReranker` currently constructs its scorer without an
explicit device override, so its normal default is CPU. The compressor scorer
uses `RuntimeConfig`, whose current defaults are STS-B, CPU, batch size 16,
sequence length 256, threshold 0.10, top-k 4, and a 4,000 local word-proxy
context cap.

### 19.4 Compression selection algorithm, in execution order

`ContextCompressor.compress()` currently performs these operations:

1. Convert a single input string into a one-element passage list, then split
   each passage with the regex sentence splitter. Candidate indices are
   zero-based and span the supplied passage sequence; passage identity is
   retained so pair scoring and neighbors do not cross passage boundaries.
2. Analyze query complexity with `QueryComplexityGater`. Features include
   comparative phrases, reasoning starters, logical/sequential connectives,
   capitalized-span entity proxies, long queries (14 or more words), and
   technical exact lookups. This is a hand-authored heuristic, not a trained
   intent classifier.
3. Batch-score each query/sentence pair. When multi-hop scoring is enabled,
   also score contiguous same-passage pairs if at least one sentence reaches
   the 0.10 pair candidate floor. Pairwise gain for the current sentence is
   `max(0, joint_score - predecessor_isolated_score)`. Its final weight is
   `0.70 * current_isolated_score + 0.30 * pairwise_gain` for eligible
   within-passage successors; otherwise the isolated score is retained. A
   dependency edge is recorded when the joint score exceeds both individual
   scores by more than 0.05. This is a local relevance heuristic, not NLI.
4. Set the active threshold to explicit request `threshold`, otherwise the
   adaptive threshold, otherwise `RuntimeConfig.threshold` when adaptive gating
   is disabled. Current adaptive formulas are `tau = clamp(0.10 + 0.10*C,
   0.10, 0.20)` and `ratio = clamp(0.80 + 0.05*C, 0.75, 0.85)`, where `C` is
   query complexity clamped to `[0,1]`. An explicit threshold only overrides
   the cutoff, not the ratio. With gating disabled and no override, cutoff is
   0.10 and no adaptive ratio is reported.
5. Estimate original text size with a lowercase regex word count. If adaptive
   gating is on, the word budget is at most the rounded input-size times the
   query's context ratio, further capped by `max_tokens` or the default 4,000.
   Despite the API field name, this local cap is not exact tokenizer tokens.
6. Filter by relevance cutoff. If fewer than
   `min(candidate_count, max(5, floor(0.60*candidate_count))` candidates pass,
   select the highest scores to that fallback floor. Then select up to the
   larger of request/default top-k (default 4) and the active fallback floor.
   Technical exact-match sentences are included as protected candidates. Ties
   use original sentence order. This safeguard is current behavior and
   supersedes the 70%/top-8 proposal described in older conversation-derived
   notes; that proposal is not the current implementation.
7. Add immediate predecessor and successor sentences around initially selected
   evidence, constrained to the same passage. Find local discourse/coreference
   edges when enabled and include required antecedents. Pairwise dependency
   edges join this dependency set. Selected sentences are returned in source
   order.
8. Pack whole connected dependency groups into the word budget. Exact-match
   selections, fallback selections, and adjacent context are protected. A
   protected group can exceed the nominal budget; if nothing has yet fit, the
   highest-ranked complete group is retained to avoid dropping all evidence.
9. Return compressed text, estimated counts/reduction, score parts and timings,
   query-gate fields, original indices, dependency counts, and a complete audit
   with reason strings for each retained/discarded candidate.

When `enable_coref` is true, `DiscoursePreserver` optionally loads
spaCy `en_core_web_sm` and batches eligible sentences through its parser to
identify subject pronouns. This package/model is optional; if missing, regex
fallbacks recognize selected leading references (`it`, `they`, `this`, etc.)
and discourse connectives (`however`, `therefore`, `as a result`, etc.). Links
are only made to the immediately preceding sentence in the same input
passage. spaCy's standard pipeline is not a general coreference resolver. If
`enable_multihop` is false, pairwise scores/edges are skipped; if
`enable_coref` is false, discourse-link analysis is skipped, but the normal
sentence scorer still runs.

### 19.5 API behavior and state details

Current routes are `/health`, `/config`, `/upload_pdf`, `/index`, `/retrieve`,
`/analytics`, `/compress`, and `/compare`, plus `GET /` for the local fallback
or optional built UI. The raw passage workflow is retained: callers may provide
`documents[]` to `/compress` and `/compare`; doc-index workflows use `doc_id`
and query/top-k controls. `/compare` requires one usable context source and
supports optional expected answer, test-case label, compression controls, and
a Groq token-per-minute preflight allowance. Upload accepts PDF or UTF-8 TXT,
with a 25 MiB upload limit. TXT files are split by blank lines; PDF extraction
preserves page records. Scanned PDFs need OCR externally.

`/index` defaults to 500 tokenizer units per chunk and 80 units overlap. It
returns page/chunk counts, active embedding backend/model, retrieval method,
and a `psutil` RSS profile if psutil is importable. The sampler polls process
RSS every 50 ms during indexing and logs/returns start, sampled peak, and end
RSS in MiB. If psutil is unavailable, indexing continues with a warning and a
null memory profile. The profile is process RSS (which includes model/runtime
memory), not a GPU allocator or per-document-only memory measurement.

`/retrieve` first-stage `top_k` defaults to 30 (maximum 200); reranked count
defaults to 8 (maximum 50). Results include chunk ID, document ID, text, page
range, section title, chunk token count, and retrieval/rerank scores and ranks.
`/compress`/`/compare` doc workflows similarly return selected retrieval
chunks, then map their page/rank/score provenance onto sentence audit records.
If `doc_id` has not been uploaded/indexed in this same process, API responses
are explicit errors (upload is 404 on a lost process cache; retrieve reports
that indexing is required). The process-local cache is single-process
development storage, not durable multi-user document storage.

The FastAPI lifespan function loads MiniLM and the MS MARCO reranker once at
process startup. The compression scorer is created with the module-level
`ContextCompressor`; rerankers are cached by model name. No model should be
re-instantiated per sentence or per request in this API process. If model
loading fails, the application may continue with the documented fallbacks;
use `/config` to inspect model-path status. `GET /health` is only a basic
process health signal and does not ping Groq or validate all loaded models.

For `/compare`, the service creates two grounded prompts with the same query,
configured Groq model, and system grounding instructions: all provided or
retrieved text for baseline, and selected compressed text for the other path.
It fits contexts against its preflight prompt budget and sends both Groq calls
concurrently via `asyncio.gather`. Groq's returned prompt/completion usage is
the source for actual-token metrics; missing provider usage remains null rather
than being replaced with word estimates. Optional `expected_answer` comparison
uses Jaccard lexical similarity only. Successful paired metrics are appended
to `reports/eval_met.xlsx`; workbook write errors are surfaced in response
metadata. `/compress` makes no Groq request. Comparisons use two provider calls
and can consume quota. Failure of either branch fails the paired result rather
than recording a misleading partial pair.

### 19.6 UI behavior and API connectivity

The main UI is the React 19/TanStack Start application under `ui/`. Vite
serves it on `127.0.0.1:3000` and proxies API paths to FastAPI on
`127.0.0.1:8000`. Proxied paths include comparison/compression, PDF upload,
index/retrieve, analytics, configuration, and health. The playground supports
raw passages and uploaded-document retrieval, compression-only execution,
paired Groq comparison, and retained/discarded sentence audit. The analytics
view reads saved workbook rows; it does not imply an independent evaluation
corpus.

The dashboard requests `/config` for live service/model/key-configuration
indicators. A green Groq-key indicator means a key is configured, not that the
Groq provider was pinged. The MiniLM and cross-encoder indicators report local
load/fallback state, not retrieval accuracy. Scroll-reveal uses
`IntersectionObserver` and honors reduced-motion CSS. The particle canvas is
fixed to the viewport, rendered behind interactive content, uses the active
theme's `--particle` token, drifts continuously, reacts to nearby mouse motion,
and removes listeners/animation frames on unmount. Light/dark variables retain
separate contrast values; the metrics area continues to show workbook data.

FastAPI serves a self-contained `service/static/index.html` fallback at `/`
when a compiled React index is unavailable. If `ui/dist/client/index.html` (or
fallback `ui/dist/index.html`) exists, root serves that built index and a
conditional catch-all `StaticFiles` mount serves its assets after API route
definitions. In local development, Vite remains the primary UI server and
proxies API requests; the backend's optional static mount does not replace
Vite. The Dockerfile and `.dockerignore` previously used for container hosting
have since been deleted from the working tree at the user's request. README
contains no Hugging Face YAML deployment header. Do not assume a container
deployment configuration is currently present.

### 19.7 Evaluation, test coverage, and evidence limits

`scripts/evaluate_pipeline.py` accepts a JSON case manifest containing PDF
path, query, optional reference answer, and a declared document length tier. It
requires corpus coverage across short (4–10 pages), medium (20–30 pages), and
long (50+ pages) sets before writing rows. For each case it records four
configurations: direct legacy Limas compression; retrieval only; retrieval plus
Limas compression; and retrieval plus a transparent top-four extractive
baseline. The retrieval benchmark worksheet stores tier/case/configuration,
page count, Recall@k, lexical Jaccard quality proxy when an answer is supplied,
estimated prompt-token reduction, context size, and overall/retrieval/
compression latency fields. Its token reduction and quality fields are local
estimates/proxies, not Groq answer-evaluation results. The script does not
itself generate LLM answers.

`tests/test_pipeline.py` exercises sentence splitting/scoring/compression,
gating, discourse/pair dependencies, API health/config/compression/upload,
mocked paired generation and errors, analytics, and workbook migrations.
`tests/test_retrieval_pipeline.py` exercises PDF extraction, chunking/page
provenance, synthetic 50-page ingestion, vector-store caching/ranking,
preflight context budgets, and upload-index-retrieve-doc_id integration. Mocked
or fallback tests verify control flow but do not prove that hosted model
weights loaded. Real model verification requires startup logs or `/config`
showing the model paths and an actual embedding/reranking request. The full
short/medium/long corpus evaluation remains pending unless corresponding
manifest cases and workbook rows are supplied and run. Do not claim a completed
multi-length quality benchmark or less than 10 GB production RAM use from a
synthetic profile alone.

### 19.8 Current configuration and local run checklist

Backend Python dependencies are in `requirements.txt`; package metadata and
the optional `discourse` spaCy extra are in `pyproject.toml`. Runtime defaults
are in `config.py`. `.env.example` documents `GROQ_API_KEY` and model selection;
the real key belongs in an untracked local `.env`. The React package scripts
are `npm run dev`, `npm run build`, and `npm run start` from `ui/`.

For local use, activate the Python environment, install backend requirements,
and run `python -m uvicorn src.context_compressor.service.api:app --reload
--host 127.0.0.1 --port 8000` from the repository root. In a second terminal,
run `npm install` once and `npm run dev` from `ui/`; open
`http://127.0.0.1:3000`. Check `http://127.0.0.1:8000/health` and
`/config`. Model weights may need downloading on first startup; if offline,
check whether the API reports fallbacks. Set a valid local Groq key only for
live `/compare` requests. Automated API comparison tests use mocks and avoid
provider quota. Keep `reports/eval_met.xlsx` closed in spreadsheet applications
while the service appends metrics.

The latest Git state may show `Dockerfile` and `.dockerignore` as deleted but
unstaged, because those tracked deployment artifacts were deliberately removed
for manual review/commit. No Git staging or commit is implied by this guide
update.
