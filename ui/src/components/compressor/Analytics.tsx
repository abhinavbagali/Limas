import * as Tooltip from "@radix-ui/react-tooltip";
import { Link2, Scissors, Target, Zap } from "lucide-react";
import {
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip as ChartTooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { CSSProperties, ReactNode } from "react";
import type { AnalyticsResult } from "@/lib/api";
import { formatNumber } from "@/lib/utils";

const intentColors = ["var(--primary)", "var(--cyan)", "var(--emerald)"];

function intentName(value: string) {
  const normalized = value.toLowerCase().replaceAll("_", "-");
  if (normalized.includes("multi")) return "Multi-Hop";
  if (normalized.includes("compar")) return "Comparative";
  return "Factual";
}

function savingsLevel(value: number | null) {
  if (value === null) return "heat-0";
  if (value < 10) return "heat-0";
  if (value < 30) return "heat-1";
  if (value < 50) return "heat-2";
  if (value < 70) return "heat-3";
  return "heat-4";
}

function formatIntentCount(value: number, total: number) {
  if (!total) return `${value} runs`;
  return `${value} · ${Math.round((value / total) * 100)}%`;
}

export function Analytics({ data }: { data: AnalyticsResult | null }) {
  const performance = data?.performance ?? [];
  const intents = ["Factual", "Comparative", "Multi-Hop"].map((name) => ({
    name,
    value:
      data?.intent_distribution
        .filter((entry) => intentName(entry.name) === name)
        .reduce((sum, entry) => sum + entry.count, 0) ?? 0,
  }));
  const totalIntents = intents.reduce((sum, item) => sum + item.value, 0);
  const activity = data?.activity ?? [];
  const cells = Array.from({ length: 105 }, (_, index) => {
    const runIndex = index - (105 - activity.length);
    return runIndex >= 0 ? activity[runIndex] : null;
  });

  return (
    <section id="metrics" className="page-section metrics-section scroll-reveal">
      <div className="section-heading">
        <div>
          <div className="section-eyebrow"><span className="eyebrow-line" />MEASURED, NOT ASSUMED</div>
          <h2>Efficiency you can see.</h2>
          <p>Metrics are computed from successful paired runs saved in the evaluation workbook.</p>
        </div>
        <span className="section-badge">{data ? `${data.runs_total} paired runs in history` : "Loading workbook history…"}</span>
      </div>
      <div className="stats-grid">
        <StatCard icon={<Scissors size={17} />} label="Avg. prompt tokens saved" value={formatNumber(data?.avg_prompt_token_reduction_percent, 1)} unit="%" tone="emerald" foot="Provider-reported Groq prompt usage" />
        <StatCard icon={<Zap size={17} />} label="Net latency saved (incl. compression)" value={formatNumber(data?.avg_latency_saved_ms, 0)} unit="ms" tone="cyan" foot="Baseline LLM time minus compression plus compressed LLM time" />
        <StatCard icon={<Target size={17} />} label="Reference-answer Jaccard" value={formatNumber(data?.avg_quality_retention_percent, 1)} unit="%" tone="neutral" foot="Lexical overlap proxy, not semantic quality" />
        <StatCard icon={<Link2 size={17} />} label="Coreferences preserved" value={formatNumber(data?.coreferences_preserved)} unit="edges" tone="gray" foot="Total edges across paired runs" />
      </div>
      <div className="analytics-grid">
        <article className="chart-card performance-card">
          <div className="chart-heading">
            <div><h3>Prompt reduction and net latency impact</h3><p>Prompt-token usage and end-to-end compression-path latency · last ten paired runs</p></div>
            <div className="chart-legend">
              <span><i className="legend-baseline" />Baseline tokens</span>
              <span><i className="legend-compressed" />Limas tokens</span>
              <span><i className="legend-latency" />Net latency saved</span>
            </div>
          </div>
          {performance.length ? (
            <div className="chart-area">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={performance} margin={{ top: 10, right: 14, bottom: 6, left: -14 }}>
                  <CartesianGrid stroke="var(--border)" strokeDasharray="3 5" vertical={false} />
                  <XAxis dataKey="run_number" tickLine={false} axisLine={false} tick={{ fill: "var(--muted-foreground)", fontSize: 11 }} />
                  <YAxis yAxisId="tokens" tickLine={false} axisLine={false} tick={{ fill: "var(--muted-foreground)", fontSize: 11 }} />
                  <YAxis yAxisId="latency" orientation="right" hide />
                  <ChartTooltip
                    contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--foreground)", fontSize: 12 }}
                    labelFormatter={(_, payload) => payload?.[0]?.payload?.test_case ?? "Paired run"}
                    formatter={(value, name) => [`${formatNumber(Number(value))}${name === "Net latency saved" ? " ms" : " tokens"}`, name]}
                  />
                  <Bar yAxisId="tokens" dataKey="baseline_prompt_tokens" name="Baseline prompt" fill="var(--chart-baseline)" radius={[3, 3, 0, 0]} maxBarSize={17} />
                  <Bar yAxisId="tokens" dataKey="compressed_prompt_tokens" name="Limas prompt" fill="var(--primary)" radius={[3, 3, 0, 0]} maxBarSize={17} />
                  <Line yAxisId="latency" dataKey="latency_saved_ms" name="Net latency saved" type="monotone" stroke="var(--cyan)" strokeWidth={2} dot={{ r: 3, fill: "var(--cyan)", strokeWidth: 0 }} connectNulls />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <EmptyChart>No paired runs are available for the chart yet.</EmptyChart>
          )}
          <div className="chart-foot"><span><span className="status-dot" />Actual provider-reported prompt counts</span><span>Net latency includes compression time</span></div>
        </article>
        <article className="chart-card intent-card">
          <div className="chart-heading"><div><h3>The right context for every query.</h3><p>Recorded query-intent distribution</p></div></div>
          {totalIntents ? (
            <div className="intent-chart-layout">
              <div className="donut-area">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={intents.filter((item) => item.value > 0)} dataKey="value" nameKey="name" innerRadius="62%" outerRadius="86%" paddingAngle={3} stroke="none" isAnimationActive={false}>
                      {intents.filter((item) => item.value > 0).map((item) => <Cell key={item.name} fill={intentColors[intents.indexOf(item)]} />)}
                    </Pie>
                    <ChartTooltip contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 6, color: "var(--foreground)", fontSize: 12 }} />
                  </PieChart>
                </ResponsiveContainer>
                <div className="donut-center"><strong>{totalIntents}</strong><span>paired runs</span></div>
              </div>
              <div className="intent-legend">
                {intents.map((item, index) => (
                  <div className="intent-row" key={item.name}>
                    <span>                    <i style={{ "--intent-color": intentColors[index] } as CSSProperties} />{item.name}</span>
                    <strong>{formatIntentCount(item.value, totalIntents)}</strong>
                  </div>
                ))}
                <div className="threshold-range">
                  Observed adaptive threshold
                  <strong>
                    {data?.dynamic_threshold_range.min === null || data?.dynamic_threshold_range.min === undefined
                      ? "Unavailable"
                      : `${formatNumber(data.dynamic_threshold_range.min, 2)} — ${formatNumber(data.dynamic_threshold_range.max, 2)}`}
                  </strong>
                </div>
              </div>
            </div>
          ) : (
            <EmptyChart>No query intents have been recorded yet.</EmptyChart>
          )}
        </article>
        <article className="chart-card heatmap-card">
          <div className="chart-heading"><div><h3>Paired run history</h3><p>Activity and prompt-token savings · last 105 paired runs</p></div><span className="section-badge">{data?.runs_total ?? 0} total runs</span></div>
          <div className="heatmap-months"><span>EARLIER</span><span>RECENT</span></div>
          <Tooltip.Provider delayDuration={100}>
            <div className="heatmap" role="grid" aria-label="Seven by fifteen grid of compression runs">
              {cells.map((run, index) => run ? (
                <Tooltip.Root key={run.run_number}>
                  <Tooltip.Trigger asChild>
                    <button
                      className={`heat-cell ${savingsLevel(run.saved_percent)}`}
                      type="button"
                      role="gridcell"
                      aria-label={`Run ${run.run_number}, ${run.saved_percent === null ? "savings unavailable" : `${formatNumber(run.saved_percent, 1)} percent saved`}`}
                    />
                  </Tooltip.Trigger>
                  <Tooltip.Portal>
                    <Tooltip.Content className="heat-tooltip" side="top">
                      <strong>Run #{run.run_number}</strong>
                      <span>{run.saved_percent === null ? "Token savings unavailable" : `${formatNumber(run.saved_percent, 1)}% prompt tokens saved`}</span>
                      <span>Coreference edges: {run.coref_edges}</span>
                      <span>Latency saved: {run.latency_saved_ms === null ? "N/A" : `${formatNumber(run.latency_saved_ms, 0)} ms`}</span>
                      <Tooltip.Arrow className="fill-card" />
                    </Tooltip.Content>
                  </Tooltip.Portal>
                </Tooltip.Root>
              ) : <span key={`empty-${index}`} className="heat-cell heat-empty" aria-hidden="true" />)}
            </div>
          </Tooltip.Provider>
          <div className="heatmap-legend"><span>Less</span>{["heat-0", "heat-1", "heat-2", "heat-3", "heat-4"].map((level) => <i key={level} className={`heat-cell ${level}`} />)}<span>More savings</span></div>
        </article>
      </div>
    </section>
  );
}

function StatCard({
  icon,
  label,
  value,
  unit,
  tone,
  foot,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  unit: string;
  tone: string;
  foot: string;
}) {
  return (
    <article className={`stat-card tone-${tone}`}>
      <div className="stat-label"><span>{label}</span>{icon}</div>
      <div className="stat-value">{value}<small>{unit}</small></div>
      <div className="stat-foot">{foot}</div>
    </article>
  );
}

function EmptyChart({ children }: { children: string }) {
  return <div className="empty-chart"><span>{children}</span></div>;
}
