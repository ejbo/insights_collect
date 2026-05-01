"use client";
import Link from "next/link";
import { useMemo, useState } from "react";
import useSWR from "swr";
import { fetcher } from "../../lib/api";
import { SkeletonCard } from "../../components/Skeleton";

type ViewpointRow = {
  id: number;
  expert_id: number;
  expert_name: string;
  expert_name_zh?: string | null;
  claim_when?: string | null;
  claim_where?: string | null;
  claim_what: string;
  claim_quote?: string | null;
  claim_medium?: string | null;
  claim_source_url?: string | null;
  claim_lang: string;
  source_domain?: string | null;
  confidence: number;
  ingested_at: string;
};

function fmtDate(d?: string | null): string {
  if (!d) return "—";
  const t = new Date(d).getTime();
  if (Number.isNaN(t)) return "—";
  return new Date(t).toLocaleDateString("zh-CN");
}

export default function ViewpointsPage() {
  const [expertFilter, setExpertFilter] = useState("");
  const [lang, setLang] = useState<"all" | "zh" | "en">("all");
  const url = expertFilter
    ? `/api/viewpoints?expert=${encodeURIComponent(expertFilter)}&limit=300`
    : `/api/viewpoints?limit=300`;
  const { data, isLoading } = useSWR<ViewpointRow[]>(url, fetcher);

  const list = data ?? [];
  const filtered = useMemo(
    () => (lang === "all" ? list : list.filter((v) => v.claim_lang === lang)),
    [list, lang],
  );

  // group by expert
  const byExpert = useMemo(() => {
    const m = new Map<string, { name: string; expert_id: number; rows: ViewpointRow[] }>();
    for (const v of filtered) {
      const key = String(v.expert_id);
      const cur = m.get(key);
      if (cur) cur.rows.push(v);
      else m.set(key, { name: v.expert_name, expert_id: v.expert_id, rows: [v] });
    }
    return Array.from(m.values()).sort((a, b) => b.rows.length - a.rows.length);
  }, [filtered]);

  return (
    <div className="space-y-lg">
      <div className="flex flex-wrap items-center gap-md">
        <div className="flex-1 min-w-[14rem] md:max-w-sm">
          <input
            className="input-pill"
            placeholder="过滤专家姓名"
            value={expertFilter}
            onChange={(e) => setExpertFilter(e.target.value)}
          />
        </div>
        <div className="flex gap-xxs">
          {(["all", "zh", "en"] as const).map((l) => (
            <button
              key={l}
              type="button"
              onClick={() => setLang(l)}
              className={lang === l ? "chip chip-selected" : "chip"}
            >
              {l === "all" ? "全部语言" : l}
            </button>
          ))}
        </div>
        <span className="ml-auto text-caption text-ink-muted-48 tabular-nums">
          {filtered.length} 条 · {byExpert.length} 位专家
        </span>
      </div>

      <div className="space-y-lg">
        {isLoading && byExpert.length === 0 && (
          <>
            <SkeletonCard lines={4} />
            <SkeletonCard lines={3} />
            <SkeletonCard lines={3} />
          </>
        )}
        {byExpert.map((g) => (
          <section key={g.expert_id}>
            <header className="mb-sm flex items-baseline justify-between">
              <Link
                href={`/experts/${g.expert_id}`}
                className="font-display text-tagline text-ink hover:text-primary"
              >
                {g.name}
                <span className="ml-xs text-caption text-ink-muted-48 tabular-nums">
                  ({g.rows.length})
                </span>
              </Link>
              <Link
                href={`/experts/${g.expert_id}`}
                className="text-caption text-primary hover:underline"
              >
                查看全部 →
              </Link>
            </header>
            <ul className="space-y-sm">
              {g.rows.slice(0, 5).map((v) => (
                <li
                  key={v.id}
                  className="rounded-tile-lg border border-hairline bg-paper p-md transition-colors hover:bg-pearl/40"
                >
                  <div className="flex flex-wrap items-baseline gap-x-md gap-y-xxs text-caption text-ink-muted-48">
                    <span className="tabular-nums">{fmtDate(v.claim_when)}</span>
                    {v.claim_where && <span>· {v.claim_where}</span>}
                    {v.claim_medium && <span>· {v.claim_medium}</span>}
                    {v.source_domain && <span className="font-mono">· {v.source_domain}</span>}
                    {typeof v.confidence === "number" && (
                      <span className="ml-auto tabular-nums">c={v.confidence.toFixed(2)}</span>
                    )}
                  </div>
                  <p className="mt-xs text-body text-ink">{v.claim_what}</p>
                  {v.claim_quote && (
                    <blockquote className="mt-xs border-l-2 border-primary/40 pl-sm text-body text-ink-muted-80">
                      “{v.claim_quote}”
                    </blockquote>
                  )}
                  {v.claim_source_url && (
                    <a
                      href={v.claim_source_url}
                      target="_blank"
                      rel="noreferrer"
                      className="mt-xs inline-block break-all text-caption text-primary hover:underline"
                    >
                      ↗ {v.claim_source_url}
                    </a>
                  )}
                </li>
              ))}
            </ul>
            {g.rows.length > 5 && (
              <div className="mt-xs text-caption text-ink-muted-48">
                还有 {g.rows.length - 5} 条 ·{" "}
                <Link href={`/experts/${g.expert_id}`} className="text-primary hover:underline">
                  全部查看
                </Link>
              </div>
            )}
          </section>
        ))}
        {byExpert.length === 0 && (
          <div className="rounded-tile-lg border border-hairline bg-pearl/30 py-xxl text-center text-caption text-ink-muted-48">
            暂无观点
          </div>
        )}
      </div>
    </div>
  );
}
