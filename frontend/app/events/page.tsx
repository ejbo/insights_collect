"use client";
import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";
import { api, fetcher } from "../../lib/api";

type Event = {
  id: number;
  name: string;
  kind: string;
  host?: string | null;
  url?: string | null;
  description?: string | null;
  viewpoint_count: number;
};

const KIND_LABEL: Record<string, string> = {
  forum: "论坛",
  interview: "采访",
  podcast: "播客",
  keynote: "演讲",
  paper: "论文",
  article: "文章",
  blog: "博客",
  other: "其他",
};

export default function EventsPage() {
  const { data, mutate } = useSWR<Event[]>("/api/events?limit=300", fetcher);
  const [kind, setKind] = useState<string>("all");
  const [curating, setCurating] = useState(false);
  const [lastResult, setLastResult] = useState<string | null>(null);

  const list = data ?? [];
  const kinds = Array.from(new Set(list.map((e) => e.kind)));
  const filtered = kind === "all" ? list : list.filter((e) => e.kind === kind);

  async function curate() {
    if (!confirm("将由主模型逐条审核所有事件，删除「研究报告」等通用类型，合并跨报告重复。确认运行？")) return;
    setCurating(true);
    setLastResult(null);
    try {
      const res = await api<any>("/api/events/curate-now", { method: "POST" });
      setLastResult(
        `共审核 ${res.events_considered} · 删 ${res.deleted ?? 0} · 合并 ${res.merged ?? 0} · ` +
        `保留 ${res.kept ?? 0}（补全 ${res.enriched ?? 0}）`,
      );
      await mutate();
    } catch (e: any) {
      setLastResult(`清理失败：${e?.message || e}`);
    } finally {
      setCurating(false);
    }
  }

  return (
    <div className="space-y-md">
      <div className="flex flex-wrap items-center gap-xs">
        <button
          type="button"
          onClick={() => setKind("all")}
          className={kind === "all" ? "chip chip-selected" : "chip"}
        >
          全部 ({list.length})
        </button>
        {kinds.map((k) => {
          const n = list.filter((e) => e.kind === k).length;
          return (
            <button
              key={k}
              type="button"
              onClick={() => setKind(k)}
              className={kind === k ? "chip chip-selected" : "chip"}
            >
              {KIND_LABEL[k] || k} ({n})
            </button>
          );
        })}
        <span className="ml-auto text-caption text-ink-muted-48 tabular-nums">
          按引用数排序
        </span>
        <button
          type="button"
          disabled={curating}
          onClick={curate}
          className="btn-secondary-pill"
          title="主模型审核：删通用类型 / 合并跨报告重复"
        >
          {curating ? "清理中…" : "立即清理事件"}
        </button>
      </div>

      {lastResult && (
        <div className="rounded-sm border border-hairline bg-pearl/60 px-md py-xs text-caption text-ink-muted-80">
          {lastResult}
        </div>
      )}

      <div className="overflow-hidden rounded-tile-lg border border-hairline bg-paper">
        <table className="w-full text-caption">
          <thead className="bg-pearl text-ink-muted-48">
            <tr>
              <th className="px-md py-sm text-left">名称</th>
              <th className="px-md py-sm text-left">主办</th>
              <th className="px-md py-sm text-left">类型</th>
              <th className="px-md py-sm text-right tabular-nums">观点引用</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((e) => (
              <tr
                key={e.id}
                className="border-t border-hairline transition-colors hover:bg-pearl/40"
              >
                <td className="px-md py-sm">
                  <Link
                    href={`/events/${e.id}`}
                    className="text-body-strong text-ink hover:text-primary"
                  >
                    {e.name}
                  </Link>
                  {e.url && (
                    <a
                      href={e.url}
                      target="_blank"
                      rel="noreferrer"
                      onClick={(ev) => ev.stopPropagation()}
                      className="ml-xs text-caption text-ink-muted-48 hover:text-primary"
                    >
                      ↗
                    </a>
                  )}
                  {e.description && (
                    <p className="mt-xxs text-caption text-ink-muted-80 line-clamp-2">
                      {e.description}
                    </p>
                  )}
                </td>
                <td className="px-md py-sm text-ink-muted-80">{e.host || "—"}</td>
                <td className="px-md py-sm">
                  <span className="inline-flex items-center rounded-pill bg-parchment px-2 py-0.5 text-caption text-ink-muted-80">
                    {KIND_LABEL[e.kind] || e.kind}
                  </span>
                </td>
                <td className="px-md py-sm text-right tabular-nums">
                  {e.viewpoint_count > 0 ? (
                    <span className="text-caption-strong text-ink">
                      {e.viewpoint_count}
                    </span>
                  ) : (
                    <span className="text-ink-muted-48">0</span>
                  )}
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={4} className="px-md py-xxl text-center text-caption text-ink-muted-48">
                  暂无事件
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
