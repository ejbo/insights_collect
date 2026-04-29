"use client";
import { use, useState } from "react";
import useSWR from "swr";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { fetcher } from "../../../lib/api";
import type { Report } from "../../../lib/types";
import { AgentStepper } from "../../../components/AgentStepper";

export default function ReportDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data: report } = useSWR<Report>(`/api/reports/${id}`, fetcher, { refreshInterval: 3000 });
  const { data: md } = useSWR<string>(
    report?.md_path ? `/api/reports/${id}/markdown` : null,
    fetcher,
    { refreshInterval: 5000 },
  );
  const { data: outline } = useSWR<any>(
    report?.outline_json_path ? `/api/reports/${id}/outline` : null,
    fetcher,
  );
  const { data: providerCalls } = useSWR<any[]>(
    `/api/runs/report/${id}/provider-calls`,
    fetcher,
    { refreshInterval: 3000 },
  );

  const [showOutline, setShowOutline] = useState(false);

  if (!report) return <div>Loading…</div>;

  return (
    <div className="space-y-4">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">{report.title}</h1>
          <div className="text-sm text-gray-500 mt-1">
            {report.focus_topics?.join("、")} · {new Date(report.time_range_start).toLocaleDateString()} ~{" "}
            {new Date(report.time_range_end).toLocaleDateString()}
          </div>
          <div className="mt-2 flex items-center gap-2 text-sm">
            <span className={`px-2 py-0.5 rounded text-xs ${
              report.status === "succeeded" ? "bg-green-100 text-green-700" :
              report.status === "running" ? "bg-blue-100 text-blue-700" :
              report.status === "failed" ? "bg-red-100 text-red-700" : "bg-gray-100 text-gray-700"
            }`}>{report.status}</span>
            <span className="text-gray-500">
              ${report.total_cost_usd?.toFixed(4) || "0.0000"} · {report.total_tokens || 0} tokens
            </span>
          </div>
          {report.error && (
            <pre className="mt-2 text-xs text-red-700 whitespace-pre-wrap bg-red-50 p-2 rounded max-w-xl">
              {report.error}
            </pre>
          )}
        </div>
        <div className="flex gap-2">
          {report.pdf_path && (
            <a href={`/api/reports/${id}/pdf`} className="bg-blue-600 text-white text-sm px-3 py-2 rounded">
              Download PDF
            </a>
          )}
          {report.outline_json_path && (
            <button onClick={() => setShowOutline((v) => !v)}
              className="border border-blue-600 text-blue-600 text-sm px-3 py-2 rounded">
              {showOutline ? "Hide" : "Show"} PPT outline JSON
            </button>
          )}
        </div>
      </header>

      {showOutline && outline && (
        <pre className="bg-gray-900 text-gray-100 text-xs rounded p-4 overflow-auto max-h-96">
          {JSON.stringify(outline, null, 2)}
        </pre>
      )}

      <section className="grid grid-cols-3 gap-4">
        <div className="col-span-2 bg-white border rounded p-5">
          {md ? (
            <div className="prose-md">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{md}</ReactMarkdown>
            </div>
          ) : (
            <div className="text-sm text-gray-500">
              {report.status === "running" ? "正在生成…" : "Markdown 尚未生成"}
            </div>
          )}
        </div>

        <aside className="space-y-3 text-sm">
          <AgentStepper reportId={Number(id)} status={report.status} />

          <div className="bg-white border rounded p-3">
            <h3 className="font-semibold mb-2">Provider calls</h3>
            <ul className="space-y-1 max-h-96 overflow-auto">
              {(providerCalls || []).map((c, i) => (
                <li key={i} className="border-b last:border-0 pb-1">
                  <span className={c.success ? "text-green-700" : "text-red-700"}>●</span>{" "}
                  <code>{c.provider}/{c.model}</code> · {c.purpose} · {c.latency_ms}ms · ${c.cost_usd?.toFixed(4)}
                  {c.error && <div className="text-xs text-red-600">{c.error}</div>}
                </li>
              ))}
              {(providerCalls || []).length === 0 && (
                <li className="text-gray-500">No calls yet.</li>
              )}
            </ul>
          </div>
        </aside>
      </section>
    </div>
  );
}
