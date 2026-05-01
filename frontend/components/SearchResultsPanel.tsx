"use client";
import useSWR from "swr";
import { useMemo, useState } from "react";
import { fetcher } from "../lib/api";
import type { SearchHit } from "../lib/types";

const KIND_LABEL: Record<SearchHit["kind"], string> = {
  web_search: "🔎 search",
  web_fetch: "📄 fetch",
  citation: "❝ cite",
  x_post: "𝕏 post",
};

const KIND_COLOR: Record<SearchHit["kind"], string> = {
  web_search: "bg-primary/10 text-primary",
  web_fetch: "bg-status-success/10 text-status-success",
  citation: "bg-parchment text-ink-muted-80",
  x_post: "bg-ink/10 text-ink",
};

const MEDIA_LABEL: Record<NonNullable<NonNullable<SearchHit["extra"]>["media_type"]>, string> = {
  video: "🎬 视频",
  image: "🖼 图片",
  text: "",
};

function parseUtc(s: string): number {
  // FastAPI serializes naive `datetime.utcnow()` as "2026-04-30T12:00:00"
  // (no timezone). new Date(...) would treat that as local time — so when
  // the viewer is +08:00 the "diff" goes negative and our age clamp pins
  // every row to "1s 前". Force UTC by appending Z when no tz info present.
  const hasTz = /(Z|[+-]\d\d:?\d\d)$/.test(s);
  return new Date(hasTz ? s : s + "Z").getTime();
}

function formatTime(s: string): string {
  const t = parseUtc(s);
  if (Number.isNaN(t)) return "";
  const diff = Math.max(0, Date.now() - t);
  if (diff < 60_000) return diff < 1500 ? "刚刚" : `${Math.floor(diff / 1000)}s 前`;
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m 前`;
  return new Date(t).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

export function SearchResultsPanel({ reportId }: { reportId: number }) {
  const { data } = useSWR<SearchHit[]>(
    `/api/reports/${reportId}/search-results`,
    fetcher,
    { refreshInterval: 3000 },
  );
  const [providerFilter, setProviderFilter] = useState<string>("all");

  const hits = data || [];
  const providers = Array.from(new Set(hits.map((h) => h.provider))).sort();
  const providerCounts = providers.reduce<Record<string, number>>((acc, p) => {
    acc[p] = hits.filter((h) => h.provider === p).length;
    return acc;
  }, {});
  const filtered =
    providerFilter === "all" ? hits : hits.filter((h) => h.provider === providerFilter);

  const lastHitAt = useMemo(() => {
    if (hits.length === 0) return null;
    return hits.reduce(
      (max, h) => (max && new Date(max).getTime() > new Date(h.created_at).getTime() ? max : h.created_at),
      hits[0].created_at,
    );
  }, [hits]);

  return (
    <div className="card-utility">
      <div className="flex items-baseline justify-between">
        <h3 className="font-display text-tagline text-ink">Search results</h3>
        <span className="text-caption text-ink-muted-48 tabular-nums">
          {hits.length} hits
          {lastHitAt && (
            <span className="ml-xs text-ink-muted-48">· 最近 {formatTime(lastHitAt)}</span>
          )}
        </span>
      </div>

      {/* Filters — only by provider */}
      <div className="mt-sm flex flex-wrap gap-xs text-caption">
        <button
          type="button"
          onClick={() => setProviderFilter("all")}
          className={providerFilter === "all" ? "chip chip-selected" : "chip"}
        >
          all ({hits.length})
        </button>
        {providers.map((p) => (
          <button
            key={p}
            type="button"
            onClick={() => setProviderFilter(p)}
            className={providerFilter === p ? "chip chip-selected" : "chip"}
          >
            {p} ({providerCounts[p]})
          </button>
        ))}
      </div>

      {/* List */}
      <ul className="mt-md max-h-[640px] space-y-sm overflow-auto">
        {filtered.map((h) => (
          <li key={h.id} className="border-b border-hairline pb-sm last:border-0">
            <div className="flex flex-wrap items-baseline gap-x-xs gap-y-xxs">
              <span className={`status-pill ${KIND_COLOR[h.kind]}`}>
                {KIND_LABEL[h.kind]}
              </span>
              {h.extra?.media_type && h.extra.media_type !== "text" && (
                <span className="status-pill bg-status-warning/15 text-ink">
                  {MEDIA_LABEL[h.extra.media_type]}
                </span>
              )}
              <span className="text-caption text-ink-muted-48 tabular-nums">
                {h.provider}
              </span>
              {h.source_domain && (
                <span className="text-caption text-ink-muted-48">
                  · {h.source_domain}
                </span>
              )}
              {h.page_age && (
                <span className="text-caption text-ink-muted-48">
                  · {h.page_age}
                </span>
              )}
              <span className="ml-auto text-caption text-ink-muted-48 tabular-nums">
                {formatTime(h.created_at)}
              </span>
            </div>
            <div className="mt-xxs">
              {h.url ? (
                <a
                  href={h.url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-body-strong text-primary hover:underline"
                >
                  {h.title || h.url}
                </a>
              ) : (
                <span className="text-body-strong text-ink">
                  {h.title || "(no title)"}
                </span>
              )}
            </div>
            {h.query && (
              <div className="mt-xxs text-caption text-ink-muted-48">
                <span className="text-caption-strong">query:</span>{" "}
                <span className="font-mono">{h.query}</span>
              </div>
            )}
            {h.snippet && (
              <p className="mt-xxs text-caption text-ink-muted-80 line-clamp-3">
                {h.snippet}
              </p>
            )}
          </li>
        ))}
        {filtered.length === 0 && (
          <li className="py-md text-center text-caption text-ink-muted-48">
            {hits.length === 0
              ? "尚无搜索结果 — provider 的 web_search 调用会在这里实时出现。"
              : "当前筛选下无结果。"}
          </li>
        )}
      </ul>
    </div>
  );
}
