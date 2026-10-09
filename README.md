# Limas

### Subcortical Context Compression Middleware for RAG Pipelines

Limas compresses retrieved documents before they are sent to a language model. It scores sentences and adjacent sentence pairs, adaptively gates retention by query complexity, and preserves selected antecedent/discourse dependencies. The pre-generation budget uses an explicitly estimated word count; actual LLM token usage is only known after a provider request.

## What this project includes

- Sentence-aware retrieval-context pruning
- Discourse antecedent preservation with optional spaCy subject-pronoun analysis
- Pairwise sentence interdependence scoring with batched cross-encoder inference
- Query-complexity adaptive threshold and context-ratio gating
- Cross-encoder relevance scoring with a robust fallback mode
- FastAPI service for use in production RAG stacks
- Groq LLM comparison for baseline vs. compressed context
- Interactive dashboard with light/dark theme and reusable test cases
- CLI tools for local demos and benchmarking
- Dataset preparation utilities for MS MARCO / NLI style training
- Benchmarking routines to measure compression ratios and latency

## Project structure

```text
.
├── .env.example
├── .gitignore
├── README.md
├── pyproject.toml
├── requirements.txt
├── docs/
│   └── proj_desc_1.md
├── examples/
│   └── demo_rag.py
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
│       ├── data/
│       │   ├── __init__.py
│       │   └── preprocessing.py
│       ├── models/
│       │   ├── __init__.py
│       │   └── cross_encoder.py
│       ├── compression/
│       │   ├── __init__.py
│       │   ├── sentence_splitter.py
│       │   └── compressor.py
│       ├── evaluation/
│       │   ├── __init__.py
│       │   ├── benchmark.py
│       │   └── comparison_metrics.py
│       └── service/
│           ├── __init__.py
│           ├── api.py
│           ├── groq_client.py
│           └── static/
│               └── index.html
└── tests/
    └── test_pipeline.py
```

The application uses the `src/` layout so importable package code stays separate
from project tooling. Human-maintained documentation lives in `docs/`, runnable
utilities in `scripts/`, automated tests in `tests/`, and generated evaluation
artifacts in `reports/`.

## Quickstart

1. Create a virtual environment:

```bash
python -m venv .venv
. .venv/bin/activate  # Linux/macOS
.venv\Scripts\activate  # Windows
```

2. Install dependencies:

```bash
pip install -r requirements.txt
pip install -e .
```

3. Configure Groq in the project root. Copy `.env.example` to `.env` and replace
the placeholder with your API key:

```text
GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=openai/gpt-oss-120b
```

The `.env` file is git-ignored. The key stays in the Python server and is never
returned to the browser. Restart the server after changing the key.

4. Start the API from the repository root in one terminal:

```bash
python -m uvicorn context_compressor.service.api:app --reload
```

5. Start the React 19 + TanStack Start UI from a second terminal:

```powershell
cd .\ui
npm install
npm run dev
```

Open `http://127.0.0.1:3000/`. The Vite proxy forwards requests to FastAPI at
`http://127.0.0.1:8000` (override with `LIMAS_API_URL`). The FastAPI root
continues to serve the self-contained static dashboard as a fallback.

The dashboard supports compression-only runs through `/compress`, paired
baseline/compressed generation through `/compare`, health/model status through
`/health` and `/config`, and workbook-backed analytics through `/analytics`.
PDF and text extraction is available through `/upload_pdf`. Analytics are based
on successful paired comparisons recorded in `reports/eval_met.xlsx`; values
that cannot be measured from the workbook are shown as unavailable rather than
substituted with mock data.

In the Limas UI, enter a query and retrieved passages, then run both comparisons.
The same model and query are used for:
- **Without compressor:** all supplied passages go to Groq.
- **With compressor:** selected sentences go to Groq.

Each response and its prompt/completion token usage and latency are shown in
separate tabs. Prompt tokens, tokens saved, and prompt-token reduction are taken
from Groq's `usage.prompt_tokens` response field for each actual API request, not
estimated from words. These counts include the complete prompt (system
instructions and formatting), matching per-request Groq usage. The compressor's
pre-generation pruning budget is still an approximate word-count heuristic; it
is clearly labeled as such and is not used as the actual token metric. The UI
reports actual prompt tokens saved and their percentage reduction by comparing
the two Groq `usage.prompt_tokens` values. If Groq does not return usage, it shows
`N/A` rather than substituting an estimate.

The Limas React dashboard provides light/dark mode, responsive paired comparisons,
built-in climate/solar/revenue scenarios, and the supplied reference's analytics
and architecture layout. Its playground displays the live per-sentence audit
(isolated score, pairwise gain, final weight, retention status, atomic group,
and decision reason). Analytics are calculated from workbook history. Every
successful comparison is appended to `reports/eval_met.xlsx`
with actual paired prompt usage, latency, answers, and optional
reference-similarity columns. Retrieval itself remains manual/external.

