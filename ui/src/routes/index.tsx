import * as Dialog from "@radix-ui/react-dialog";
import * as Tooltip from "@radix-ui/react-tooltip";
import {
  ArrowDown,
  ArrowRight,
  ArrowUpRight,
  Boxes,
  CheckCheck,
  ChevronRight,
  Database,
  FileText,
  Github,
  Layers3,
  MessageSquare,
  Moon,
  Network,
  Search,
  Scissors,
  ShieldCheck,
  Sun,
  Workflow,
  X,
  Zap,
} from "lucide-react";
import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useRef, useState, type CSSProperties } from "react";
import { Analytics } from "@/components/compressor/Analytics";
import { ParticleField } from "@/components/compressor/ParticleField";
import { Playground } from "@/components/compressor/Playground";
import { Button } from "@/components/ui/button";
import { getAnalytics, getRuntimeConfig, type AnalyticsResult, type RuntimeConfig } from "@/lib/api";
import { useScrollReveal } from "@/hooks/use-scroll-reveal";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Limas — Subcortical Context Compression Middleware" },
      { name: "description", content: "Limas is subcortical context compression middleware for high-efficiency RAG pipelines." },
    ],
  }),
  component: LimasHome,
});

const pipelineSteps = [
  { icon: MessageSquare, title: "User query", subtitle: "Question", detail: "A natural-language query defines the evidence to retrieve and retain." },
  { icon: FileText, title: "Document", subtitle: "PDF/TXT or passages", detail: "Upload PDF/TXT for page-aware indexing, or keep using the compatible raw-passage workflow." },
  { icon: Database, title: "MiniLM", subtitle: "Dense retrieval", detail: "all-MiniLM-L6-v2 embeds document chunks and the query for first-stage retrieval." },
  { icon: Search, title: "Cross-encoder", subtitle: "Reranking", detail: "The MS MARCO cross-encoder batches query/chunk pairs and reranks retrieved candidates." },
  { icon: Workflow, title: "Limas", subtitle: "Context compression", detail: "Sentence relevance, pairwise gain, discourse preservation, and adaptive gating select context." },
  { icon: CheckCheck, title: "Groq compare", subtitle: "Answer + metrics", detail: "Baseline and compressed contexts are compared; provider usage and workbook metrics are recorded." },
];

const architectureModules = [
  { icon: FileText, name: "PDF Ingestion & Chunking", file: "ingestion/pdf_extractor.py · chunker.py", description: "Extracts page-aware text and builds overlapping chunks while preserving source page ranges.", tag: "PAGE PROVENANCE" },
  { icon: Database, name: "MiniLM VectorStore", file: "retrieval/vector_store.py", description: "Creates normalized dense vectors for document chunks and queries, then retrieves candidates.", tag: "DENSE RETRIEVAL" },
  { icon: Network, name: "CrossEncoderReranker", file: "retrieval/reranker.py · models/cross_encoder.py", description: "Batches query/chunk pairs and reranks the dense candidates with the MS MARCO model.", tag: "BATCHED RERANKING" },
  { icon: Boxes, name: "Limas ContextCompressor", file: "compression/compressor.py · coreference.py · gating.py", description: "Combines relevance, pairwise gain, discourse links, and adaptive context budgets.", tag: "CONTEXT COMPRESSION" },
  { icon: Zap, name: "Groq & Metric Logger", file: "service/groq_client.py · evaluation/comparison_metrics.py", description: "Compares full and compressed contexts and saves provider usage and paired metrics.", tag: "PAIRED EVALUATION" },
];

