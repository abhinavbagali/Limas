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
