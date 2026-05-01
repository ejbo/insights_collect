"use client";
import useSWR from "swr";
import Link from "next/link";
import { fetcher } from "../lib/api";
import { Skeleton, Pulse, SkeletonRow } from "../components/Skeleton";
import type { Report, Stats } from "../lib/types";

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

function StatusPill({ status }: { status: Report["status"] }) {
  return <span className={STATUS_CLASS[status]}>{STATUS_LABEL[status]}</span>;
}

type StatTile = {
  key: keyof Stats;
  label: string;
  href: string | null;
  hint: string;
};

const STAT_TILES: StatTile[] = [
  { key: "reports", label: "报告", href: "/reports", hint: "已生成的研究报告" },
  { key: "experts", label: "专家", href: "/experts", hint: "去重后的发声主体" },
  { key: "viewpoints", label: "观点", href: "/viewpoints", hint: "7 元组结构化观点" },
  { key: "events", label: "事件", href: "/events", hint: "anchor 论坛 / 节目 / 报告" },
  { key: "sources", label: "信源", href: null, hint: "已收录的来源域" },
  { key: "topics", label: "主题", href: null, hint: "已建立的主题节点" },
];

type FlowStep = {
  num: number;
  short: string;
  name: string;
  logic: string;
  out: string;
};

type FlowPhase = {
  id: string;
  title: string;
  hint: string;
  dotClass: string;        // Tailwind requires concrete class names, not interpolated.
  steps: FlowStep[];
};

const FLOW: FlowPhase[] = [
  {
    id: "collect",
    title: "Collect · 采集",
    hint: "从主题到原始片段",
    dotClass: "bg-primary",
    steps: [
      {
        num: 1,
        short: "Planner",
        name: "拆解主题",
        logic: "把焦点主题拆成 4–8 条多语言、多视角子查询，标注合适的 provider 子集。",
        out: "sub_queries · anchor 候选事件",
      },
      {
        num: 2,
        short: "MultiSearch",
        name: "多源并行检索",
        logic: "(子查询 × provider) 任务一次性 fan-out，结果到达即落库实时可见。",
        out: "raw_snippets · 实时 SearchHits",
      },
      {
        num: 3,
        short: "DedupMerger",
        name: "跨源去重",
        logic: "按 normalized URL 聚类同一来源；无 URL 的按文本相似度合并。",
        out: "snippets_clusters",
      },
    ],
  },
  {
    id: "analyze",
    title: "Analyze · 分析",
    hint: "从片段到结构化观点",
    dotClass: "bg-status-success",
    steps: [
      {
        num: 4,
        short: "ExpertDiscoverer",
        name: "双向挖人",
        logic: "由人到事 + 由事到人；从论坛/节目反向挖讲者，跨源命中加权打分。",
        out: "expert_candidates · discovered_events",
      },
      {
        num: 5,
        short: "ViewpointExtractor",
        name: "7 元组抽取",
        logic: "对候选专家抽取 (who/role + when + where + what + quote + medium + source)。",
        out: "extracted_viewpoints",
      },
      {
        num: 6,
        short: "ClusterAnalyzer",
        name: "共识 / 分歧 / 重点 / 启示",
        logic: "按主题分组观点后做深度聚类，并写出共同点 / 分歧 / 启示的 summary。",
        out: "clusters_by_topic · section_summaries",
      },
    ],
  },
  {
    id: "output",
    title: "Output · 输出",
    hint: "落库 + 渲染",
    dotClass: "bg-ink",
    steps: [
      {
        num: 7,
        short: "KnowledgeWriter",
        name: "落库",
        logic: "experts / events / sources / viewpoints 增量入库；savepoint 保护单条。",
        out: "持久化的知识图节点",
      },
      {
        num: 8,
        short: "ReportComposer",
        name: "渲染输出",
        logic: "按 markdown / outline 模板填充内容，渲染 md + JSON outline + PDF。",
        out: "md_path · outline_json_path · pdf_path",
      },
    ],
  },
];

function Chevron() {
  return (
    <svg
      aria-hidden
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="shrink-0 text-ink-muted-48"
    >
      <path d="M9 6l6 6-6 6" />
    </svg>
  );
}

function PhaseConnector() {
  return (
    <div aria-hidden className="my-md flex items-center gap-xs px-lg">
      <span className="h-px flex-1 bg-hairline" />
      <svg
        width="16"
        height="16"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="text-ink-muted-48"
      >
        <path d="M12 5v14M5 12l7 7 7-7" />
      </svg>
      <span className="h-px flex-1 bg-hairline" />
    </div>
  );
}

function StepCard({ step }: { step: FlowStep }) {
  return (
    <div className="group relative flex h-full min-w-[14rem] flex-1 flex-col rounded-tile-lg border border-hairline bg-canvas p-md transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md">
      <div className="flex items-baseline justify-between">
        <span className="font-display text-caption-strong text-ink-muted-48 tabular-nums">
          {String(step.num).padStart(2, "0")}
        </span>
        <span className="font-mono text-caption text-ink-muted-48">{step.short}</span>
      </div>
      <div className="mt-xs text-body-strong text-ink">{step.name}</div>
      <p className="mt-xxs flex-1 text-caption text-ink-muted-80">{step.logic}</p>
      <div className="mt-sm border-t border-hairline pt-xs text-caption text-ink-muted-48">
        <span className="font-mono">{step.out}</span>
      </div>
    </div>
  );
}

