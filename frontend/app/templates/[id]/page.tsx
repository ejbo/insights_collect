"use client";
import { use, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { api, fetcher } from "../../../lib/api";
import type { ReportTemplate } from "../../../lib/types";

export default function TemplateEditor({ params }: { params: Promise<{ id: string }> }) {
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

  useEffect(() => {
    if (!data) return;
    setName(data.name);
    setKind(data.kind);
    setDescription(data.description || "");
    setPromptTemplate(data.prompt_template);
    setIsDefault(data.is_default);
  }, [data]);

  async function save() {
    setSaving(true);
    setErr(null);
    try {
      const body = {
        name, kind, prompt_template: promptTemplate,
        description, jinja_vars: null, is_default: isDefault,
      };
      if (isNew) {
        const created: any = await api("/api/templates", { method: "POST", body: JSON.stringify(body) });
        router.push(`/templates/${created.id}`);
      } else {
        await api(`/api/templates/${id}`, { method: "PUT", body: JSON.stringify(body) });
      }
    } catch (e: any) {
      setErr(String(e.message || e));
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!confirm("Delete this template?")) return;
    await api(`/api/templates/${id}`, { method: "DELETE" });
    router.push("/templates");
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">
        {isNew ? "New template" : `Edit: ${data?.name || ""}`}
        {data && <span className="ml-2 text-sm text-gray-500">v{data.version}</span>}
      </h1>

      <div className="grid grid-cols-3 gap-3">
        <input className="border rounded px-3 py-2 col-span-2" placeholder="Name"
          value={name} onChange={(e) => setName(e.target.value)} />
        <select className="border rounded px-3 py-2"
          value={kind} onChange={(e) => setKind(e.target.value as any)}>
          <option value="md_report">md_report</option>
          <option value="ppt_outline">ppt_outline</option>
          <option value="section">section</option>
        </select>
      </div>
      <input className="w-full border rounded px-3 py-2" placeholder="Description"
        value={description} onChange={(e) => setDescription(e.target.value)} />

      <textarea className="w-full border rounded px-3 py-2 font-mono text-xs h-[480px]"
        placeholder="Jinja2 template…"
        value={promptTemplate} onChange={(e) => setPromptTemplate(e.target.value)} />

      <label className="inline-flex items-center gap-2 text-sm">
        <input type="checkbox" checked={isDefault} onChange={(e) => setIsDefault(e.target.checked)} />
        Set as default for {kind}
      </label>

      {err && <p className="text-red-600 text-sm">{err}</p>}

      <div className="flex items-center gap-2">
        <button onClick={save} disabled={saving}
          className="bg-blue-600 text-white text-sm px-5 py-2 rounded">
          {saving ? "Saving…" : "Save"}
        </button>
        {!isNew && !data?.is_builtin && (
          <button onClick={remove} className="text-red-600 text-sm px-3 py-2 rounded">
            Delete
          </button>
        )}
        {data?.is_builtin && (
          <span className="text-xs text-gray-500">Built-in templates cannot be deleted.</span>
        )}
      </div>

      <div className="text-xs text-gray-500 mt-4">
        Available Jinja vars: <code>title</code>, <code>focus_topics</code>,
        <code>time_range_start</code>, <code>time_range_end</code>,
        <code>sections[]</code> ({"{topic_name, clusters[], section_summary}"}),
        <code>analysis</code> ({"{executive_summary, executive_summary_bullets, consensus[], dissent[], spotlight[], insight[]}"}),
        <code>all_viewpoints[]</code>, <code>top_viewpoints[]</code>.
      </div>
    </div>
  );
}
