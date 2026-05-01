"use client";
import useSWR from "swr";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, fetcher } from "../../lib/api";
import type { ReportTemplate } from "../../lib/types";

const KIND_LABEL: Record<ReportTemplate["kind"], string> = {
  md_report: "Markdown 报告",
  ppt_outline: "PPT 大纲",
  section: "Section",
};

export default function TemplatesPage() {
  const { data, mutate } = useSWR<ReportTemplate[]>("/api/templates", fetcher);
  const router = useRouter();
  const [busyId, setBusyId] = useState<number | null>(null);

  async function clone(t: ReportTemplate) {
    setBusyId(t.id);
    try {
      const created: any = await api("/api/templates", {
        method: "POST",
        body: JSON.stringify({
          name: `${t.name} · 副本`,
          kind: t.kind,
          prompt_template: t.prompt_template,
          description: t.description,
          jinja_vars: null,
          is_default: false,
        }),
      });
      await mutate();
      router.push(`/templates/${created.id}`);
    } finally {
      setBusyId(null);
    }
  }

  const list = data || [];
  const byKind: Record<string, ReportTemplate[]> = {};
  for (const t of list) {
    (byKind[t.kind] ||= []).push(t);
  }

  return (
    <div className="space-y-lg">
      <header className="flex flex-wrap items-baseline justify-between gap-sm">
        <div>
          <h2 className="font-display text-display-md text-ink">模板</h2>
          <p className="mt-xxs text-caption text-ink-muted-80">
            报告生成时按模板渲染。点击卡片编辑；编辑页右侧有变量字典与实时预览。
          </p>
        </div>
        <Link href="/templates/new" className="btn-primary">
          + 新建模板
        </Link>
      </header>

      {(["md_report", "ppt_outline", "section"] as const).map((k) =>
        byKind[k]?.length ? (
          <section key={k} className="space-y-sm">
            <h3 className="font-display text-tagline text-ink-muted-80">
              {KIND_LABEL[k]} ({byKind[k].length})
            </h3>
            <div className="grid grid-cols-1 gap-md md:grid-cols-2 lg:grid-cols-3">
              {byKind[k].map((t) => (
                <div
                  key={t.id}
                  className="card-utility group flex flex-col gap-sm"
                >
                  <div className="flex items-start justify-between gap-sm">
                    <Link
                      href={`/templates/${t.id}`}
                      className="font-display text-tagline text-ink hover:text-primary"
                    >
                      {t.name}
                    </Link>
                    {t.is_default && (
                      <span className="status-running shrink-0">默认</span>
                    )}
                  </div>
                  {t.description && (
                    <p className="line-clamp-2 text-caption text-ink-muted-80">
                      {t.description}
                    </p>
                  )}
                  <div className="mt-auto flex items-center gap-md pt-sm text-caption text-ink-muted-48">
                    <span className="tabular-nums">v{t.version}</span>
                    {t.is_builtin && <span>内置</span>}
                    <div className="ml-auto flex items-center gap-sm">
                      <button
                        type="button"
                        disabled={busyId === t.id}
                        onClick={() => clone(t)}
                        className="text-ink-muted-80 hover:text-primary"
                        title="基于该模板创建一个副本，可自由编辑"
                      >
                        {busyId === t.id ? "复制中…" : "复制"}
                      </button>
                      <Link
                        href={`/templates/${t.id}`}
                        className="text-primary hover:underline"
                      >
                        编辑 →
                      </Link>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </section>
        ) : null,
      )}

      {list.length === 0 && (
        <div className="card-utility py-xxl text-center text-caption text-ink-muted-48">
          暂无模板 ·{" "}
          <Link href="/templates/new" className="text-primary">
            新建一个
          </Link>
        </div>
      )}
    </div>
  );
}
