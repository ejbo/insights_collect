"use client";
import useSWR from "swr";
import { useMemo, useState } from "react";
import { fetcher } from "../lib/api";

type ReportViewpoint = {
  id: number;
  expert_id: number;
  expert_name: string;
  expert_name_zh?: string | null;
  expert_role?: string | null;
  expert_affiliations?: string[] | null;
  expert_profile_urls?: string[] | null;
  claim_who_role?: string | null;
  claim_when?: string | null;
  claim_where?: string | null;
  claim_what: string;
  claim_quote?: string | null;
  claim_medium?: string | null;
  claim_source_url?: string | null;
  claim_why_context?: string | null;
  claim_lang: string;
  confidence: number;
  source_domain?: string | null;
  topics: string[];
};

const QUOTE_MAX = 320;

function summarize(text: string, max = QUOTE_MAX): string {
  if (!text) return "";
  if (text.length <= max) return text;
  return text.slice(0, max).trimEnd() + "…";
}

function formatDate(s: string | null | undefined): string {
  if (!s) return "时间未知";
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return "时间未知";
  return d.toISOString().slice(0, 10);
}

function slugify(s: string): string {
  return s.replace(/[^A-Za-z0-9_一-鿿]+/g, "-").replace(/^-|-$/g, "").toLowerCase();
}

