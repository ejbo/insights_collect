"use client";
import Link from "next/link";
import { use, useMemo, useState } from "react";
import useSWR from "swr";
import { fetcher } from "../../../lib/api";

type EventViewpoint = {
  id: number;
  expert_id: number;
  expert_name: string;
  expert_name_zh?: string | null;
  source_domain?: string | null;
  claim_when?: string | null;
  claim_where?: string | null;
  claim_what?: string | null;
  claim_quote?: string | null;
  claim_medium?: string | null;
  claim_source_url?: string | null;
  claim_why_context?: string | null;
  confidence?: number | null;
};

type EventDetail = {
  id: number;
  name: string;
  kind: string;
  host?: string | null;
  date?: string | null;
  url?: string | null;
  description?: string | null;
  viewpoint_count: number;
  experts: { id: number; name: string; name_zh?: string | null; viewpoint_count: number }[];
  topics: { name: string; count: number }[];
  viewpoints: EventViewpoint[];
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

function fmtDate(d?: string | null): string {
  if (!d) return "—";
  const t = new Date(d).getTime();
  if (Number.isNaN(t)) return "—";
  return new Date(t).toLocaleDateString("zh-CN");
}

export default function EventDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const { data: ev } = useSWR<EventDetail>(`/api/events/${id}`, fetcher);
  const [view, setView] = useState<"timeline" | "expert">("timeline");

  const groupedByExpert = useMemo(() => {
    if (!ev) return [];
    const m = new Map<number, EventViewpoint[]>();
    for (const v of ev.viewpoints) {
      if (!m.has(v.expert_id)) m.set(v.expert_id, []);
      m.get(v.expert_id)!.push(v);
    }
    return Array.from(m.entries())
      .map(([eid, vps]) => ({
        expert: ev.experts.find((e) => e.id === eid)!,
        viewpoints: vps,
      }))
      .sort((a, b) => b.viewpoints.length - a.viewpoints.length);
  }, [ev]);

  if (!ev) {
    return <div className="py-xxl text-center text-caption text-ink-muted-48">加载中…</div>;
  }

  return (
    <div className="space-y-xl">
      <div className="text-caption">
        <Link href="/events" className="text-ink-muted-48 hover:text-primary">
          ← 事件列表
        </Link>
      </div>

      <header className="space-y-sm">
        <div className="flex items-baseline gap-sm">
          <span className="inline-flex items-center rounded-pill bg-parchment px-2 py-0.5 text-caption text-ink-muted-80">
            {KIND_LABEL[ev.kind] || ev.kind}
          </span>
          {ev.date && (
            <span className="text-caption text-ink-muted-48 tabular-nums">
              {fmtDate(ev.date)}
            </span>
          )}
        </div>
        <h1 className="font-display text-display-md text-ink">{ev.name}</h1>
        <div className="text-caption text-ink-muted-80">
          {ev.host && <span>主办：{ev.host}</span>}
          {ev.host && ev.url && <span className="mx-xs text-ink-muted-48">·</span>}
          {ev.url && (
            <a
              href={ev.url}
              target="_blank"
              rel="noreferrer"
              className="text-primary hover:underline break-all"
            >
              ↗ {ev.url}
            </a>
          )}
        </div>
        {ev.description && (
          <p className="text-body text-ink-muted-80">{ev.description}</p>
        )}
      </header>

      <section className="grid grid-cols-3 gap-md">
        <Stat label="收录观点" value={ev.viewpoint_count} />
        <Stat label="参与专家" value={ev.experts.length} />
        <Stat label="覆盖主题" value={ev.topics.length} />
      </section>

      {ev.topics.length > 0 && (
        <section>
          <h3 className="font-display text-tagline text-ink">相关主题</h3>
          <div className="mt-sm flex flex-wrap gap-xxs">
            {ev.topics.map((t) => (
              <span
                key={t.name}
                className="inline-flex items-center rounded-pill bg-pearl px-2.5 py-0.5 text-caption text-ink-muted-80"
              >
                {t.name}
                <span className="ml-1 tabular-nums text-ink-muted-48">×{t.count}</span>
              </span>
            ))}
          </div>
        </section>
      )}

      {ev.experts.length > 0 && (
        <section>
          <h3 className="font-display text-tagline text-ink">参与专家</h3>
          <div className="mt-sm flex flex-wrap gap-xxs">
            {ev.experts.map((e) => (
              <Link
                key={e.id}
                href={`/experts/${e.id}`}
                className="inline-flex items-center rounded-pill bg-parchment px-2.5 py-0.5 text-caption text-ink-muted-80 hover:bg-pearl hover:text-ink"
              >
                {e.name_zh || e.name}
                <span className="ml-1 tabular-nums text-ink-muted-48">×{e.viewpoint_count}</span>
              </Link>
            ))}
          </div>
        </section>
      )}

      <section>
        <header className="mb-sm flex items-baseline justify-between">
          <h3 className="font-display text-tagline text-ink">观点 ({ev.viewpoints.length})</h3>
          <div className="flex gap-xs text-caption">
            <button
              type="button"
              onClick={() => setView("timeline")}
              className={view === "timeline" ? "chip chip-selected" : "chip"}
            >
              时间线
            </button>
            <button
              type="button"
              onClick={() => setView("expert")}
              className={view === "expert" ? "chip chip-selected" : "chip"}
            >
              按专家
            </button>
          </div>
        </header>

        {ev.viewpoints.length === 0 ? (
          <div className="rounded-tile-lg border border-hairline bg-pearl/30 py-xxl text-center text-caption text-ink-muted-48">
            该事件暂无收录观点
          </div>
        ) : view === "timeline" ? (
          <ol className="space-y-md">
            {ev.viewpoints.map((v) => (
              <ViewpointCard key={v.id} v={v} showExpert />
            ))}
          </ol>
        ) : (
          <div className="space-y-lg">
            {groupedByExpert.map(({ expert, viewpoints }) => (
              <div key={expert.id} className="space-y-sm">
                <div className="flex items-baseline gap-sm">
                  <Link
                    href={`/experts/${expert.id}`}
                    className="text-body-strong text-ink hover:text-primary"
                  >
                    {expert.name_zh || expert.name}
                  </Link>
                  <span className="text-caption text-ink-muted-48 tabular-nums">
                    {viewpoints.length} 条观点
                  </span>
                </div>
                <ol className="space-y-md">
                  {viewpoints.map((v) => (
                    <ViewpointCard key={v.id} v={v} />
                  ))}
                </ol>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function ViewpointCard({ v, showExpert = false }: { v: EventViewpoint; showExpert?: boolean }) {
  return (
    <li className="rounded-tile-lg border border-hairline bg-paper p-md transition-colors hover:bg-pearl/40">
      <div className="flex flex-wrap items-baseline gap-x-md gap-y-xxs text-caption text-ink-muted-48">
        {showExpert && (
          <Link
            href={`/experts/${v.expert_id}`}
            className="text-caption-strong text-ink hover:text-primary"
          >
            {v.expert_name_zh || v.expert_name}
          </Link>
        )}
        <span className="tabular-nums">{fmtDate(v.claim_when)}</span>
        {v.claim_where && <span>· {v.claim_where}</span>}
        {v.source_domain && <span className="font-mono">· {v.source_domain}</span>}
        {typeof v.confidence === "number" && (
          <span className="ml-auto tabular-nums">c={v.confidence.toFixed(2)}</span>
        )}
      </div>
      {v.claim_what && <p className="mt-xs text-body text-ink">{v.claim_what}</p>}
      {v.claim_quote && (
        <blockquote className="mt-xs border-l-2 border-primary/40 pl-sm text-body text-ink-muted-80">
          “{v.claim_quote}”
        </blockquote>
      )}
      {v.claim_why_context && (
        <p className="mt-xs text-caption text-ink-muted-80">背景：{v.claim_why_context}</p>
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
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-tile-lg border border-hairline bg-paper p-md">
      <div className="text-caption text-ink-muted-48">{label}</div>
      <div className="mt-xs font-display text-display-md text-ink tabular-nums">{value}</div>
    </div>
  );
}
