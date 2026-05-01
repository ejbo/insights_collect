"use client";
import { use, useEffect, useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { api, fetcher } from "../../../lib/api";
import type { ExpertDetail, ExpertViewpoint } from "../../../lib/types";

function fmtDate(d?: string | null): string {
  if (!d) return "—";
  const t = new Date(d).getTime();
  if (Number.isNaN(t)) return "—";
  return new Date(t).toLocaleDateString("zh-CN");
}

type EditableLine = {
  active: boolean;
  draft: string;
};

function EditableField({
  label,
  value,
  multiline = false,
  placeholder,
  onSave,
}: {
  label: string;
  value: string;
  multiline?: boolean;
  placeholder?: string;
  onSave: (next: string) => Promise<void>;
}) {
  const [state, setState] = useState<EditableLine>({ active: false, draft: value });
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!state.active) setState({ active: false, draft: value });
  }, [value, state.active]);

  if (!state.active) {
    return (
      <button
        type="button"
        onClick={() => setState({ active: true, draft: value })}
        className="group block w-full text-left transition-colors hover:bg-pearl/60 rounded-sm px-2 -mx-2 py-1"
      >
        <div className="text-caption text-ink-muted-48">{label}</div>
        <div className={`mt-xxs ${value ? "text-body text-ink" : "text-body text-ink-muted-48"}`}>
          {value || placeholder || "—"}
          <span className="ml-xs text-caption text-ink-muted-48 opacity-0 transition-opacity group-hover:opacity-100">
            ✎ 编辑
          </span>
        </div>
      </button>
    );
  }

  const Input = multiline ? "textarea" : "input";
  return (
    <div>
      <div className="text-caption text-ink-muted-48">{label}</div>
      <div className="mt-xxs flex gap-xs">
        <Input
          className={multiline ? "textarea-flat min-h-20 flex-1" : "input-flat flex-1"}
          autoFocus
          placeholder={placeholder}
          value={state.draft}
          onChange={(e: any) => setState({ active: true, draft: e.target.value })}
        />
        <div className="flex gap-xxs">
          <button
            type="button"
            disabled={busy || state.draft === value}
            onClick={async () => {
              setBusy(true);
              try {
                await onSave(state.draft);
                setState({ active: false, draft: state.draft });
              } finally {
                setBusy(false);
              }
            }}
            className="btn-primary !px-3 !py-1 text-caption-strong"
          >
            {busy ? "…" : "保存"}
          </button>
          <button
            type="button"
            onClick={() => setState({ active: false, draft: value })}
            className="btn-pearl !px-3 !py-1 text-caption-strong"
          >
            取消
          </button>
        </div>
      </div>
    </div>
  );
}

function ListEditor({
  label,
  values,
  onSave,
}: {
  label: string;
  values: string[] | null | undefined;
  onSave: (next: string[]) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState((values || []).join("\n"));
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!editing) setDraft((values || []).join("\n"));
  }, [values, editing]);

  if (!editing) {
    return (
      <button
        type="button"
        onClick={() => setEditing(true)}
        className="group block w-full text-left transition-colors hover:bg-pearl/60 rounded-sm px-2 -mx-2 py-1"
      >
        <div className="text-caption text-ink-muted-48">{label}</div>
        <div className="mt-xxs flex flex-wrap gap-xxs">
          {(values || []).length === 0 ? (
            <span className="text-body text-ink-muted-48">—</span>
          ) : (
            (values || []).map((v) => (
              <span
                key={v}
                className="inline-flex items-center rounded-pill bg-parchment px-2 py-0.5 text-caption text-ink-muted-80"
              >
                {v}
              </span>
            ))
          )}
          <span className="ml-xs text-caption text-ink-muted-48 opacity-0 transition-opacity group-hover:opacity-100">
            ✎ 编辑
          </span>
        </div>
      </button>
    );
  }

  return (
    <div>
      <div className="text-caption text-ink-muted-48">{label}（每行一个）</div>
      <textarea
        className="textarea-flat mt-xxs min-h-20"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
      />
      <div className="mt-xxs flex gap-xxs">
        <button
          type="button"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              const next = draft
                .split(/[\n,，]/)
                .map((s) => s.trim())
                .filter(Boolean);
              await onSave(next);
              setEditing(false);
            } finally {
              setBusy(false);
            }
          }}
          className="btn-primary !px-3 !py-1 text-caption-strong"
        >
          {busy ? "…" : "保存"}
        </button>
        <button
          type="button"
          onClick={() => setEditing(false)}
          className="btn-pearl !px-3 !py-1 text-caption-strong"
        >
          取消
        </button>
      </div>
    </div>
  );
}

