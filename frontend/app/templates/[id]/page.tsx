"use client";
import { use, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import useSWR from "swr";
import { api, fetcher } from "../../../lib/api";
import type { ReportTemplate } from "../../../lib/types";

const KIND_LABEL: Record<ReportTemplate["kind"], string> = {
  md_report: "Markdown 报告",
  ppt_outline: "PPT 大纲",
  section: "Section",
};

/* -----------------------------------------------------------------------
 * Variable dictionary — kept in sync with report_composer.py's render ctx.
 * Every entry is click-to-insert (snippet inserted at cursor). Loops emit a
 * `{% for ... %}{% endfor %}` block; scalars emit `{{ ... }}`.
 * -------------------------------------------------------------------- */
type VarSpec = {
  expr: string;          // text inserted at cursor
  label: string;         // human-readable Chinese name
  hint: string;          // one-line description
  example?: string;      // optional inline example value
};
type VarSection = { title: string; vars: VarSpec[] };

const VARIABLES: VarSection[] = [
  {
    title: "报告头部",
    vars: [
      { expr: "{{ title }}", label: "标题", hint: "报告标题（用户在新建表单里填的）", example: "AI 治理与生产力周报" },
      { expr: "{{ focus_topics | join('、') }}", label: "焦点主题", hint: "焦点主题数组拼接", example: "AI 治理、AI 生产力" },
      { expr: "{{ time_range_start.strftime('%Y-%m-%d') }}", label: "时间窗起点", hint: "起始日期，常用 strftime 格式化" },
      { expr: "{{ time_range_end.strftime('%Y-%m-%d') }}", label: "时间窗终点", hint: "结束日期" },
    ],
  },
  {
    title: "综合分析（analysis）",
    vars: [
      { expr: "{{ analysis.executive_summary }}", label: "执行摘要", hint: "一段中文执行摘要" },
      {
        expr: "{% for b in analysis.executive_summary_bullets %}- {{ b }}\n{% endfor %}",
        label: "摘要要点（循环）",
        hint: "3-5 条要点的循环渲染",
      },
      {
        expr: "{% for item in analysis.consensus %}- {{ item }}\n{% endfor %}",
        label: "共识列表（循环）",
        hint: "可换为 dissent / spotlight / insight",
      },
      { expr: "{{ analysis.dissent }}", label: "分歧（数组）", hint: "list[str]" },
      { expr: "{{ analysis.spotlight }}", label: "重点（数组）", hint: "list[str]" },
      { expr: "{{ analysis.insight }}", label: "启示（数组）", hint: "list[str]" },
    ],
  },
  {
    title: "主题章节（sections）",
    vars: [
      {
        expr:
          "{% for section in sections %}\n## {{ loop.index }}. {{ section.topic_name }}\n" +
          "{{ section.section_summary }}\n" +
          "  {% for cluster in section.clusters %}\n" +
          "  ### {{ cluster.label }}（{{ cluster.kind }}）\n" +
          "  {{ cluster.summary_md }}\n" +
          "  {% endfor %}\n{% endfor %}",
        label: "完整 sections 循环",
        hint: "插入一个完整的双层循环（主题 → cluster），可在里面继续展开 viewpoints",
      },
      { expr: "{{ section.topic_name }}", label: "section.topic_name", hint: "在 sections 循环内：当前主题名" },
      { expr: "{{ section.section_summary }}", label: "section.section_summary", hint: "本节小结" },
      { expr: "{{ cluster.label }}", label: "cluster.label", hint: "在 cluster 循环内：聚类标签" },
      { expr: "{{ cluster.kind }}", label: "cluster.kind", hint: "consensus / dissent / spotlight / insight" },
      { expr: "{{ cluster.summary_md }}", label: "cluster.summary_md", hint: "聚类小结（已是 markdown）" },
    ],
  },
  {
    title: "观点（viewpoints）",
    vars: [
      {
        expr:
          "{% for v in cluster.viewpoints %}\n" +
          "- **{{ v.expert_name }}**（{{ v.claim_who_role or '' }}）\n" +
          "  > {{ v.claim_quote or v.claim_what }}\n" +
          "{% endfor %}",
        label: "cluster 内观点循环",
        hint: "在 cluster 循环里继续展开它的 viewpoints",
      },
      {
        expr:
          "{% for v in all_viewpoints %}\n- {{ v.expert_name }}：{{ v.claim_what }}\n{% endfor %}",
        label: "扁平 all_viewpoints 循环",
        hint: "全部观点（不分主题）",
      },
      { expr: "{{ v.expert_name }}", label: "v.expert_name", hint: "专家姓名（英文/原文）" },
      { expr: "{{ v.claim_who_role }}", label: "v.claim_who_role", hint: "角色，如 '国家数据局局长'" },
      { expr: "{{ v.claim_when.strftime('%Y-%m-%d') if v.claim_when else '时间未知' }}", label: "v.claim_when", hint: "datetime；若可能为空请加 if 守卫" },
      { expr: "{{ v.claim_where }}", label: "v.claim_where", hint: "场合 / 地点" },
      { expr: "{{ v.claim_what }}", label: "v.claim_what", hint: "观点摘要（必有）" },
      { expr: "{{ v.claim_quote }}", label: "v.claim_quote", hint: "原话引用（可空）" },
      { expr: "{{ v.claim_medium }}", label: "v.claim_medium", hint: "论坛 / 采访栏目 / 文章" },
      { expr: "{{ v.claim_source_url }}", label: "v.claim_source_url", hint: "来源链接" },
      { expr: "{{ v.claim_why_context }}", label: "v.claim_why_context", hint: "上下文 / 背景说明" },
      { expr: "{{ v.source_domain }}", label: "v.source_domain", hint: "来源域名（自动从 URL 提取）" },
    ],
  },
  {
    title: "Jinja 常用片段",
    vars: [
      { expr: "{% if  %}\n\n{% endif %}", label: "if 条件块", hint: "条件渲染" },
      { expr: "{{ value | default('—') }}", label: "default 过滤器", hint: "值为空时显示占位符" },
      { expr: "{{ items | join('、') }}", label: "join 过滤器", hint: "数组拼接" },
      { expr: "{{ obj | tojson }}", label: "tojson 过滤器", hint: "对象转 JSON 字符串（PPT 大纲必备）" },
      { expr: "{{ loop.index }}", label: "loop.index", hint: "在 for 循环内：1-based 当前下标" },
      { expr: "{{ loop.last }}", label: "loop.last", hint: "在 for 循环内：是否最后一个（用于逗号）" },
    ],
  },
];

export default function TemplateEditor({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const router = useRouter();
  const isNew = id === "new";
  const { data } = useSWR<ReportTemplate>(isNew ? null : `/api/templates/${id}`, fetcher);

  const [name, setName] = useState("");
  const [kind, setKind] = useState<"md_report" | "ppt_outline" | "section">("md_report");
  const [description, setDescription] = useState("");
  const [promptTemplate, setPromptTemplate] = useState("");
  const [isDefault, setIsDefault] = useState(false);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [rightTab, setRightTab] = useState<"vars" | "preview">("vars");
  const [search, setSearch] = useState("");

  const editorRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    if (!data) return;
    setName(data.name);
    setKind(data.kind);
    setDescription(data.description || "");
    setPromptTemplate(data.prompt_template);
    setIsDefault(data.is_default);
  }, [data]);

  /* --- click-to-insert at cursor ----------------------------------- */
  function insertAtCursor(snippet: string) {
    const el = editorRef.current;
    if (!el) {
      setPromptTemplate((prev) => prev + snippet);
      return;
    }
    const start = el.selectionStart ?? promptTemplate.length;
    const end = el.selectionEnd ?? promptTemplate.length;
    const next = promptTemplate.slice(0, start) + snippet + promptTemplate.slice(end);
    setPromptTemplate(next);
    // restore cursor right after the inserted snippet, on next tick
    requestAnimationFrame(() => {
      el.focus();
      const pos = start + snippet.length;
      el.setSelectionRange(pos, pos);
    });
  }

  /* --- live preview (debounced) ------------------------------------ */
  const [preview, setPreview] = useState<{ rendered: string; error: string | null; isJson: boolean } | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  useEffect(() => {
    if (rightTab !== "preview") return;
    if (!promptTemplate.trim()) {
      setPreview({ rendered: "", error: null, isJson: false });
      return;
    }
    setPreviewLoading(true);
    const timer = setTimeout(async () => {
      try {
        const res: any = await api("/api/templates/preview", {
          method: "POST",
          body: JSON.stringify({ prompt_template: promptTemplate, kind }),
        });
        setPreview({
          rendered: res.rendered || "",
          error: res.error || null,
          isJson: !!res.is_json,
        });
      } catch (e: any) {
        setPreview({ rendered: "", error: String(e?.message || e), isJson: false });
      } finally {
        setPreviewLoading(false);
      }
    }, 400);
    return () => clearTimeout(timer);
  }, [promptTemplate, kind, rightTab]);

  /* --- variable filter --------------------------------------------- */
  const filteredVars = useMemo(() => {
    if (!search.trim()) return VARIABLES;
    const q = search.trim().toLowerCase();
    return VARIABLES
      .map((s) => ({
        ...s,
        vars: s.vars.filter(
          (v) =>
            v.label.toLowerCase().includes(q) ||
            v.expr.toLowerCase().includes(q) ||
            v.hint.toLowerCase().includes(q),
        ),
      }))
      .filter((s) => s.vars.length > 0);
  }, [search]);

  async function save() {
    setSaving(true);
    setErr(null);
    try {
      const body = {
        name,
        kind,
        prompt_template: promptTemplate,
        description,
        jinja_vars: null,
        is_default: isDefault,
      };
      if (isNew) {
        const created: any = await api("/api/templates", {
          method: "POST",
          body: JSON.stringify(body),
        });
        router.push(`/templates/${created.id}`);
      } else {
        await api(`/api/templates/${id}`, {
          method: "PUT",
          body: JSON.stringify(body),
        });
      }
    } catch (e: any) {
      setErr(String(e.message || e));
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!confirm("删除该模板？")) return;
    await api(`/api/templates/${id}`, { method: "DELETE" });
    router.push("/templates");
  }

  return (
    <div className="space-y-md">
      <div className="flex items-baseline justify-between text-caption">
        <Link href="/templates" className="text-ink-muted-48 hover:text-primary">
          ← 模板列表
        </Link>
        {data && (
          <div className="flex items-center gap-xs text-ink-muted-48">
            <span>v{data.version}</span>
            {data.is_builtin && <span>· 内置（保存会另存为副本）</span>}
            {data.is_default && <span>· 默认</span>}
          </div>
        )}
      </div>

      <section className="card-utility space-y-md">
        <div className="grid grid-cols-1 gap-md md:grid-cols-3">
          <div className="md:col-span-2">
            <label className="mb-xs block text-caption-strong text-ink">名称</label>
            <input
              className="input-flat"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="例：周报 · 投资视角"
            />
          </div>
          <div>
            <label className="mb-xs block text-caption-strong text-ink">类型</label>
            <select
              className="input-flat"
              value={kind}
              onChange={(e) => setKind(e.target.value as any)}
            >
              <option value="md_report">{KIND_LABEL.md_report}</option>
              <option value="ppt_outline">{KIND_LABEL.ppt_outline}</option>
              <option value="section">{KIND_LABEL.section}</option>
            </select>
          </div>
        </div>

        <div>
          <label className="mb-xs block text-caption-strong text-ink">描述</label>
          <input
            className="input-flat"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="简单一句话说明这个模板适合什么场景"
          />
        </div>
      </section>

      {/* Editor + helper sidebar */}
      <section className="grid grid-cols-1 gap-md lg:grid-cols-5">
        <div className="lg:col-span-3">
          <div className="mb-xs flex items-baseline justify-between">
            <label className="text-caption-strong text-ink">Jinja 模板</label>
            <span className="text-caption text-ink-muted-48">
              点击右侧变量 → 自动插入到光标处
            </span>
          </div>
          <textarea
            ref={editorRef}
            className="textarea-flat h-[640px] !font-mono !text-caption"
            value={promptTemplate}
            onChange={(e) => setPromptTemplate(e.target.value)}
            spellCheck={false}
            placeholder="# {{ title }}&#10;&#10;{% for section in sections %}&#10;## {{ section.topic_name }}&#10;{% endfor %}"
          />
        </div>

        <aside className="card-utility lg:col-span-2 lg:max-h-[696px] lg:overflow-hidden flex flex-col">
          <div className="flex items-baseline justify-between">
            <div className="flex gap-xs">
              <button
                type="button"
                onClick={() => setRightTab("vars")}
                className={rightTab === "vars" ? "chip chip-selected" : "chip"}
              >
                变量字典
              </button>
              <button
                type="button"
                onClick={() => setRightTab("preview")}
                className={rightTab === "preview" ? "chip chip-selected" : "chip"}
              >
                实时预览
              </button>
            </div>
            {rightTab === "preview" && previewLoading && (
              <span className="text-caption text-ink-muted-48">渲染中…</span>
            )}
          </div>

          {rightTab === "vars" && (
            <>
              <input
                className="input-flat mt-sm !h-9 !text-caption"
                placeholder="搜索变量、字段、关键字..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
              <div className="mt-sm flex-1 space-y-md overflow-auto pr-xs">
                {filteredVars.map((sec) => (
                  <div key={sec.title}>
                    <div className="text-caption-strong text-ink">{sec.title}</div>
                    <ul className="mt-xs space-y-xxs">
                      {sec.vars.map((v) => (
                        <li key={v.label}>
                          <button
                            type="button"
                            onClick={() => insertAtCursor(v.expr)}
                            className="group block w-full rounded-sm px-xs py-xs text-left transition-colors hover:bg-pearl/60"
                            title="点击插入到光标处"
                          >
                            <div className="flex items-baseline justify-between gap-xs">
                              <span className="text-caption-strong text-ink">{v.label}</span>
                              <span className="text-caption text-ink-muted-48 opacity-0 transition-opacity group-hover:opacity-100">
                                ⤵ 插入
                              </span>
                            </div>
                            <code className="mt-xxs block break-all rounded-sm bg-parchment px-1.5 py-0.5 font-mono text-caption text-ink-muted-80">
                              {v.expr.length > 90 ? v.expr.slice(0, 90) + "…" : v.expr}
                            </code>
                            <p className="mt-xxs text-caption text-ink-muted-80">{v.hint}</p>
                            {v.example && (
                              <p className="mt-xxs text-caption text-ink-muted-48">
                                示例值：{v.example}
                              </p>
                            )}
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
                {filteredVars.length === 0 && (
                  <div className="text-center text-caption text-ink-muted-48">
                    没有匹配的变量
                  </div>
                )}
              </div>
            </>
          )}

          {rightTab === "preview" && (
            <div className="mt-sm flex-1 overflow-auto rounded-sm border border-hairline bg-pearl/40 p-sm">
              {preview?.error ? (
                <pre className="whitespace-pre-wrap break-all text-caption text-status-danger">
                  渲染错误：{preview.error}
                </pre>
              ) : preview?.rendered ? (
                <pre className="whitespace-pre-wrap break-all font-mono text-caption text-ink">
                  {preview.rendered}
                </pre>
              ) : (
                <div className="text-center text-caption text-ink-muted-48">
                  填入模板内容后会实时显示渲染结果（基于内置示例数据）
                </div>
              )}
            </div>
          )}
        </aside>
      </section>

      <section className="flex flex-wrap items-center gap-sm">
        <label className="inline-flex items-center gap-xs text-caption text-ink">
          <input
            type="checkbox"
            checked={isDefault}
            onChange={(e) => setIsDefault(e.target.checked)}
            className="accent-primary"
          />
          设为 {KIND_LABEL[kind]} 默认
        </label>
        <div className="ml-auto flex items-center gap-sm">
          <button onClick={save} disabled={saving} className="btn-primary">
            {saving ? "保存中…" : "保存"}
          </button>
          {!isNew && !data?.is_builtin && (
            <button
              onClick={remove}
              className="btn-secondary-pill !border-status-danger !text-status-danger"
            >
              删除
            </button>
          )}
          {data?.is_builtin && (
            <span className="text-caption text-ink-muted-48">内置模板不可删除</span>
          )}
        </div>
      </section>

      {err && (
        <div className="rounded-tile-lg border border-status-danger/30 bg-status-danger/10 px-lg py-md text-caption text-status-danger">
          {err}
        </div>
      )}
    </div>
  );
}