The paired `/compare` endpoint sends the baseline and compressed Groq requests
concurrently. If either request fails, the API reports the failing branch and
provider diagnostic instead of writing a partial workbook row. `POST /compress`
also returns a `sentence_audit` entry for every candidate sentence and does not
call Groq.

### Research features and options

`POST /compress` and `POST /compare` accept three optional Boolean settings,
each enabled by default:

```json
{
  "enable_coref": true,
  "enable_multihop": true,
  "adaptive_gating": true
}
```

- **Discourse preservation:** local adjacent antecedent links are formed for
  leading pronouns and discourse connectives; selected dependent sentences pull
  in their antecedents as an atomic retention block. spaCy's `en_core_web_sm`
  may add subject-pronoun detection. Without the optional package/model, the
  built-in regex analyzer is used.
- **Pairwise interdependence:** Stage A batches isolated query/sentence scores.
  Stage B batches contiguous same-passage sentence-pair scores and blends
  positive joint-relevance gain into each following sentence's score. This is a
  relevance proxy, not an NLI entailment probability.
- **Adaptive gating:** a transparent heuristic classifies factual,
  comparative, and multi-hop query signals; more complex queries get a lower
  cutoff and a higher maximum context ratio. Explicit `threshold` values
  override the adaptive cutoff. `max_tokens` remains an upper bound on the
  local estimated-word budget. The response reports a null adaptive ratio when
  adaptive gating is disabled.

The response includes complexity, selected original sentence indices, the
cutoff and ratio used, preserved-antecedent count, and isolated/pairwise/
coreference analysis timings. Counts remain labeled as word estimates; they
must not be interpreted as exact tokenizer or Groq token counts.

5. Run the demo:

```bash
python -m context_compressor.cli demo
python -m context_compressor.cli compress --no-enable-coref
```

Optional spaCy installation (the regex fallback requires no additional
dependency):

```bash
pip install -e ".[discourse]"
python -m spacy download en_core_web_sm
```

To compare fixed-rule and enhanced compression over a simple/complex case set,
provide a JSON list with `query`, `documents`, and optional `answer` fields:

```bash
python -m context_compressor.cli benchmark --cases query_cases.json
```

The output reports latency overhead and lexical answer/context-similarity
change per case and averaged by inferred query intent. This is a local research
diagnostic, not a controlled end-to-end QA benchmark.

To run a benchmark and append its metrics to `reports/eval_met.xlsx` (worksheet `eval_met`):

```bash
python scripts/eval_met_gen.py
```

For a custom benchmark, provide a JSON file with `query`, a non-empty `documents` string list, and an optional `answer`:

```bash
python scripts/eval_met_gen.py --input benchmark.json
```

Run the automated test suite and write its formatted report to
`reports/pipeline_test_results.txt`:

```bash
python tests/test_pipeline.py
```

See [`docs/proj_desc_1.md`](docs/proj_desc_1.md) for the detailed phase status,
architecture, implementation notes, limitations, and handoff guide.

6. Send a compression-only request:

```bash
curl -X POST http://127.0.0.1:8000/compress \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What causes climate change?",
    "documents": [
      "Climate change is caused by rising greenhouse gas concentrations.",
      "The cafeteria serves lunch from 12pm to 1pm.",
      "Anthropogenic emissions trap heat in the atmosphere and increase global temperatures."
    ]
  }'
```

## Training pipeline overview

The project is designed around the full pipeline described in the specification:

### Phase 1: foundations
- baseline RAG pipeline pattern
- evaluation harness and metrics

### Phase 2: dataset prep and model tuning
- MS MARCO / NLI conversion utilities
- PyTorch cross-encoder training hooks
- local model save/load helpers

### Phase 3: compression logic
- sentence splitting and relevance scoring
- thresholding and token-budget pruning
- optional ONNX optimization paths

### Phase 4: service integration
- FastAPI API wrapper
- retriever-to-compressor integration pattern

### Phase 5: benchmarking
- token reduction percentage
- latency comparison
- answer quality estimation

## Notes

- The default runtime uses a lightweight fallback relevance scorer when Hugging Face models are unavailable,
  keeping the repository runnable in constrained environments.
- The comparison dashboard requires a valid Groq API key in `.env` and makes two concurrent Groq calls per run.
- The comparison Excel sheet stores both answers, Groq-reported prompt/completion
  usage, actual prompt-token savings, compression time, LLM latency, total
  latency, and optional reference similarity. Historical word-count estimates
  remain in explicitly labeled legacy columns only.
- For trained models, replace the fallback scorer with a tuned cross-encoder and optionally export to ONNX Runtime.

## License

MIT