export function ExpertQuotesView({ reportId, focusTopics }: { reportId: number; focusTopics: string[] }) {
  const { data, isLoading } = useSWR<ReportViewpoint[]>(
    `/api/reports/${reportId}/viewpoints`,
    fetcher,
    { refreshInterval: 5000 },
  );

  const [minConfidence, setMinConfidence] = useState(0.5);
  const [groupBy, setGroupBy] = useState<"topic" | "expert">("topic");
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set());

  const all = data || [];

  const filtered = useMemo(
    () => all.filter((v) => (v.confidence ?? 0) >= minConfidence),
    [all, minConfidence],
  );

  // Group: topic → expert → viewpoints[], or expert → viewpoints[]
  const grouped = useMemo(() => {
    const out = new Map<string, Map<string, ReportViewpoint[]>>();
    if (groupBy === "topic") {
      for (const v of filtered) {
        const topics = v.topics?.length ? v.topics : ["未分类"];
        for (const t of topics) {
          if (!out.has(t)) out.set(t, new Map());
          const expertMap = out.get(t)!;
          const key = v.expert_name_zh || v.expert_name;
          if (!expertMap.has(key)) expertMap.set(key, []);
          expertMap.get(key)!.push(v);
        }
      }
      // Sort topics by report focus order, then alphabetically
      const orderedKeys = [
        ...focusTopics.filter((t) => out.has(t)),
        ...[...out.keys()].filter((t) => !focusTopics.includes(t)).sort(),
      ];
      const sorted = new Map<string, Map<string, ReportViewpoint[]>>();
      for (const k of orderedKeys) sorted.set(k, out.get(k)!);
      return sorted;
    }
    // group by expert directly
    const byExpert = new Map<string, ReportViewpoint[]>();
    for (const v of filtered) {
      const key = v.expert_name_zh || v.expert_name;
      if (!byExpert.has(key)) byExpert.set(key, []);
      byExpert.get(key)!.push(v);
    }
    const sortedExperts = [...byExpert.entries()].sort(
      (a, b) => b[1].length - a[1].length,
    );
    const wrap = new Map<string, Map<string, ReportViewpoint[]>>();
    wrap.set("全部专家", new Map(sortedExperts));
    return wrap;
  }, [filtered, groupBy, focusTopics]);

  const toc = useMemo(() => {
    const items: { id: string; label: string; count: number; depth: 0 | 1 }[] = [];
    for (const [topic, expertMap] of grouped) {
      const total = [...expertMap.values()].reduce((s, arr) => s + arr.length, 0);
      items.push({ id: `g-${slugify(topic)}`, label: topic, count: total, depth: 0 });
      for (const [expert, vps] of expertMap) {
        items.push({
          id: `g-${slugify(topic)}-${slugify(expert)}`,
          label: expert,
          count: vps.length,
          depth: 1,
        });
      }
    }
    return items;
  }, [grouped]);

  function toggleExpanded(id: number) {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  if (isLoading && all.length === 0) {
    return (
      <div className="card-utility py-xxl text-center text-caption text-ink-muted-48">
        加载专家言论中…
      </div>
    );
  }
  if (all.length === 0) {
    return (
      <div className="card-utility py-xxl text-center text-caption text-ink-muted-48">
        本报告暂未抽取到专家言论。
      </div>
    );
  }

  const counts = {
    total: all.length,
    afterFilter: filtered.length,
    experts: new Set(filtered.map((v) => v.expert_id)).size,
  };

  return (
    <div className="grid grid-cols-1 gap-lg lg:grid-cols-[220px_1fr]">
      {/* Side TOC */}
      <aside className="lg:sticky lg:top-md lg:self-start">
        <div className="card-utility">
          <h3 className="font-display text-tagline text-ink">目录</h3>
          <p className="mt-xxs text-caption text-ink-muted-48 tabular-nums">
            {counts.afterFilter}/{counts.total} 条 · {counts.experts} 位专家
          </p>
          <nav className="mt-md max-h-[70vh] space-y-xxs overflow-auto pr-xs">
            {toc.map((t) => (
              <a
                key={t.id}
                href={`#${t.id}`}
                className={
                  "block truncate rounded px-xs py-xxs text-caption hover:bg-pearl " +
                  (t.depth === 0 ? "text-caption-strong text-ink" : "ml-md text-ink-muted-80")
                }
              >
                {t.label}
                <span className="ml-xs text-ink-muted-48 tabular-nums">{t.count}</span>
              </a>
            ))}
          </nav>
        </div>
      </aside>

      <div className="space-y-lg">
        {/* Controls */}
        <div className="card-utility flex flex-wrap items-center gap-md">
          <div className="flex items-center gap-xs">
            <span className="text-caption-strong text-ink">分组</span>
            <button
              type="button"
              onClick={() => setGroupBy("topic")}
              className={groupBy === "topic" ? "chip chip-selected" : "chip"}
            >
              按主题
            </button>
            <button
              type="button"
              onClick={() => setGroupBy("expert")}
              className={groupBy === "expert" ? "chip chip-selected" : "chip"}
            >
              按专家
            </button>
          </div>
          <div className="flex flex-1 items-center gap-xs min-w-[220px]">
            <span className="text-caption-strong text-ink whitespace-nowrap">
              质量阈值 {minConfidence.toFixed(2)}
            </span>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={minConfidence}
              onChange={(e) => setMinConfidence(Number(e.target.value))}
              className="flex-1 accent-primary"
            />
            <span className="text-caption text-ink-muted-48 tabular-nums whitespace-nowrap">
              保留 {counts.afterFilter}
            </span>
          </div>
        </div>

        {/* Groups */}
        {[...grouped.entries()].map(([topic, expertMap]) => {
          const topicId = `g-${slugify(topic)}`;
          const topicTotal = [...expertMap.values()].reduce((s, arr) => s + arr.length, 0);
          return (
            <section key={topic} id={topicId} className="space-y-md scroll-mt-lg">
              <div className="flex items-baseline gap-sm border-b border-hairline pb-xs">
                <h2 className="font-display text-tagline-lg text-ink">{topic}</h2>
                <span className="text-caption text-ink-muted-48 tabular-nums">
                  {topicTotal} 条 · {expertMap.size} 位专家
                </span>
              </div>
              {[...expertMap.entries()].map(([expert, vps]) => {
                const expertId = `${topicId}-${slugify(expert)}`;
                const sample = vps[0];
                return (
                  <div key={expertId} id={expertId} className="card-utility space-y-sm scroll-mt-lg">
                    <header className="flex flex-wrap items-baseline gap-x-sm gap-y-xxs">
                      <h3 className="font-display text-tagline text-ink">{expert}</h3>
                      {sample.expert_role && (
                        <span className="text-caption text-ink-muted-80">
                          {sample.expert_role}
                        </span>
                      )}
                      {sample.expert_affiliations?.length ? (
                        <span className="text-caption text-ink-muted-48">
                          · {sample.expert_affiliations.slice(0, 2).join(" / ")}
                        </span>
                      ) : null}
                      <span className="ml-auto text-caption text-ink-muted-48 tabular-nums">
                        {vps.length} 条
                      </span>
                    </header>
                    <ul className="space-y-sm">
                      {vps.map((v) => {
                        const isExpanded = expandedIds.has(v.id);
                        const fullQuote = v.claim_quote || v.claim_what;
                        const showSummary = fullQuote.length > QUOTE_MAX && !isExpanded;
                        return (
                          <li
                            key={v.id}
                            className="rounded-tile-lg border border-hairline bg-pearl/40 p-sm space-y-xxs"
                          >
                            <div className="flex flex-wrap items-baseline gap-x-xs gap-y-xxs text-caption">
                              <span className="text-caption-strong text-ink">
                                {formatDate(v.claim_when)}
                              </span>
                              {v.claim_where && (
                                <span className="text-ink-muted-80">@ {v.claim_where}</span>
                              )}
                              {v.claim_medium && v.claim_medium !== v.claim_where && (
                                <span className="text-ink-muted-48">· {v.claim_medium}</span>
                              )}
                              <span
                                className="ml-auto rounded border border-hairline px-xxs tabular-nums"
                                title="confidence"
                              >
                                conf {v.confidence?.toFixed(2)}
                              </span>
                            </div>
                            <blockquote className="border-l-2 border-primary/40 pl-sm text-body text-ink">
                              {showSummary ? summarize(fullQuote) : fullQuote}
                            </blockquote>
                            {fullQuote.length > QUOTE_MAX && (
                              <button
                                type="button"
                                onClick={() => toggleExpanded(v.id)}
                                className="text-caption text-primary hover:underline"
                              >
                                {isExpanded ? "收起原文" : "展开原文"}
                              </button>
                            )}
                            {v.claim_quote && v.claim_what && v.claim_quote !== v.claim_what && (
                              <p className="text-caption text-ink-muted-80">
                                <span className="text-caption-strong text-ink">摘要：</span>
                                {v.claim_what}
                              </p>
                            )}
                            {v.claim_why_context && (
                              <p className="rounded border border-primary/20 bg-primary/5 p-xs text-caption text-ink">
                                <span className="text-caption-strong">解读：</span>{" "}
                                {v.claim_why_context}
                              </p>
                            )}
                            <div className="flex flex-wrap items-center gap-xs text-caption text-ink-muted-48">
                              {v.source_domain && (
                                <span className="rounded border border-hairline px-xxs">
                                  {v.source_domain}
                                </span>
                              )}
                              {v.topics?.map((t) => (
                                <span
                                  key={t}
                                  className="rounded bg-primary/10 px-xxs text-primary"
                                >
                                  #{t}
                                </span>
                              ))}
                              {v.claim_source_url && (
                                <a
                                  href={v.claim_source_url}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="ml-auto text-primary hover:underline"
                                >
                                  打开原文 ↗
                                </a>
                              )}
                            </div>
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                );
              })}
            </section>
          );
        })}
      </div>
    </div>
  );
}