function LimasHome() {
  const pageRef = useRef<HTMLDivElement>(null);
  const [dark, setDark] = useState(false);
  const [config, setConfig] = useState<RuntimeConfig | null>(null);
  const [analytics, setAnalytics] = useState<AnalyticsResult | null>(null);
  const [analyticsError, setAnalyticsError] = useState("");
  const [activeSection, setActiveSection] = useState("overview");
  const [selectedStep, setSelectedStep] = useState<number | null>(null);
  const [selectedModule, setSelectedModule] = useState<number | null>(null);

  useScrollReveal(pageRef);

  useEffect(() => {
    try {
      const savedTheme = localStorage.getItem("limas-theme") === "dark";
      document.documentElement.classList.toggle("dark", savedTheme);
      document
        .querySelector('meta[name="theme-color"]')
        ?.setAttribute("content", savedTheme ? "#0b0f19" : "#f8fafc");
      setDark(savedTheme);
    } catch {
      document.documentElement.classList.remove("dark");
      setDark(false);
    }
    let alive = true;
    getRuntimeConfig()
      .then((value) => { if (alive) setConfig(value); })
      .catch(() => { if (alive) setConfig(null); });
    refreshAnalytics(alive);
    return () => { alive = false; };
    // The initial page load intentionally owns this one API refresh cycle.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function refreshAnalytics(alive = true) {
    try {
      const data = await getAnalytics();
      if (alive) {
        setAnalytics(data);
        setAnalyticsError("");
      }
    } catch (error) {
      if (alive) setAnalyticsError(error instanceof Error ? error.message : "Analytics could not be loaded.");
    }
  }

  function toggleTheme() {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
    document
      .querySelector('meta[name="theme-color"]')
      ?.setAttribute("content", next ? "#0b0f19" : "#f8fafc");
    try {
      localStorage.setItem("limas-theme", next ? "dark" : "light");
    } catch {
      // The current theme still changes when browser storage is unavailable.
    }
  }

  function navigateTo(section: string) {
    setActiveSection(section);
    document.getElementById(section)?.scrollIntoView({
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth",
      block: "start",
    });
  }

  useEffect(() => {
    const sections = document.querySelectorAll<HTMLElement>("main section[id]");
    if (!("IntersectionObserver" in window)) return;
    const observer = new IntersectionObserver(
      (entries) => entries.forEach((entry) => {
        if (entry.isIntersecting) setActiveSection(entry.target.id);
      }),
      { rootMargin: "-25% 0px -65% 0px" },
    );
    sections.forEach((section) => observer.observe(section));
    return () => observer.disconnect();
  }, []);

  const serviceLabel = config
    ? config.groq_configured
      ? `API Online · Groq key configured`
      : "API Online · Groq key needed"
    : "API status unavailable";

  return (
    <Tooltip.Provider delayDuration={250}>
      <div className={`app-shell ${dark ? "dark" : ""}`} ref={pageRef}>
        <header className="topbar">
          <div className="nav-inner">
            <a className="brand-lockup" href="#overview" onClick={(event) => { event.preventDefault(); navigateTo("overview"); }}>
              <span className="brand-symbol"><Layers3 size={21} /></span>
              <span className="brand-text"><strong>Limas</strong><small>SUBCORTICAL CONTEXT COMPRESSION</small></span>
            </a>
            <nav className="main-nav" aria-label="Main navigation">
              {[["playground", "Playground"], ["metrics", "Metrics & Analytics"], ["architecture", "Architecture"]].map(([id, label]) => (
                <a key={id} href={`#${id}`} className={activeSection === id ? "nav-active" : ""} onClick={(event) => { event.preventDefault(); navigateTo(id); }}>{label}</a>
              ))}
            </nav>
            <div className="nav-controls">
              <span className={`api-pill ${config === null ? "api-unknown" : config.groq_configured ? "" : "api-warning"}`}><span className="status-dot" />{serviceLabel}</span>
              <Button variant="ghost" size="icon" aria-label={dark ? "Switch to light theme" : "Switch to dark theme"} title={dark ? "Light theme" : "Dark theme"} onClick={toggleTheme}>{dark ? <Sun size={17} /> : <Moon size={17} />}</Button>
              <a className="github-link" href="https://github.com" target="_blank" rel="noreferrer"><Github size={14} /><span>GitHub</span><ArrowUpRight size={12} /></a>
            </div>
          </div>
        </header>

        <main>
          <section id="overview" className="hero-section">
            <ParticleField />
            <div className="hero-copy scroll-reveal">
              <div className="hero-eyebrow"><span className="status-dot" />INTELLIGENT MIDDLEWARE FOR RAG <i />v2.0</div>
              <div className="hero-title-row"><h1>Limas</h1><span className="hero-subtitle-pill">Subcortical Context Compression Middleware</span></div>
              <p className="hero-description">Precision context compression for high-efficiency RAG pipelines. Reduce prompt bloat, preserve discourse integrity, and let every retrieved sentence earn its place.</p>
              <div className="hero-actions">
                <Button size="lg" onClick={() => navigateTo("playground")}><Scissors size={15} />Try live compressor<ArrowRight size={15} /></Button>
                <Button variant="outline" size="lg" onClick={() => navigateTo("metrics")}>View performance metrics<ArrowUpRight size={14} /></Button>
              </div>
              <div className="hero-proofs"><span><Scissors size={13} />Fewer irrelevant tokens</span><span><Zap size={13} />Provider-measured usage</span><span><ShieldCheck size={13} />Source facts stay intact</span></div>
            </div>
            <div className="pipeline-panel scroll-reveal">
              <div className="pipeline-heading"><div><span className="section-eyebrow"><i className="eyebrow-line" />FROM DOCUMENT TO ANSWER</span><strong>Retrieval-to-compression pipeline</strong><small>Page-aware indexing, semantic retrieval, reranking, and grounded generation</small></div><span className="pipeline-live"><span className="status-dot" />LIVE API</span></div>
              <div className="pipeline-nodes">
                {pipelineSteps.map((step, index) => {
                  const Icon = step.icon;
                  return (
                    <div className="pipeline-step" key={step.title}>
                      <button type="button" className={`pipeline-node ${index === 4 ? "engine-node" : ""} ${selectedStep === index ? "pipeline-selected" : ""}`} onClick={() => setSelectedStep(selectedStep === index ? null : index)} aria-pressed={selectedStep === index}>
                        <span className="pipeline-icon"><Icon size={21} /></span><strong>{step.title}</strong><small>{step.subtitle}</small>{index === 4 && <span className="engine-label">LIMAS ENGINE</span>}
                      </button>
                      {index < pipelineSteps.length - 1 && <ChevronRight className="pipeline-chevron" size={15} />}
                    </div>
                  );
                })}
              </div>
              {selectedStep !== null && <div className="pipeline-detail">{pipelineSteps[selectedStep].detail}</div>}
              <div className="pipeline-footer"><span><span className="status-dot" />Legacy passage routes remain supported</span><code>/upload_pdf <ArrowRight size={10} /> /index <ArrowRight size={10} /> /retrieve</code></div>
            </div>
          </section>

          <div className="content-wrap">
            <Playground model={config?.model ?? "loading model"} groqConfigured={config?.groq_configured ?? false} onRunComplete={() => refreshAnalytics()} />
            <Analytics data={analytics} />
            {analyticsError && <p className="analytics-error" role="status">Could not load workbook analytics: {analyticsError}</p>}
            <section id="architecture" className="page-section architecture-section scroll-reveal">
              <div className="section-heading">
                <div><div className="section-eyebrow"><span className="eyebrow-line" />UNDER THE HOOD</div><h2>Five stages. One retrieval-aware layer.</h2><p>Follow source pages through dense retrieval, reranking, compression, and paired evaluation.</p></div>
                <span className="section-badge"><Workflow size={13} />Built for RAG pipelines</span>
              </div>
              <div className="module-grid">
                {architectureModules.map((module, index) => {
                  const Icon = module.icon;
                  return (
                    <button className="module-card scroll-reveal" key={module.name} style={{ "--reveal-delay": `${index * 75}ms` } as CSSProperties} onClick={() => setSelectedModule(index)}>
                      <span className="module-icon"><Icon size={19} /></span><span className="module-number">0{index + 1}</span>
                      <strong>{module.name}</strong><code>{module.file}</code><p>{module.description}</p>
                      <span className="module-footer"><small>{module.tag}</small><ArrowUpRight size={15} /></span>
                    </button>
                  );
                })}
              </div>
              <div className="runtime-panel scroll-reveal" aria-label="Runtime component status">
                <div className="runtime-panel-heading"><strong>Runtime status</strong><span>Live configuration from the API</span></div>
                <div className="runtime-status-grid">
                  <RuntimeStatus label="FastAPI service" state={config ? "online" : "offline"} detail={config ? "Reachable" : "Unavailable"} />
                  <RuntimeStatus label="PyTorch + Transformers" state={config?.transformers_available ? "online" : config ? "offline" : "unknown"} detail={config?.transformers_available ? "Runtime ready" : config ? "Not available" : "Waiting for API"} />
                  <RuntimeStatus label="MiniLM encoder" state={config?.embedding_model_loaded ? "online" : config ? "offline" : "unknown"} detail={config?.embedding_model ?? "Waiting for API"} />
                  <RuntimeStatus label="MS MARCO reranker" state={config?.reranker_model_loaded ? "online" : config ? "offline" : "unknown"} detail={config?.reranker_model ?? "Waiting for API"} />
                  <RuntimeStatus label="Compression scorer" state={config?.compression_scorer_loaded ? "online" : config ? "offline" : "unknown"} detail={config?.compression_scorer_model ?? "Waiting for API"} />
                  <RuntimeStatus label="Groq API key" state={config?.groq_configured ? "online" : config ? "offline" : "unknown"} detail={config?.groq_configured ? "Configured · provider not pinged" : config ? "Not configured" : "Waiting for API"} />
                </div>
              </div>
              <div className="api-routes"><span>LIMAS API</span><code>POST /upload_pdf</code><code>POST /index</code><code>POST /retrieve</code><code>POST /compress</code><code>POST /compare</code><code>GET /analytics</code><code>GET /config</code></div>
            </section>
          </div>
        </main>

        <footer className="site-footer">
          <div className="footer-top">
            <a className="footer-brand" href="#overview" onClick={(event) => { event.preventDefault(); navigateTo("overview"); }}><span className="brand-symbol"><Layers3 size={18} /></span><span><strong>Limas v2.0</strong><small>Subcortical Context Compression Middleware</small></span></a>
            <div className="footer-routes"><code>POST /index</code><code>POST /retrieve</code><code>POST /compress</code><code>POST /compare</code><code>GET /analytics</code></div>
            <span className="footer-api-status"><span className="status-dot" />{serviceLabel}</span>
          </div>
          <div className="footer-bottom"><span>© 2026 Limas · Subcortical Context Compression Middleware for RAG Pipelines.</span><span>Precision in context. Clarity in answers.</span></div>
        </footer>

        <Dialog.Root open={selectedModule !== null} onOpenChange={(open) => { if (!open) setSelectedModule(null); }}>
          <Dialog.Portal>
            <Dialog.Overlay className="dialog-overlay" />
            <Dialog.Content className="module-dialog">
              <Dialog.Close asChild><Button variant="ghost" size="icon" className="dialog-close" aria-label="Close details"><X size={17} /></Button></Dialog.Close>
              {selectedModule !== null && <><span className="section-eyebrow"><i className="eyebrow-line" />MODULE 0{selectedModule + 1}</span><Dialog.Title>{architectureModules[selectedModule].name}</Dialog.Title><code>{architectureModules[selectedModule].file}</code><Dialog.Description>{architectureModules[selectedModule].description}</Dialog.Description><Button onClick={() => { setSelectedModule(null); navigateTo("playground"); }}>Explore in playground<ArrowDown size={14} /></Button></>}
            </Dialog.Content>
          </Dialog.Portal>
        </Dialog.Root>
      </div>
    </Tooltip.Provider>
  );
}

function RuntimeStatus({ label, state, detail }: { label: string; state: "online" | "offline" | "unknown"; detail: string }) {
  return (
    <div className={`runtime-status runtime-${state}`}>
      <span className="runtime-status-label"><i className="runtime-dot" />{label}</span>
      <span className="runtime-status-detail">{detail}</span>
      <span className="sr-only">{state}</span>
    </div>
  );
}
