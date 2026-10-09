import * as Slider from "@radix-ui/react-slider";
import * as Switch from "@radix-ui/react-switch";
import * as Tabs from "@radix-ui/react-tabs";
import * as Tooltip from "@radix-ui/react-tooltip";
import {
  ArrowRight,
  Check,
  FileText,
  LoaderCircle,
  Play,
  RotateCcw,
  Scissors,
  SlidersHorizontal,
  Sparkles,
  Timer,
  Upload,
} from "lucide-react";
import { useRef, useState, type DragEvent } from "react";
import {
  compareContexts,
  compressContext,
  uploadDocument,
  type CompareResult,
  type CompressionOptions,
  type CompressResult,
} from "@/lib/api";
import { formatNumber, splitSentences } from "@/lib/utils";
import { Button } from "@/components/ui/button";

type ExperimentResult = CompareResult | CompressResult;

const scenarios = {
  climate: {
    name: "Climate & rainfall shifts",
    query: "How does climate change affect precipitation?",
    documents:
      "Climate change alters the global hydrological cycle by increasing evaporation and changing storm tracks. This often shifts regional rainfall patterns.\n\nThe office kitchen is closed on Fridays.\n\nWarmer air can hold more moisture, which may intensify heavy rainfall in some regions. Other regions can experience longer dry periods.",
    expected:
      "Climate change shifts rainfall patterns. Warmer air can intensify heavy rainfall in some regions while other regions may experience longer dry periods.",
  },
  solar: {
    name: "Solar energy efficiency",
    query: "How do solar panels convert sunlight into electricity?",
    documents:
      "Photovoltaic cells absorb photons from sunlight. The energy frees electrons in a semiconductor, creating an electric current.\n\nSolar panels can connect to inverters that convert direct current into alternating current.\n\nThe city library opens at 9 a.m. and has a collection of travel books.",
    expected:
      "Photovoltaic cells convert sunlight into electricity by freeing electrons in a semiconductor; an inverter can convert direct current to alternating current.",
  },
  revenue: {
    name: "Corporate revenue Q3",
    query: "Compare Acme Corp's Q3 revenue with Q2 and explain the main driver.",
    documents:
      "Acme Corp reported Q3 revenue of $4.8 billion, a 12% increase over Q2. The company attributed the gain primarily to stronger cloud subscriptions.\n\nIts cloud division grew 21% year over year, while hardware revenue remained nearly flat.\n\nThe company cafeteria serves breakfast from 7:30 a.m. until 10 a.m.",
    expected:
      "Acme Corp's Q3 revenue was $4.8 billion, up 12% from Q2, mainly driven by stronger cloud subscriptions.",
  },
};

interface PlaygroundProps {
  model: string;
  groqConfigured: boolean;
  onRunComplete: () => void;
}

function AuditContext({
  result,
  documents,
}: {
  result: ExperimentResult;
  documents: string[];
}) {
  let sentenceIndex = 0;
  return (
    <p className="context-copy">
      {documents.map((passage, passageIndex) => (
        <span key={`${passageIndex}-${passage.slice(0, 18)}`}>
          {passageIndex > 0 && <span className="paragraph-break">{"\n\n"}</span>}
          {splitSentences(passage).map((sentence) => {
            const audit = result.sentence_audit[sentenceIndex];
            const currentIndex = sentenceIndex;
            sentenceIndex += 1;
            if (!audit) return <span key={currentIndex}>{sentence} </span>;
            return (
              <Tooltip.Provider key={currentIndex} delayDuration={200}>
                <Tooltip.Root>
                  <Tooltip.Trigger asChild>
                    <span
                      className={audit.retained ? "sentence-kept" : "sentence-pruned"}
                      tabIndex={0}
                    >
                      {sentence}{" "}
                    </span>
                  </Tooltip.Trigger>
                  <Tooltip.Portal>
                    <Tooltip.Content className="audit-tooltip" side="top">
                      <strong>
                        {audit.retained ? "Retained" : "Pruned"} · sentence {currentIndex + 1}
                      </strong>
                      <span>Isolated score: {audit.isolated_score.toFixed(3)}</span>
                      <span>Pairwise gain: {audit.pairwise_gain.toFixed(3)}</span>
                      <span>Final weight: {audit.final_weight.toFixed(3)}</span>
                      <span>
                        {audit.retained ? audit.retention_reason : audit.discard_reason}
                      </span>
                      <Tooltip.Arrow className="fill-card" />
                    </Tooltip.Content>
                  </Tooltip.Portal>
                </Tooltip.Root>
              </Tooltip.Provider>
            );
          })}
        </span>
      ))}
    </p>
  );
}

