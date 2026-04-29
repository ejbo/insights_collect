"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { api, fetcher } from "../../../lib/api";
import type { ProviderCredentialView, ReportTemplate } from "../../../lib/types";

const ALL_PROVIDERS = ["anthropic", "openai", "gemini", "grok", "perplexity", "qwen", "deepseek"];

export default function NewReportPage() {
  const router = useRouter();
  const { data: templates } = useSWR<ReportTemplate[]>("/api/templates", fetcher);
  const { data: creds } = useSWR<ProviderCredentialView[]>("/api/settings/providers", fetcher);

  const today = new Date();
  const fmt = (d: Date) => d.toISOString().slice(0, 10);
  const thirtyAgo = new Date(today);
  thirtyAgo.setDate(today.getDate() - 30);

  const [title, setTitle] = useState("ICT 产业打卡观点总结");
  const [topicsRaw, setTopicsRaw] = useState("Token 经济, 黄仁勋, 斯坦福 2026 AI 报告, Pichai 十年复盘");
  const [startDate, setStartDate] = useState(fmt(thirtyAgo));
  const [endDate, setEndDate] = useState(fmt(today));
  const [providers, setProviders] = useState<string[]>([]);
  const [mdTemplateId, setMdTemplateId] = useState<number | "">("");
  const [outlineTemplateId, setOutlineTemplateId] = useState<number | "">("");
  const [costCap, setCostCap] = useState(10);
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Default selected providers = enabled & has_key
  useEffect(() => {
    if (!creds) return;
    setProviders((cur) =>
      cur.length > 0
        ? cur
        : creds.filter((c) => c.enabled && c.has_key).map((c) => c.provider),
    );
  }, [creds]);

  // Default templates = first md_report default + first ppt_outline default
  useEffect(() => {
    if (!templates) return;
    setMdTemplateId((cur) =>
      cur !== ""
        ? cur
        : templates.find((t) => t.kind === "md_report" && t.is_default)?.id ??
          templates.find((t) => t.kind === "md_report")?.id ??
          "",
    );
    setOutlineTemplateId((cur) =>
      cur !== ""
        ? cur
        : templates.find((t) => t.kind === "ppt_outline" && t.is_default)?.id ??
          templates.find((t) => t.kind === "ppt_outline")?.id ??
          "",
    );
  }, [templates]);

  function toggleProvider(p: string) {
    setProviders((cur) => (cur.includes(p) ? cur.filter((x) => x !== p) : [...cur, p]));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setErr(null);
    try {
      const focus = topicsRaw.split(/[,、，;；\n]/).map((s) => s.trim()).filter(Boolean);
      const body = {
        title,
        focus_topics: focus,
        time_range_start: new Date(startDate + "T00:00:00").toISOString(),
        time_range_end: new Date(endDate + "T23:59:59").toISOString(),
        md_template_id: mdTemplateId || null,
        outline_template_id: outlineTemplateId || null,
        providers_enabled: providers,
        cost_cap_usd: costCap,
        max_reflection_rounds: 3,
      };
      const created: any = await api("/api/reports", { method: "POST", body: JSON.stringify(body) });
      router.push(`/reports/${created.id}`);
    } catch (e: any) {
      setErr(String(e.message || e));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="max-w-3xl">
      <h1 className="text-2xl font-semibold mb-4">New report</h1>
      <form onSubmit={submit} className="space-y-4 bg-white border rounded p-5">
        <div>
          <label className="block text-sm font-medium mb-1">Title</label>
          <input className="w-full border rounded px-3 py-2"
            value={title} onChange={(e) => setTitle(e.target.value)} />
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">Focus topics（逗号 / 顿号分隔）</label>
          <textarea className="w-full border rounded px-3 py-2 h-20"
            value={topicsRaw} onChange={(e) => setTopicsRaw(e.target.value)} />
        </div>

        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="block text-sm font-medium mb-1">Start date</label>
            <input type="date" className="w-full border rounded px-3 py-2"
              value={startDate} max={endDate}
              onChange={(e) => setStartDate(e.target.value)} />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">End date</label>
            <input type="date" className="w-full border rounded px-3 py-2"
              value={endDate} min={startDate}
              onChange={(e) => setEndDate(e.target.value)} />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">Cost cap (USD)</label>
            <input type="number" step={0.5} className="w-full border rounded px-3 py-2"
              value={costCap} onChange={(e) => setCostCap(Number(e.target.value))} />
          </div>
        </div>
        <div className="flex gap-2 text-xs">
          {[
            { label: "近 7 天", days: 7 },
            { label: "近 30 天", days: 30 },
            { label: "近 90 天", days: 90 },
            { label: "近 180 天", days: 180 },
          ].map((p) => (
            <button key={p.days} type="button"
              onClick={() => {
                const e = new Date();
                const s = new Date(e);
                s.setDate(e.getDate() - p.days);
                setStartDate(fmt(s));
                setEndDate(fmt(e));
              }}
              className="text-blue-600 hover:underline">
              {p.label}
            </button>
          ))}
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">Providers</label>
          <div className="flex flex-wrap gap-2 text-sm">
            {ALL_PROVIDERS.map((p) => {
              const c = creds?.find((x) => x.provider === p);
              const hasKey = c?.has_key;
              return (
                <label key={p}
                  className={`px-3 py-1 rounded border cursor-pointer ${
                    providers.includes(p)
                      ? "bg-blue-50 border-blue-400 text-blue-700"
                      : "bg-white border-gray-300 text-gray-700"
                  } ${hasKey ? "" : "opacity-50"}`}>
                  <input type="checkbox" className="mr-1"
                    checked={providers.includes(p)} onChange={() => toggleProvider(p)} disabled={!hasKey} />
                  {p}
                </label>
              );
            })}
          </div>
          {creds && creds.filter((c) => c.has_key && c.enabled).length === 0 && (
            <p className="text-xs text-orange-600 mt-2">
              没有已启用的 provider key — 先去 <a href="/settings" className="underline">/settings</a> 配置。
            </p>
          )}
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-sm font-medium mb-1">Markdown template</label>
            <select className="w-full border rounded px-3 py-2"
              value={mdTemplateId} onChange={(e) => setMdTemplateId(e.target.value ? Number(e.target.value) : "")}>
              <option value="">— default —</option>
              {(templates || []).filter((t) => t.kind === "md_report").map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}{t.is_default ? " ★" : ""}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">PPT outline template</label>
            <select className="w-full border rounded px-3 py-2"
              value={outlineTemplateId} onChange={(e) => setOutlineTemplateId(e.target.value ? Number(e.target.value) : "")}>
              <option value="">— default —</option>
              {(templates || []).filter((t) => t.kind === "ppt_outline").map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}{t.is_default ? " ★" : ""}
                </option>
              ))}
            </select>
          </div>
        </div>

        {err && <p className="text-red-600 text-sm">{err}</p>}

        <button type="submit" disabled={submitting || providers.length === 0}
          className="bg-blue-600 disabled:bg-gray-300 text-white px-5 py-2 rounded">
          {submitting ? "Submitting…" : "Generate report"}
        </button>
      </form>
    </div>
  );
}
