"use client";
import Link from "next/link";
import useSWR from "swr";
import { useState } from "react";
import { fetcher } from "../../lib/api";
import { SkeletonRow } from "../../components/Skeleton";
import type { ExpertSummary } from "../../lib/types";

type Sort = "viewpoints" | "recent" | "name";

const SORTS: { id: Sort; label: string }[] = [
  { id: "viewpoints", label: "按观点数" },
  { id: "recent", label: "按最近发声" },
  { id: "name", label: "按姓名" },
];

function formatDate(d?: string | null): string {
  if (!d) return "—";
  const t = new Date(d).getTime();
  if (Number.isNaN(t)) return "—";
  return new Date(t).toLocaleDateString("zh-CN");
}

export default function ExpertsPage() {
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<Sort>("viewpoints");
  const { data, isLoading } = useSWR<ExpertSummary[]>(
    `/api/experts?q=${encodeURIComponent(q)}&sort=${sort}&limit=200`,
    fetcher,
  );

  const list = data ?? [];

  return (
    <div className="space-y-lg">
      <div className="flex flex-wrap items-end gap-md">
        <div className="flex-1 min-w-[12rem] md:max-w-sm">
          <input
            className="input-pill"
            placeholder="搜索姓名"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        <div className="flex gap-xxs">
          {SORTS.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => setSort(s.id)}
              className={sort === s.id ? "chip chip-selected" : "chip"}
            >
              {s.label}
            </button>
          ))}
        </div>
        <span className="ml-auto text-caption text-ink-muted-48 tabular-nums">
          {isLoading ? "加载中…" : `共 ${list.length} 位`}
        </span>
      </div>

      <div className="overflow-hidden rounded-tile-lg border border-hairline bg-paper">
        <table className="w-full text-caption">
          <thead className="bg-pearl text-ink-muted-48">
            <tr>
              <th className="px-md py-sm text-left">#</th>
              <th className="px-md py-sm text-left">姓名</th>
              <th className="px-md py-sm text-left">所属 / 角色</th>
              <th className="px-md py-sm text-right tabular-nums">观点数</th>
              <th className="px-md py-sm text-right">最近发声</th>
            </tr>
          </thead>
          <tbody>
            {isLoading &&
              Array.from({ length: 5 }).map((_, i) => (
                <tr key={`skel-${i}`}>
                  <td colSpan={5}><SkeletonRow cols={5} /></td>
                </tr>
              ))}
            {list.map((e, i) => (
              <tr
                key={e.id}
                className="border-t border-hairline transition-colors hover:bg-pearl/60"
              >
                <td className="px-md py-sm text-ink-muted-48 tabular-nums">{i + 1}</td>
                <td className="px-md py-sm">
                  <Link
                    href={`/experts/${e.id}`}
                    className="text-body-strong text-ink hover:text-primary"
                  >
                    {e.name}
                  </Link>
                  {e.name_zh && e.name_zh !== e.name && (
                    <span className="ml-xs text-caption text-ink-muted-48">{e.name_zh}</span>
                  )}
                </td>
                <td className="px-md py-sm">
                  {e.affiliations && e.affiliations.length > 0 ? (
                    <div className="flex flex-wrap gap-xxs">
                      {e.affiliations.slice(0, 3).map((a) => (
                        <span
                          key={a}
                          className="inline-flex items-center rounded-pill bg-parchment px-2 py-0.5 text-caption text-ink-muted-80"
                        >
                          {a}
                        </span>
                      ))}
                    </div>
                  ) : e.bio ? (
                    <span className="text-caption text-ink-muted-80 line-clamp-1">{e.bio}</span>
                  ) : (
                    <span className="text-caption text-ink-muted-48">—</span>
                  )}
                </td>
                <td className="px-md py-sm text-right tabular-nums">
                  {e.viewpoint_count > 0 ? (
                    <span className="text-caption-strong text-ink">{e.viewpoint_count}</span>
                  ) : (
                    <span className="text-ink-muted-48">0</span>
                  )}
                </td>
                <td className="px-md py-sm text-right text-caption text-ink-muted-80 tabular-nums">
                  {formatDate(e.last_claim_at)}
                </td>
              </tr>
            ))}
            {list.length === 0 && !isLoading && (
              <tr>
                <td colSpan={5} className="px-md py-xxl text-center text-caption text-ink-muted-48">
                  暂无专家
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