export function Playground({ model, groqConfigured, onRunComplete }: PlaygroundProps) {
  const [query, setQuery] = useState(scenarios.climate.query);
  const [documentsText, setDocumentsText] = useState(scenarios.climate.documents);
  const [reference, setReference] = useState(scenarios.climate.expected);
  const [scenario, setScenario] = useState<keyof typeof scenarios | "custom">("climate");
  const [features, setFeatures] = useState({ coref: true, multihop: true, adaptive: true });
  const [manualOverride, setManualOverride] = useState(false);
  const [threshold, setThreshold] = useState(0.45);
  const [topK, setTopK] = useState(6);
  const [budget, setBudget] = useState(512);
  const [tab, setTab] = useState("context");
  const [result, setResult] = useState<ExperimentResult | null>(null);
  const [busy, setBusy] = useState<"compare" | "compress" | "upload" | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);

  const documents = documentsText
    .split(/\n\s*\n/)
    .map((passage) => passage.trim())
    .filter(Boolean);

  function loadScenario(value: string) {
    if (value === "custom") {
      setScenario("custom");
      setQuery("");
      setDocumentsText("");
      setReference("");
    } else {
      const item = scenarios[value as keyof typeof scenarios];
      setScenario(value as keyof typeof scenarios);
      setQuery(item.query);
      setDocumentsText(item.documents);
      setReference(item.expected);
    }
    setResult(null);
    setError("");
    setNotice("");
  }

  function buildRequest(): CompressionOptions {
    const options: CompressionOptions = {
      query: query.trim(),
      documents,
      expected_answer: reference.trim() || null,
      test_case: scenario === "custom" ? null : scenarios[scenario].name,
      top_k: topK,
      max_tokens: budget,
      enable_coref: features.coref,
      enable_multihop: features.multihop,
      adaptive_gating: features.adaptive,
    };
    if (!features.adaptive || manualOverride) options.threshold = threshold;
    return options;
  }

  async function runComparison() {
    setError("");
    setNotice("");
    if (!query.trim() || !documents.length) {
      setError("Enter a query and at least one retrieved passage.");
      return;
    }
    setBusy("compare");
    try {
      setResult(await compareContexts(buildRequest()));
      setNotice("Paired answers generated concurrently by the configured Groq model.");
      onRunComplete();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Comparison failed.");
    } finally {
      setBusy(null);
    }
  }

  async function runCompression() {
    setError("");
    setNotice("");
    if (!query.trim() || !documents.length) {
      setError("Enter a query and at least one retrieved passage.");
      return;
    }
    setBusy("compress");
    try {
      setResult(await compressContext(buildRequest()));
      setNotice("Compression-only pass complete; no LLM request was made.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Compression failed.");
    } finally {
      setBusy(null);
    }
  }

  async function receiveFile(file: File | undefined) {
    if (!file) return;
    setError("");
    setNotice("");
    setBusy("upload");
    try {
      const uploaded = await uploadDocument(file);
      setDocumentsText(uploaded.passages.join("\n\n"));
      setScenario("custom");
      setResult(null);
      setNotice(
        `Loaded ${uploaded.passages.length} passage${uploaded.passages.length === 1 ? "" : "s"} from ${uploaded.filename} (${uploaded.page_count} pages).`,
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Document upload failed.");
    } finally {
      setBusy(null);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    event.currentTarget.classList.remove("dropzone-active");
    void receiveFile(event.dataTransfer.files[0]);
  }

  function setFeature(key: keyof typeof features, checked: boolean) {
    setFeatures((current) => ({ ...current, [key]: checked }));
  }

  const comparison = result && "model" in result ? result : null;
  const savedTokens = comparison?.actual_prompt_tokens_saved ?? null;
  const tokenReduction = comparison?.actual_prompt_token_reduction_percent ?? null;
  const prunedCount = result?.sentence_audit.filter((sentence) => !sentence.retained).length ?? 0;

  return (
    <section id="playground" className="page-section playground-section scroll-reveal">
      <div className="section-heading">
        <div>
          <div className="section-eyebrow"><span className="eyebrow-line" />EXPERIMENT WORKSPACE</div>
          <h2>Less context. Same intelligence.</h2>
          <p>See exactly what Limas retains, why sentences are pruned, and what changes in the paired generation.</p>
        </div>
        <span className="section-badge"><span className="status-dot" />Live backend</span>
      </div>

      <div className="workspace">
        <aside className="settings-panel">
          <div className="panel-heading"><SlidersHorizontal size={15} /><strong>Compression settings</strong></div>
          <div className="settings-body">
            <div className="input-label eyebrow-label">RESEARCH FEATURES</div>
            {(
              [
                ["coref", "Discourse preservation", "Keep antecedents with their dependent sentences."],
                ["multihop", "Pairwise interdependence", "Preserve adjacent evidence with joint relevance."],
                ["adaptive", "Adaptive complexity gating", "Adjust relevance cutoff to query intent."],
              ] as const
            ).map(([key, title, description]) => (
              <div className="feature-row" key={key}>
                <div><strong>{title}</strong><small>{description}</small></div>
                <Switch.Root
                  className="switch-root"
                  checked={features[key]}
                  onCheckedChange={(checked) => setFeature(key, checked)}
                  aria-label={title}
                >
                  <Switch.Thumb className="switch-thumb" />
                </Switch.Root>
              </div>
            ))}
            <div className="manual-row">
              <span>Manual threshold override</span>
              <Switch.Root
                className="switch-root"
                checked={manualOverride}
                onCheckedChange={setManualOverride}
                aria-label="Manual threshold override"
              >
                <Switch.Thumb className="switch-thumb" />
              </Switch.Root>
            </div>
            <div className={`slider-list ${!manualOverride ? "slider-list-muted" : ""}`}>
              <RangeControl label="Relevance threshold τ" value={threshold} min={0.1} max={1} step={0.05} display={threshold.toFixed(2)} onChange={setThreshold} disabled={!manualOverride} />
              <RangeControl label="Top-K sentences" value={topK} min={1} max={10} step={1} display={String(topK)} onChange={setTopK} />
              <RangeControl label="Approx. word budget" value={budget} min={64} max={1024} step={32} display={String(budget)} onChange={setBudget} />
            </div>
            <div className="engine-note"><Sparkles size={14} /><span><strong>Source wording stays intact</strong><small>Budget is an estimated word cap, not a tokenizer limit.</small></span></div>
          </div>
        </aside>

        <div className="input-panel">
          <div className="panel-heading"><FileText size={15} /><strong>Input context</strong><div className="scenario-control">
            <label className="sr-only" htmlFor="scenario">Example scenario</label>
            <select id="scenario" value={scenario} onChange={(event) => loadScenario(event.target.value)}>
              {Object.entries(scenarios).map(([key, value]) => <option key={key} value={key}>{value.name}</option>)}
              <option value="custom">Custom scenario</option>
            </select>
            <Button variant="ghost" size="icon" title="Reset current scenario" aria-label="Reset current scenario" onClick={() => loadScenario(scenario)}>
              <RotateCcw size={14} />
            </Button>
          </div></div>
          <div className="input-body">
            <label className="field-label" htmlFor="query">User query <span>QUERY</span></label>
            <textarea id="query" className="query-input" value={query} onChange={(event) => { setQuery(event.target.value); setScenario("custom"); }} placeholder="What do you want to know?" />
            <div className="field-label documents-label"><label htmlFor="documents">Retrieved passages</label><span>{documents.length} passage{documents.length === 1 ? "" : "s"}</span></div>
            <textarea id="documents" className="documents-input" value={documentsText} onChange={(event) => { setDocumentsText(event.target.value); setScenario("custom"); }} placeholder="Paste retrieved documents. Separate passages with blank lines." />
            <div
              className="upload-zone"
              role="button"
              tabIndex={0}
              onClick={() => fileInput.current?.click()}
              onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") fileInput.current?.click(); }}
              onDragOver={(event) => { event.preventDefault(); event.currentTarget.classList.add("dropzone-active"); }}
              onDragLeave={(event) => event.currentTarget.classList.remove("dropzone-active")}
              onDrop={onDrop}
            >
              <Upload size={16} />
              <span><strong>Drop a PDF or TXT file here</strong><small>Text is extracted into the passages field · maximum 25 MB</small></span>
              <Button variant="outline" size="sm" type="button" onClick={(event) => { event.stopPropagation(); fileInput.current?.click(); }}>Browse</Button>
              <input ref={fileInput} type="file" accept=".pdf,.txt,application/pdf,text/plain" hidden onChange={(event) => receiveFile(event.target.files?.[0])} />
            </div>
            <label className="field-label reference-label" htmlFor="reference">Expected reference answer <span>OPTIONAL</span></label>
            <input id="reference" className="text-input" value={reference} onChange={(event) => setReference(event.target.value)} placeholder="Add an answer reference for lexical similarity." />
            <div className="run-row">
              <div className="provider-state"><span className="status-dot" />{groqConfigured ? `Groq · ${model}` : "API online · Groq key not configured"}</div>
              <div className="run-buttons">
                <Button variant="outline" disabled={busy !== null || !query.trim() || !documents.length} onClick={runCompression}>
                  {busy === "compress" ? <LoaderCircle className="spin" size={14} /> : <Scissors size={14} />}
                  Compress only
                </Button>
                <Button className="comparison-button" disabled={busy !== null || !query.trim() || !documents.length} onClick={runComparison}>
                  {busy === "compare" ? <LoaderCircle className="spin" size={14} /> : <Play size={13} fill="currentColor" />}
                  {busy === "compare" ? "Generating both answers…" : "Run paired comparison"}
                  {busy !== "compare" && <ArrowRight size={14} />}
                </Button>
              </div>
            </div>
            {error && <p className="inline-error" role="alert">{error}</p>}
            {notice && <p className="inline-notice" role="status">{notice}</p>}
          </div>
        </div>
      </div>

      <div className="results-heading">
        <div><div className="section-eyebrow"><span className="eyebrow-line" />SIDE-BY-SIDE RESULTS</div><h3>Baseline RAG vs. Limas</h3></div>
        {result && <span className="section-badge success-badge"><Check size={13} />{comparison ? `${formatNumber(tokenReduction, 1)}% actual prompt-token reduction` : `${formatNumber(result.estimated_word_reduction_percent, 1)}% estimated word reduction`}</span>}
      </div>

      <Tabs.Root value={tab} onValueChange={setTab}>
        <Tabs.List className="view-tabs" aria-label="Comparison output type">
          <Tabs.Trigger value="context">Sentence diff</Tabs.Trigger>
          <Tabs.Trigger value="answer">Generated answers</Tabs.Trigger>
        </Tabs.List>
        <div className="comparison-grid">
          <article className="result-card">
            <div className="result-card-heading"><span className="result-icon"><FileText size={15} /></span><div><h4>Baseline RAG</h4><p>Full retrieved context</p></div><span className="result-tag">ORIGINAL</span></div>
            <Tabs.Content value="context" className="result-content">
              <div className="content-label">UNCOMPRESSED CONTEXT</div>
              <p className="context-copy">{documentsText || "Retrieved passages will appear here."}</p>
            </Tabs.Content>
            <Tabs.Content value="answer" className="result-content answer-content">
              <div className="content-label">BASELINE GROQ ANSWER</div>
              <p>{comparison?.without_compressor_answer ?? "Run paired comparison to generate the baseline answer."}</p>
            </Tabs.Content>
            <MetricStrip
              tokens={comparison?.without_compressor_prompt_tokens ?? null}
              latency={comparison?.without_compressor_llm_latency_ms ?? null}
              completion={comparison?.without_compressor_completion_tokens ?? null}
            />
          </article>
          <article className="result-card compressed-card">
            <div className="result-card-heading"><span className="result-icon result-icon-green"><Sparkles size={15} /></span><div><h4>Limas compressed RAG</h4><p>Retained evidence, sentence by sentence</p></div><span className="result-tag result-tag-green">OPTIMIZED</span></div>
            <Tabs.Content value="context" className="result-content">
              {result ? (
                <>
                  <div className="content-label">RETAINED <span className="inline-legend"><i /> PRUNED <i className="red-dot" /></span></div>
                  <AuditContext result={result} documents={documents} />
                </>
              ) : (
                <div className="empty-output"><Scissors size={22} /><span>Your sentence-level diff will appear here.</span><small>Retained context is green; pruned sentences are struck through.</small></div>
              )}
            </Tabs.Content>
            <Tabs.Content value="answer" className="result-content answer-content">
              <div className="content-label">GROUNDED GROQ ANSWER</div>
              <p>{comparison?.with_compressor_answer ?? "Run paired comparison to generate the compressed answer."}</p>
            </Tabs.Content>
            <MetricStrip
              tokens={comparison?.with_compressor_prompt_tokens ?? null}
              latency={comparison?.with_compressor_llm_latency_ms ?? null}
              completion={comparison?.with_compressor_completion_tokens ?? null}
            />
          </article>
        </div>
      </Tabs.Root>

      {result && (
        <>
          <div className="savings-banner">
            <div><strong>{comparison ? `${formatNumber(savedTokens)} prompt tokens saved` : `${formatNumber(result.estimated_compressed_word_count)} estimated words retained`}</strong><span>{comparison ? "Compared using provider-reported Groq prompt usage." : "Compression-only run; no LLM call was made."}</span></div>
            <div className="savings-number">{comparison ? `${formatNumber(tokenReduction, 1)}%` : `${formatNumber(result.estimated_word_reduction_percent, 1)}%`}<small>reduction</small></div>
          </div>
          <div className="audit-summary"><span><Check size={13} />{result.sentence_audit.length - prunedCount} retained</span><span>{prunedCount} pruned</span><span><Timer size={13} />{comparison ? `${formatNumber(comparison.with_compressor_llm_latency_ms, 0)} ms compressed LLM latency` : "No generation request"}</span><span><Sparkles size={13} />{result.preserved_coreferences_count} discourse edges</span></div>
          <details className="audit-details">
            <summary>Full sentence score audit · {result.sentence_audit.length} candidate sentences</summary>
            <div className="audit-table-wrap"><table><thead><tr><th>Sentence</th><th>Isolated</th><th>Pair gain</th><th>Final</th><th>Decision</th><th>Reason</th></tr></thead>
              <tbody>{result.sentence_audit.map((item) => <tr key={item.sentence_index}><td>{item.sentence_index + 1}. {item.text}</td><td>{item.isolated_score.toFixed(3)}</td><td>{item.pairwise_gain.toFixed(3)}</td><td>{item.final_weight.toFixed(3)}</td><td className={item.retained ? "audit-retained" : "audit-pruned"}>{item.retained ? `Retained · group ${item.atomic_group_id ?? "—"}` : "Pruned"}</td><td>{item.retained ? item.retention_reason : item.discard_reason}</td></tr>)}</tbody>
            </table></div>
          </details>
          {comparison && !comparison.metrics_saved && <p className="inline-error" role="status">{comparison.metrics_save_error ?? "Comparison completed; workbook metrics were not saved."}</p>}
        </>
      )}
    </section>
  );
}

function RangeControl({
  label,
  value,
  min,
  max,
  step,
  display,
  disabled = false,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  display: string;
  disabled?: boolean;
  onChange: (value: number) => void;
}) {
  return (
    <label className="range-control">
      <span>{label}<code>{display}</code></span>
      <Slider.Root className="range-root" min={min} max={max} step={step} value={[value]} disabled={disabled} onValueChange={([next]) => onChange(next)}>
        <Slider.Track className="range-track"><Slider.Range className="range-fill" /></Slider.Track>
        <Slider.Thumb className="range-thumb" aria-label={label} />
      </Slider.Root>
      <span className="range-ends"><small>{min}</small><small>{max}</small></span>
    </label>
  );
}

function MetricStrip({
  tokens,
  latency,
  completion,
}: {
  tokens: number | null;
  latency: number | null;
  completion: number | null;
}) {
  return (
    <div className="metric-strip">
      <div><strong>{formatNumber(tokens)}</strong><span>Prompt tokens · Groq actual</span></div>
      <div><strong>{formatNumber(completion)}</strong><span>Completion tokens</span></div>
      <div><strong>{latency === null ? "—" : `${formatNumber(latency, 0)} ms`}</strong><span>LLM generation latency</span></div>
    </div>
  );
}
