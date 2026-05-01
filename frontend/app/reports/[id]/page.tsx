"use client";
import { use, useState } from "react";
import useSWR from "swr";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, fetcher } from "../../../lib/api";
import type { Report } from "../../../lib/types";
import { AgentStepper } from "../../../components/AgentStepper";
import { Pulse, Skeleton } from "../../../components/Skeleton";
import { SearchResultsPanel } from "../../../components/SearchResultsPanel";
import { ExpertQuotesView } from "../../../components/ExpertQuotesView";

const STATUS_CLASS: Record<Report["status"], string> = {
  pending: "status-pending",
  running: "status-running",
  succeeded: "status-succeeded",
  failed: "status-failed",
  cancelled: "status-cancelled",
};

const STATUS_LABEL: Record<Report["status"], string> = {
  pending: "等待中",
  running: "运行中",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

export default function ReportDetail({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const { data: report } = useSWR<Report>(`/api/reports/${id}`, fetcher, {
    refreshInterval: 3000,
  });
  const { data: md } = useSWR<string>(
    report?.md_path ? `/api/reports/${id}/markdown` : null,
    fetcher,
    { refreshInterval: 5000 },
  );
  const { data: outline } = useSWR<any>(
    report?.outline_json_path ? `/api/reports/${id}/outline` : null,
    fetcher,
  );
  const { data: providerCalls } = useSWR<any[]>(
    `/api/runs/report/${id}/provider-calls`,
    fetcher,
    { refreshInterval: 3000 },
  );

  const [showOutline, setShowOutline] = useState(false);
  const [advancing, setAdvancing] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [tab, setTab] = useState<"report" | "quotes">("report");
  const [outlineCopied, setOutlineCopied] = useState(false);

  async function copyOutline() {
    if (!outline) return;
    try {
      await navigator.clipboard.writeText(JSON.stringify(outline, null, 2));
      setOutlineCopied(true);
      setTimeout(() => setOutlineCopied(false), 1800);
    } catch {
      // clipboard blocked — fall back to manual selection
    }
  }

  async function advance() {
    setAdvancing(true);
    try {
      await api(`/api/reports/${id}/advance`, { method: "POST" });
    } finally {
      setAdvancing(false);
    }
  }

  async function cancel() {
    if (!confirm("确认中止这份报告？已生成的中间结果会保留，但不会继续推进。")) return;
    setCancelling(true);
    try {
      await api(`/api/reports/${id}/cancel`, { method: "POST" });
    } finally {
      setCancelling(false);
    }
  }

  if (!report) {
    return (
      <div className="space-y-md">
        <Skeleton className="h-8 w-2/3" />
        <Skeleton className="h-4 w-1/3" />
        <div className="grid grid-cols-1 gap-md md:grid-cols-3">
          <Skeleton className="h-24" rounded="rounded-tile-lg" />
          <Skeleton className="h-24" rounded="rounded-tile-lg" />
          <Skeleton className="h-24" rounded="rounded-tile-lg" />
        </div>
      </div>
    );
  }

  const isLive = report.status === "running" || report.status === "pending";

  return (
    <div className="space-y-xl">
      <header className="flex flex-col gap-md md:flex-row md:items-start md:justify-between">
        <div className="min-w-0 flex-1">
          <h1 className="font-display text-display-md text-ink">{report.title}</h1>
          <p className="mt-xs text-caption text-ink-muted-48">
            {report.focus_topics?.join(" · ")} ·{" "}
            {new Date(report.time_range_start).toLocaleDateString()} –{" "}
            {new Date(report.time_range_end).toLocaleDateString()}
          </p>
          <div className="mt-md flex items-center gap-sm">
            {isLive ? (
              <Pulse label={report.status === "running" ? "运行中" : "等待中"} />
            ) : (
              <span className={STATUS_CLASS[report.status]}>{STATUS_LABEL[report.status]}</span>
            )}
            <span className="text-caption text-ink-muted-80 tabular-nums">
              ${(report.total_cost_usd ?? 0).toFixed(4)} ·{" "}
              {report.total_tokens || 0} tokens
            </span>
            {isLive && (report.total_cost_usd ?? 0) > 0 && (
              <span className="text-caption text-ink-muted-48">实时累计</span>
            )}
          </div>
          {report.error && (
            <div className="mt-md rounded-tile-lg border border-status-danger/30 bg-status-danger/10 p-md">
              <pre className="whitespace-pre-wrap font-mono text-caption text-status-danger">
                {report.error}
              </pre>
            </div>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-xs">
          {isLive && (
            <>
              <button
                onClick={advance}
                disabled={advancing}
                title="把当前已收集的结果交给下一步，取消还在跑的 provider 调用"
                className="btn-secondary-pill"
              >
                {advancing ? "处理中…" : "跳过当前步骤"}
              </button>
              <button
                onClick={cancel}
                disabled={cancelling}
                className="btn-pearl !border-status-danger/40 !text-status-danger"
              >
                {cancelling ? "中止中…" : "中止报告"}
              </button>
            </>
          )}
          {report.pdf_path && (
            <a href={`/api/reports/${id}/pdf`} className="btn-primary">
              下载 PDF
            </a>
          )}
          {report.outline_json_path && (
            <button
              onClick={() => setShowOutline((v) => !v)}
              className="btn-secondary-pill"
            >
              {showOutline ? "收起大纲" : "展开大纲"}
            </button>
          )}
        </div>
      </header>

      {showOutline && outline && (
        <div className="surface-card relative bg-tile p-lg max-h-96 overflow-auto">
          <button
            type="button"
            onClick={copyOutline}
            className="btn-pearl absolute right-md top-md !text-caption"
            title="复制完整大纲 JSON 到剪贴板"
          >
            {outlineCopied ? "已复制 ✓" : "一键复制"}
          </button>
          <pre className="font-mono text-caption text-body-on-dark whitespace-pre-wrap pr-[120px]">
            {JSON.stringify(outline, null, 2)}
          </pre>
        </div>
      )}

      <AgentStepper reportId={Number(id)} status={report.status} />

      {/* Tab switcher */}
      <div className="flex items-center gap-xs border-b border-hairline">
        <button
          type="button"
          onClick={() => setTab("report")}
          className={
            "border-b-2 px-md py-sm text-caption-strong transition-colors " +
            (tab === "report"
              ? "border-primary text-ink"
              : "border-transparent text-ink-muted-48 hover:text-ink")
          }
        >
          研究报告
        </button>
        <button
          type="button"
          onClick={() => setTab("quotes")}
          className={
            "border-b-2 px-md py-sm text-caption-strong transition-colors " +
            (tab === "quotes"
              ? "border-primary text-ink"
              : "border-transparent text-ink-muted-48 hover:text-ink")
          }
        >
          专家言论
        </button>
      </div>

      {tab === "quotes" ? (
        <ExpertQuotesView
          reportId={Number(id)}
          focusTopics={report.focus_topics || []}
        />
      ) : (
      <section className="grid grid-cols-1 gap-lg lg:grid-cols-3">
        <div className="card-utility lg:col-span-2 lg:p-xxl">
          {md ? (
            <div className="prose-md">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{md}</ReactMarkdown>
            </div>
          ) : isLive ? (
            <div className="flex flex-col items-center gap-sm py-xxl">
              <Pulse label="正在生成报告" />
              <p className="text-caption text-ink-muted-48">
                上方流程会实时显示每一步的进度与花费
              </p>
            </div>
          ) : (
            <div className="py-xxl text-center text-caption text-ink-muted-48">
              尚未生成
            </div>
          )}
        </div>

        <aside className="space-y-lg">
          <SearchResultsPanel reportId={Number(id)} />

          <div className="card-utility">
            <div className="flex items-baseline justify-between">
              <h3 className="font-display text-tagline text-ink">Provider 调用 · 花费明细</h3>
              <span className="text-caption text-ink-muted-48 tabular-nums">
                合计 ${(providerCalls || []).reduce((s, c: any) => s + (c.cost_usd || 0), 0).toFixed(4)}
                {" · "}
                {(providerCalls || []).reduce((s, c: any) => s + (c.tokens_input || 0) + (c.tokens_output || 0), 0)} tokens
              </span>
            </div>
            <ul className="mt-md max-h-[420px] space-y-sm overflow-auto">
              {(providerCalls || []).map((c: any, i: number) => {
                const ex = c.extra || {};
                const toolUsage = ex.tool_usage as Record<string, number> | undefined;
                const pass = ex.pass as string | undefined;
                const handles = ex.candidate_handles as string[] | undefined;
                const xs = ex.x_search as { from_date?: string; to_date?: string; allowed_x_handles?: string[] } | undefined;
                return (
                  <li
                    key={i}
                    className="border-b border-hairline pb-sm last:border-0"
                  >
                    <div className="flex items-center gap-xs">
                      <span
                        className={
                          "inline-block h-2 w-2 rounded-full " +
                          (c.success ? "bg-status-success" : "bg-status-danger")
                        }
                      />
                      <code className="font-mono text-caption text-ink">
                        {c.provider}/{c.model}
                      </code>
                      <span className="text-caption text-ink-muted-48">
                        · {c.purpose}
                      </span>
                      {pass && (
                        <span className="status-pill bg-primary/10 text-primary">
                          {pass === "x_event" ? "事→人" : pass === "x_people" ? "人→事" : pass}
                        </span>
                      )}
                    </div>
                    <div className="mt-xxs text-caption text-ink-muted-48 tabular-nums">
                      {((c.latency_ms || 0) / 1000).toFixed(1)}s · ${c.cost_usd?.toFixed(4)}
                      {" · "}
                      {(c.tokens_input || 0) + (c.tokens_output || 0)} tok
                      {ex.reasoning_tokens ? ` (含 ${ex.reasoning_tokens} reasoning)` : ""}
                    </div>
                    {toolUsage && Object.keys(toolUsage).length > 0 && (
                      <div className="mt-xxs flex flex-wrap gap-xxs text-caption text-ink-muted-48">
                        {Object.entries(toolUsage).map(([k, v]) => (
                          <span key={k} className="rounded border border-hairline px-xxs">
                            {k.replace("SERVER_SIDE_TOOL_", "").toLowerCase()} × {v}
                          </span>
                        ))}
                      </div>
                    )}
                    {xs && (
                      <div className="mt-xxs text-caption text-ink-muted-48 truncate">
                        {xs.from_date}–{xs.to_date}
                        {xs.allowed_x_handles && xs.allowed_x_handles.length > 0 && (
                          <> · @{xs.allowed_x_handles.slice(0, 4).join(" @")}{xs.allowed_x_handles.length > 4 ? " …" : ""}</>
                        )}
                      </div>
                    )}
                    {!xs && handles && handles.length > 0 && (
                      <div className="mt-xxs text-caption text-ink-muted-48 truncate">
                        候选 @{handles.slice(0, 5).join(" @")}{handles.length > 5 ? ` (+${handles.length - 5})` : ""}
                      </div>
                    )}
                    {c.error && (
                      <div className="mt-xxs text-caption text-status-danger break-all">
                        {c.error}
                      </div>
                    )}
                  </li>
                );
              })}
              {(providerCalls || []).length === 0 && (
                <li className="text-caption text-ink-muted-48">暂无调用</li>
              )}
            </ul>
          </div>
        </aside>
      </section>
      )}
    </div>
  );
}
