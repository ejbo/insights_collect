"use client";
import { useEffect, useState } from "react";
import useSWR from "swr";
import { api, fetcher } from "../lib/api";
import type { AgentRun, GraphMeta, Report } from "../lib/types";

type ProviderCallRow = {
  id: number;
  provider: string;
  model: string;
  purpose: string;
  tokens_input: number;
  tokens_output: number;
  cost_usd: number;
  latency_ms: number;
  success: boolean;
  error: string | null;
};

function parseUtc(s: string): number {
  const hasTz = /(Z|[+-]\d\d:?\d\d)$/.test(s);
  return new Date(hasTz ? s : s + "Z").getTime();
}

function durationMs(a: string, b: string | null): string {
  if (!b) return "—";
  const ms = parseUtc(b) - parseUtc(a);
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60_000)}m${Math.round((ms % 60_000) / 1000)}s`;
}

function formatClock(s: string): string {
  return new Date(parseUtc(s)).toLocaleTimeString("zh-CN", {
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}

function fmtCost(v: number): string {
  if (!v) return "$0";
  if (v < 0.001) return `$${v.toFixed(5)}`;
  return `$${v.toFixed(4)}`;
}

function Chip({ children, tone = "muted" }: { children: React.ReactNode; tone?: "muted" | "primary" | "success" | "danger" | "warn" }) {
  const cls: Record<typeof tone, string> = {
    muted: "bg-pearl text-ink-muted-80",
    primary: "bg-primary/10 text-primary",
    success: "bg-status-success/10 text-status-success",
    danger: "bg-status-danger/10 text-status-danger",
    warn: "bg-amber-100 text-amber-800",
  } as any;
  return (
    <span className={`inline-flex items-center rounded-full px-1.5 py-0.5 text-caption ${cls[tone]}`}>
      {children}
    </span>
  );
}

/* ---------------- per-node detail renderers ---------------- */

function PlannerDetails({ s }: { s: any }) {
  const sqs: { text: string; lang: string; angle: string }[] = s.sub_queries || [];
  const events: string[] = s.anchor_events || [];
  return (
    <div className="space-y-sm">
      {sqs.length > 0 && (
        <div>
          <div className="mb-xxs text-caption-strong text-ink">子查询 ({sqs.length})</div>
          <ul className="space-y-xxs">
            {sqs.map((q, i) => (
              <li key={i} className="text-caption text-ink">
                <Chip tone={q.lang === "zh" ? "primary" : "muted"}>{q.lang}</Chip>{" "}
                <span className="text-ink-muted-80">[{q.angle}]</span>{" "}
                {q.text}
              </li>
            ))}
          </ul>
        </div>
      )}
      {events.length > 0 && (
        <div>
          <div className="mb-xxs text-caption-strong text-ink">候选 anchor 事件</div>
          <div className="flex flex-wrap gap-xxs">
            {events.map((e) => <Chip key={e}>{e}</Chip>)}
          </div>
        </div>
      )}
    </div>
  );
}

function MultiSearchDetails({
  s, isRunning, reportId,
}: { s: any; isRunning: boolean; reportId: number }) {
  const per: Record<string, any> = s?.per_provider || {};
  const liveCalls = useSWR<ProviderCallRow[]>(
    isRunning ? `/api/runs/report/${reportId}/provider-calls` : null,
    fetcher,
    { refreshInterval: 1500 },
  );
  const liveHits = useSWR<{ id: number; created_at: string }[]>(
    isRunning ? `/api/reports/${reportId}/search-results?limit=1` : null,
    fetcher,
    { refreshInterval: 2000 },
  );
  const liveSearchCount = (liveCalls.data || []).filter((c) => c.purpose === "search").length;
  const lastHitAt = liveHits.data?.[0]?.created_at;

  const [advancing, setAdvancing] = useState(false);
  const [advanced, setAdvanced] = useState(false);

  async function advance() {
    setAdvancing(true);
    try {
      await api(`/api/reports/${reportId}/advance`, { method: "POST" });
      setAdvanced(true);
    } finally {
      setAdvancing(false);
    }
  }

  const rows = Object.entries(per).map(([prov, v]) => ({ prov, ...(v as any) }));
  rows.sort((a, b) => (b.snippets || 0) - (a.snippets || 0));

  return (
    <div className="space-y-sm">
      {isRunning && (
        <div className="flex flex-wrap items-baseline justify-between gap-sm rounded-sm bg-pearl/60 px-md py-sm">
          <div className="text-caption text-ink-muted-80">
            实时:{" "}
            <span className="tabular-nums text-ink">{liveSearchCount}</span>{" "}
            条 provider 搜索调用已落库
            {lastHitAt && (
              <span className="ml-xs text-ink-muted-48">
                · 最近 hit {formatClock(lastHitAt)}
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={advance}
            disabled={advancing || advanced}
            className="btn-pearl !py-1 !px-3 text-caption-strong"
            title="把当前已收集的结果交给下一步，取消还在跑的 provider 调用"
          >
            {advanced ? "已提交，正在收尾…" : advancing ? "处理中…" : "结果已够 · 立即下一步"}
          </button>
        </div>
      )}
      {rows.length > 0 && (
        <table className="w-full text-caption">
          <thead className="text-caption text-ink-muted-48">
            <tr className="text-left">
              <th className="py-xxs">Provider</th>
              <th className="py-xxs text-right tabular-nums" title="该 provider 在本次 multi_search 里发起的调用次数">调用</th>
              <th className="py-xxs text-right tabular-nums" title="provider 返回的搜索结果条数（含 web_search、web_fetch、citation 等）">搜索结果</th>
              <th className="py-xxs text-right tabular-nums">失败</th>
              <th className="py-xxs text-right tabular-nums">tokens</th>
              <th className="py-xxs text-right tabular-nums">cost</th>
              <th className="py-xxs text-right tabular-nums" title="单次调用的平均耗时">平均耗时</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.prov} className="border-t border-hairline">
                <td className="py-xxs text-ink"><code className="font-mono">{r.prov}</code></td>
                <td className="py-xxs text-right tabular-nums">{r.calls}</td>
                <td className="py-xxs text-right tabular-nums text-ink-muted-80">{r.snippets}</td>
                <td className={`py-xxs text-right tabular-nums ${r.errors > 0 ? "text-status-danger" : "text-ink-muted-48"}`}>{r.errors}</td>
                <td className="py-xxs text-right tabular-nums text-ink-muted-80">{r.tokens || 0}</td>
                <td className="py-xxs text-right tabular-nums text-ink-muted-80">{fmtCost(r.cost_usd || 0)}</td>
                <td className="py-xxs text-right tabular-nums text-ink-muted-80">
                  {r.calls > 0 ? `${((r.latency_total_ms || 0) / r.calls / 1000).toFixed(1)}s` : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function DedupDetails({ s }: { s: any }) {
  const top: { domain: string; count: number }[] = s.top_domains || [];
  return (
    <div className="space-y-xxs">
      <div className="text-caption text-ink">
        共 <span className="text-caption-strong tabular-nums">{s.clusters_after_dedup}</span> 个去重后 cluster
      </div>
      {top.length > 0 && (
        <div>
          <div className="mt-xxs mb-xxs text-caption text-ink-muted-48">来源域名 Top {top.length}</div>
          <div className="flex flex-wrap gap-xxs">
            {top.map((d) => (
              <Chip key={d.domain}>{d.domain} · <span className="tabular-nums">{d.count}</span></Chip>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ExpertDetails({ s }: { s: any }) {
  const cands: any[] = s.candidates || [];
  const events: string[] = s.events || [];
  return (
    <div className="space-y-sm">
      {cands.length > 0 && (
        <div>
          <div className="mb-xxs text-caption-strong text-ink">候选专家 ({s.expert_candidates_count})</div>
          <ul className="space-y-xxs">
            {cands.map((c, i) => (
              <li key={i} className="text-caption text-ink">
                <span className="text-caption-strong">{c.name}</span>
                {c.role && <span className="text-ink-muted-80"> · {c.role}</span>}
                {Array.isArray(c.affiliations) && c.affiliations.length > 0 && (
                  <span className="text-ink-muted-48"> · {c.affiliations.join(" / ")}</span>
                )}
                {typeof c.relevance === "number" && (
                  <span className="ml-xxs text-ink-muted-48 tabular-nums">[{c.relevance.toFixed(2)}]</span>
                )}
                {c.rationale && (
                  <div className="mt-xxs text-ink-muted-80">{c.rationale}</div>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
      {events.length > 0 && (
        <div>
          <div className="mb-xxs text-caption-strong text-ink">挖出的事件 / 论坛 ({events.length})</div>
          <div className="flex flex-wrap gap-xxs">
            {events.map((e) => <Chip key={e} tone="primary">{e}</Chip>)}
          </div>
        </div>
      )}
    </div>
  );
}

function ViewpointDetails({ s }: { s: any }) {
  const vps: any[] = s.viewpoints || [];
  if (vps.length === 0) return <div className="text-caption text-ink-muted-48">尚未抽取观点</div>;
  return (
    <div>
      <div className="mb-xxs text-caption-strong text-ink">7 元组观点 ({s.viewpoints_extracted})</div>
      <ul className="space-y-sm">
        {vps.map((v, i) => (
          <li key={i} className="border-b border-hairline pb-xs last:border-0">
            <div className="text-caption">
              <span className="text-caption-strong text-ink">{v.expert_name}</span>
              {v.expert_role && <span className="text-ink-muted-80"> · {v.expert_role}</span>}
              {v.claim_when && <span className="text-ink-muted-48"> · {v.claim_when}</span>}
              {v.claim_where && <span className="text-ink-muted-48"> · {v.claim_where}</span>}
              {typeof v.confidence === "number" && (
                <span className="ml-xxs text-ink-muted-48 tabular-nums">[c={v.confidence.toFixed(2)}]</span>
              )}
            </div>
            {v.claim_what && <p className="mt-xxs text-caption text-ink">{v.claim_what}</p>}
            <div className="mt-xxs text-caption text-ink-muted-48">
              {v.claim_medium && <span>{v.claim_medium}</span>}
              {v.claim_source_url && (
                <>
                  {" · "}
                  <a className="text-primary hover:underline break-all" href={v.claim_source_url} target="_blank" rel="noreferrer">
                    {v.claim_source_url}
                  </a>
                </>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

const KIND_TONE: Record<string, "primary" | "success" | "warn" | "muted"> = {
  consensus: "success",
  dissent: "warn",
  spotlight: "primary",
  insight: "muted",
};

function ClusterDetails({ s }: { s: any }) {
  const cbt: Record<string, { label: string; kind: string }[]> = s.clusters_by_topic || {};
  const summaries: Record<string, string> = s.section_summaries || {};
  const topics = Object.keys(cbt);
  return (
    <div className="space-y-md">
      {topics.map((t) => (
        <div key={t}>
          <div className="text-caption-strong text-ink">{t}</div>
          <div className="mt-xxs flex flex-wrap gap-xxs">
            {cbt[t].map((c, i) => (
              <Chip key={i} tone={KIND_TONE[c.kind] || "muted"}>
                {c.kind} · {c.label}
              </Chip>
            ))}
          </div>
          {summaries[t] && (
            <p className="mt-xs text-caption text-ink-muted-80">{summaries[t]}</p>
          )}
        </div>
      ))}
      {topics.length === 0 && <div className="text-caption text-ink-muted-48">尚无聚类</div>}
    </div>
  );
}

function KnowledgeDetails({ s }: { s: any }) {
  return (
    <div className="text-caption text-ink-muted-80">
      Experts <span className="text-ink tabular-nums">{s.experts_persisted}</span> ·{" "}
      Events <span className="text-ink tabular-nums">{s.events_persisted}</span> ·{" "}
      Viewpoints <span className="text-ink tabular-nums">{s.viewpoints_persisted}</span>
    </div>
  );
}

function ComposerDetails({ s, reportId }: { s: any; reportId: number }) {
  return (
    <div className="flex flex-wrap gap-sm text-caption">
      {s.md_generated && (
        <a className="text-primary hover:underline" href={`/api/reports/${reportId}/markdown`} target="_blank" rel="noreferrer">
          ↗ Markdown
        </a>
      )}
      {s.outline_generated && (
        <a className="text-primary hover:underline" href={`/api/reports/${reportId}/outline`} target="_blank" rel="noreferrer">
          ↗ Outline JSON
        </a>
      )}
      {s.pdf_generated && (
        <a className="text-primary hover:underline" href={`/api/reports/${reportId}/pdf`} target="_blank" rel="noreferrer">
          ↗ PDF
        </a>
      )}
    </div>
  );
}

function NodeBody({
  nodeName, stats, isRunning, reportId,
}: {
  nodeName: string;
  stats: any;
  isRunning: boolean;
  reportId: number;
}) {
  if (!stats) return <div className="text-caption text-ink-muted-48">暂无明细</div>;
  switch (nodeName) {
    case "planner": return <PlannerDetails s={stats} />;
    case "multi_search": return <MultiSearchDetails s={stats} isRunning={isRunning} reportId={reportId} />;
    case "dedup_merger": return <DedupDetails s={stats} />;
    case "expert_discoverer": return <ExpertDetails s={stats} />;
    case "viewpoint_extractor": return <ViewpointDetails s={stats} />;
    case "cluster_analyzer": return <ClusterDetails s={stats} />;
    case "knowledge_writer": return <KnowledgeDetails s={stats} />;
    case "report_composer": return <ComposerDetails s={stats} reportId={reportId} />;
    default: return <pre className="text-caption">{JSON.stringify(stats, null, 2)}</pre>;
  }
}

/* ---------------- main component ---------------- */

export function AgentStepper({
  reportId,
  status,
}: {
  reportId: number;
  status: Report["status"];
}) {
  const { data: meta } = useSWR<GraphMeta>("/api/runs/graph-meta", fetcher);
  const { data: runs } = useSWR<AgentRun[]>(
    `/api/runs/report/${reportId}/agent-runs`,
    fetcher,
    { refreshInterval: 1500 },
  );

  const isLive = status === "running" || status === "pending";
  const [open, setOpen] = useState(isLive);
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set());

  function toggleNode(name: string) {
    setExpandedNodes((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  // auto-expand while running, auto-collapse on completion
  useEffect(() => {
    setOpen(isLive);
  }, [isLive]);

  // auto-expand the currently running node so the user sees live detail —
  // additive only; never collapses what the user already opened.
  useEffect(() => {
    if (!meta || !runs) return;
    const runByNode = new Map<string, AgentRun>();
    runs.forEach((r) => runByNode.set(r.graph_node, r));
    if (status === "running") {
      const runningNode = meta.nodes.find((n) => !runByNode.has(n.name));
      if (runningNode) {
        setExpandedNodes((prev) => {
          if (prev.has(runningNode.name)) return prev;
          const next = new Set(prev);
          next.add(runningNode.name);
          return next;
        });
      }
    }
  }, [meta, runs, status]);

  if (!meta) return null;
  const runByNode = new Map<string, AgentRun>();
  (runs || []).forEach((r) => runByNode.set(r.graph_node, r));

  const completedCount = meta.nodes.filter((n) => runByNode.has(n.name) && !runByNode.get(n.name)?.error).length;
  const totalCount = meta.nodes.length;
  const pct = Math.round((completedCount / totalCount) * 100);

  let runningIdx = -1;
  if (status === "running" || status === "pending") {
    for (let i = 0; i < meta.nodes.length; i++) {
      if (!runByNode.has(meta.nodes[i].name)) {
        runningIdx = i;
        break;
      }
    }
  }

  const totalTokens = (runs || []).reduce((acc, r) => acc + (r.tokens || 0), 0);
  const totalCost = (runs || []).reduce((acc, r) => acc + (r.cost_usd || 0), 0);

  const collapsedLabel =
    status === "succeeded"
      ? `已完成全部 ${totalCount} 步 · 查看生成过程`
      : status === "failed"
        ? `生成失败 · 查看流程详情`
        : status === "cancelled"
          ? `已取消 · 查看流程详情`
          : `${completedCount}/${totalCount} 步完成 · 展开详情`;

  const expandableNames = meta.nodes
    .filter((n, i) => runByNode.has(n.name) || i === runningIdx)
    .map((n) => n.name);
  const allExpanded =
    expandableNames.length > 0 &&
    expandableNames.every((name) => expandedNodes.has(name));

  return (
    <section className="card-utility">
      <header className="flex flex-wrap items-baseline justify-between gap-xs">
        <h3 className="font-display text-tagline text-ink">流程</h3>
        <div className="flex items-baseline gap-md text-caption">
          {open && expandableNames.length > 0 && (
            <button
              type="button"
              onClick={() =>
                setExpandedNodes(allExpanded ? new Set() : new Set(expandableNames))
              }
              className="text-primary hover:underline"
            >
              {allExpanded ? "全部收起" : "全部展开"}
            </button>
          )}
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="text-primary hover:underline"
          >
            {open ? "收起" : collapsedLabel}
          </button>
        </div>
      </header>

      {/* Progress bar */}
      <div className="mt-sm">
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-hairline">
          <div
            className={
              "h-full transition-all duration-500 " +
              (status === "failed" ? "bg-status-danger" : "bg-primary")
            }
            style={{ width: `${pct}%` }}
          />
        </div>
        <div className="mt-xxs flex flex-wrap items-baseline justify-between gap-xs text-caption text-ink-muted-48 tabular-nums">
          <span>{completedCount} / {totalCount} · {pct}%</span>
          <span>{totalTokens} tok · {fmtCost(totalCost)}</span>
        </div>
      </div>

      {open && (
        <ol className="mt-md space-y-xs">
          {meta.nodes.map((n, idx) => {
            const run = runByNode.get(n.name);
            const isRunning = idx === runningIdx;
            const isDone = !!run;
            const hasError = !!run?.error;
            const dotClass = hasError
              ? "bg-status-danger"
              : isDone
                ? "bg-status-success"
                : isRunning
                  ? "bg-primary animate-pulse"
                  : "bg-hairline";
            const isExpanded = expandedNodes.has(n.name);
            const stats = (run?.state_out as any) || null;
            const expandable = isDone || isRunning;
            return (
              <li key={n.name} className="rounded-tile-lg border border-hairline">
                <button
                  type="button"
                  onClick={() => expandable && toggleNode(n.name)}
                  className={`flex w-full items-start gap-sm p-sm text-left ${expandable ? "hover:bg-pearl" : "cursor-default"}`}
                >
                  <span className={`mt-1.5 inline-block h-2.5 w-2.5 shrink-0 rounded-full ${dotClass}`} />
                  <div className="flex-1 min-w-0">
                    <div className="flex flex-wrap items-baseline gap-xs">
                      <span className={
                        isDone || isRunning
                          ? "text-body-strong text-ink"
                          : "text-body text-ink-muted-48"
                      }>
                        {idx + 1}. {n.label}
                      </span>
                      {run && (
                        <span className="text-caption text-ink-muted-48 tabular-nums">
                          {durationMs(run.started_at, run.finished_at)}
                          {run.tokens > 0 && ` · ${run.tokens} tok`}
                          {run.cost_usd > 0 && ` · ${fmtCost(run.cost_usd)}`}
                        </span>
                      )}
                      {isRunning && <Chip tone="primary">运行中…</Chip>}
                      {expandable && (
                        <span className="ml-auto text-caption text-ink-muted-48">
                          {isExpanded ? "▾" : "▸"}
                        </span>
                      )}
                    </div>
                    {hasError && (
                      <div className="mt-xxs break-all text-caption text-status-danger">
                        {run!.error}
                      </div>
                    )}
                  </div>
                </button>
                {isExpanded && expandable && (
                  <div className="border-t border-hairline bg-pearl/50 p-sm">
                    <NodeBody
                      nodeName={n.name}
                      stats={stats}
                      isRunning={isRunning}
                      reportId={reportId}
                    />
                  </div>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