export default function ExpertDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const { data: expert, mutate: mutateExpert } = useSWR<ExpertDetail>(
    `/api/experts/${id}`,
    fetcher,
  );
  const { data: viewpoints } = useSWR<ExpertViewpoint[]>(
    `/api/experts/${id}/viewpoints`,
    fetcher,
  );

  if (!expert) {
    return <div className="py-xxl text-center text-caption text-ink-muted-48">加载中…</div>;
  }

  async function patch(payload: Record<string, any>) {
    await api(`/api/experts/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    await mutateExpert();
  }

  const vps = viewpoints || [];

  return (
    <div className="space-y-xl">
      <div className="text-caption">
        <Link href="/experts" className="text-ink-muted-48 hover:text-primary">
          ← 专家列表
        </Link>
      </div>

      <header className="space-y-md">
        <EditableField
          label="姓名 / Name"
          value={expert.name}
          placeholder="必填"
          onSave={(v) => patch({ name: v.trim() })}
        />
        <div className="grid grid-cols-1 gap-md md:grid-cols-2">
          <EditableField
            label="中文名"
            value={expert.name_zh || ""}
            onSave={(v) => patch({ name_zh: v.trim() || null })}
          />
          <EditableField
            label="角色 / 简介"
            multiline
            value={expert.bio || ""}
            onSave={(v) => patch({ bio: v.trim() || null })}
          />
        </div>
        <div className="grid grid-cols-1 gap-md md:grid-cols-3">
          <ListEditor
            label="所属"
            values={expert.affiliations}
            onSave={(arr) => patch({ affiliations: arr })}
          />
          <ListEditor
            label="领域"
            values={expert.domains}
            onSave={(arr) => patch({ domains: arr })}
          />
          <ListEditor
            label="主页 / 链接"
            values={expert.profile_urls}
            onSave={(arr) => patch({ profile_urls: arr })}
          />
        </div>
      </header>

      <section className="grid grid-cols-3 gap-md">
        <Stat label="收录观点" value={expert.viewpoint_count} />
        <Stat
          label="独立来源域"
          value={expert.source_domains.length}
        />
        <Stat
          label="最近发声"
          value={fmtDate(vps[0]?.claim_when || expert.updated_at)}
          numeric={false}
        />
      </section>

      {expert.source_domains.length > 0 && (
        <section>
          <h3 className="font-display text-tagline text-ink">引用来源</h3>
          <div className="mt-sm flex flex-wrap gap-xxs">
            {expert.source_domains.map((d) => (
              <span
                key={d.domain}
                className="inline-flex items-center rounded-pill bg-pearl px-2.5 py-0.5 text-caption text-ink-muted-80"
              >
                <span className="font-mono">{d.domain}</span>
                <span className="ml-1 tabular-nums text-ink-muted-48">×{d.count}</span>
              </span>
            ))}
          </div>
        </section>
      )}

      <section>
        <header className="mb-sm flex items-baseline justify-between">
          <h3 className="font-display text-tagline text-ink">
            观点 ({vps.length})
          </h3>
          <span className="text-caption text-ink-muted-48">按时间倒序</span>
        </header>
        {vps.length === 0 ? (
          <div className="rounded-tile-lg border border-hairline bg-pearl/30 py-xxl text-center text-caption text-ink-muted-48">
            该专家暂无收录观点
          </div>
        ) : (
          <ol className="space-y-md">
            {vps.map((v) => (
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
                {v.claim_why_context && (
                  <p className="mt-xs text-caption text-ink-muted-80">
                    背景：{v.claim_why_context}
                  </p>
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
          </ol>
        )}
      </section>
    </div>
  );
}

function Stat({
  label,
  value,
  numeric = true,
}: {
  label: string;
  value: number | string;
  numeric?: boolean;
}) {
  return (
    <div className="rounded-tile-lg border border-hairline bg-paper p-md">
      <div className="text-caption text-ink-muted-48">{label}</div>
      <div
        className={
          "mt-xs font-display text-display-md text-ink " +
          (numeric ? "tabular-nums" : "")
        }
      >
        {value}
      </div>
    </div>
  );
}
