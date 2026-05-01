"use client";
import { useState } from "react";
import useSWR from "swr";
import Link from "next/link";
import { api, fetcher } from "../../lib/api";
import { Pulse, SkeletonRow } from "../../components/Skeleton";
import type { Report } from "../../lib/types";

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

export default function ReportsList() {
  const { data, mutate } = useSWR<Report[]>("/api/reports?limit=100", fetcher, {
    refreshInterval: 3000,
  });
  const [busy, setBusy] = useState<{ id: number; op: "cancel" | "delete" } | null>(null);

  async function cancel(id: number) {
    if (!confirm(`确认中止报告 #${id}？`)) return;
    setBusy({ id, op: "cancel" });
    try {
      await api(`/api/reports/${id}/cancel`, { method: "POST" });
      await mutate();
    } finally {
      setBusy(null);
    }
  }

  async function remove(id: number, title: string) {
    if (!confirm(`确认删除报告 #${id}「${title}」？\n该操作会同时清理所有 search results / agent runs / provider calls 和文件。`)) return;
    setBusy({ id, op: "delete" });
    try {
      await api(`/api/reports/${id}`, { method: "DELETE" });
      await mutate();
    } finally {
      setBusy(null);
    }
  }

  const list = data ?? [];

  return (
    <div className="surface-card overflow-hidden">
      <ul className="divide-y divide-hairline">
        {data === undefined &&
          Array.from({ length: 6 }).map((_, i) => <SkeletonRow key={i} cols={5} />)}
        {list.map((r) => {
          const isLive = r.status === "running" || r.status === "pending";
          const isBusyCancel = busy?.id === r.id && busy?.op === "cancel";
          const isBusyDelete = busy?.id === r.id && busy?.op === "delete";
          return (
            <li
              key={r.id}
              className="group flex items-center gap-md px-lg py-md transition-colors hover:bg-pearl/40"
            >
              <span className="w-12 text-caption text-ink-muted-48 tabular-nums">
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
                <span className={STATUS_CLASS[r.status]}>{STATUS_LABEL[r.status]}</span>
              )}
              <span className="w-24 text-right text-caption text-ink-muted-80 tabular-nums">
                ${r.total_cost_usd?.toFixed(3) ?? "0.000"}
              </span>
              <span className="hidden w-44 text-right text-caption text-ink-muted-48 md:block">
                {new Date(r.created_at).toLocaleString()}
              </span>
              <div className="flex items-center gap-xxs">
                {isLive && (
                  <button
                    type="button"
                    onClick={() => cancel(r.id)}
                    disabled={isBusyCancel}
                    className="btn-pearl !py-1 !px-3 text-caption-strong !border-status-danger/40 !text-status-danger"
                    title="中止这份报告"
                  >
                    {isBusyCancel ? "…" : "中止"}
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => remove(r.id, r.title)}
                  disabled={isBusyDelete}
                  className="rounded-md p-1.5 text-ink-muted-48 opacity-0 transition-all hover:bg-status-danger/10 hover:text-status-danger group-hover:opacity-100 disabled:opacity-100"
                  title="删除报告"
                  aria-label="删除报告"
                >
                  {isBusyDelete ? (
                    <span className="block h-4 w-4 text-caption">…</span>
                  ) : (
                    <TrashIcon />
                  )}
                </button>
              </div>
            </li>
          );
        })}
        {data !== undefined && list.length === 0 && (
          <li className="px-lg py-xxl text-center text-caption text-ink-muted-48">
            暂无报告 ·{" "}
            <Link href="/reports/new" className="text-primary">
              新建一个
            </Link>
          </li>
        )}
      </ul>
    </div>
  );
}

function TrashIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M3 6h18" />
      <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
      <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
      <path d="M10 11v6" />
      <path d="M14 11v6" />
    </svg>
  );
}