function PhaseRow({ phase }: { phase: FlowPhase }) {
  return (
    <div>
      <div className="mb-sm flex items-baseline gap-sm">
        <span
          aria-hidden
          className={`inline-block h-2 w-2 rounded-full ${phase.dotClass}`}
        />
        <h3 className="font-display text-tagline text-ink">{phase.title}</h3>
        <span className="text-caption text-ink-muted-48">{phase.hint}</span>
      </div>
      <div className="flex flex-wrap items-stretch gap-xs">
        {phase.steps.map((s, i) => (
          <div key={s.num} className="flex flex-1 items-stretch gap-xs">
            <StepCard step={s} />
            {i < phase.steps.length - 1 && (
              <div className="flex shrink-0 items-center">
                <Chevron />
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export default function Dashboard() {
  const { data: stats } = useSWR<Stats>("/api/stats", fetcher, { refreshInterval: 5000 });
  const { data: reports } = useSWR<Report[]>("/api/reports?limit=10", fetcher, {
    refreshInterval: 3000,
  });

  return (
    <div className="space-y-xxl">
      {/* 数据概览 */}
      <section className="grid grid-cols-2 gap-sm sm:gap-md md:grid-cols-3 lg:grid-cols-6">
        {STAT_TILES.map((t) => {
          const value = stats?.[t.key];
          const inner = (
            <div className="h-full rounded-tile-lg border border-hairline bg-canvas p-md transition-all duration-200 hover:-translate-y-0.5 hover:border-ink/20 hover:shadow-sm">
              <div className="text-caption text-ink-muted-48">{t.label}</div>
              {stats === undefined ? (
                <Skeleton className="mt-xs h-9 w-16" />
              ) : (
                <div className="mt-xs font-display text-display-md text-ink tabular-nums">
                  {value ?? "—"}
                </div>
              )}
              <div className="mt-xxs text-caption text-ink-muted-48 line-clamp-1">
                {t.hint}
              </div>
            </div>
          );
          return t.href ? (
            <Link key={t.key} href={t.href} className="block">
              {inner}
            </Link>
          ) : (
            <div key={t.key}>{inner}</div>
          );
        })}
      </section>

      {/* 生成流程 — flowchart */}
      <section>
        <div className="mb-md flex items-end justify-between">
          <div>
            <h2 className="font-display text-display-sm text-ink">生成流程</h2>
            <p className="mt-xxs text-caption text-ink-muted-48">
              三阶段 · 八步 — Collect → Analyze → Output
            </p>
          </div>
          <Link href="/reports/new" className="text-caption text-primary hover:underline">
            走一遍 →
          </Link>
        </div>

        <div className="rounded-tile-lg border border-hairline bg-pearl/30 p-lg">
          {FLOW.map((phase, idx) => (
            <div key={phase.id}>
              <PhaseRow phase={phase} />
              {idx < FLOW.length - 1 && <PhaseConnector />}
            </div>
          ))}
        </div>
      </section>

      {/* 最近报告 */}
      <section>
        <div className="mb-md flex items-end justify-between">
          <h2 className="font-display text-display-sm text-ink">最近报告</h2>
          <Link href="/reports" className="text-caption text-primary hover:underline">
            查看全部 →
          </Link>
        </div>

        <div className="overflow-hidden rounded-tile-lg border border-hairline bg-canvas">
          <ul className="divide-y divide-hairline">
            {reports === undefined &&
              Array.from({ length: 4 }).map((_, i) => <SkeletonRow key={i} />)}
            {(reports ?? []).map((r) => (
              <li
                key={r.id}
                className="flex items-center gap-md px-lg py-md transition-colors hover:bg-pearl/40"
              >
                <span className="w-10 text-caption text-ink-muted-48 tabular-nums">
                  #{r.id}
                </span>
                <div className="min-w-0 flex-1">
                  <Link
                    href={`/reports/${r.id}`}
                    className="block truncate text-body-strong text-ink hover:text-primary"
                  >
                    {r.title}
                  </Link>
                  {r.focus_topics?.length > 0 && (
                    <div className="truncate text-caption text-ink-muted-48">
                      {r.focus_topics.join(" · ")}
                    </div>
                  )}
                </div>
                {r.status === "running" ? (
                  <Pulse label="运行中" />
                ) : (
                  <StatusPill status={r.status} />
                )}
                <span className="w-20 text-right text-caption text-ink-muted-80 tabular-nums">
                  ${r.total_cost_usd?.toFixed(3) ?? "0.000"}
                </span>
                <span className="hidden w-44 text-right text-caption text-ink-muted-48 md:block">
                  {new Date(r.created_at).toLocaleString()}
                </span>
              </li>
            ))}
            {reports !== undefined && reports.length === 0 && (
              <li className="px-lg py-xxl text-center text-caption text-ink-muted-48">
                暂无报告 ·{" "}
                <Link href="/reports/new" className="text-primary">
                  新建一个
                </Link>
              </li>
            )}
          </ul>
        </div>
      </section>
    </div>
  );
}
