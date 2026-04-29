"use client";
import useSWR from "swr";
import { fetcher } from "../lib/api";
import type { AgentRun, GraphMeta, Report } from "../lib/types";

function formatStat(node: string, stats: Record<string, any> | null): string {
  if (!stats) return "";
  const pairs: string[] = [];
  for (const [k, v] of Object.entries(stats)) {
    if (Array.isArray(v)) {
      pairs.push(`${k}: ${v.length === 0 ? "—" : v.join(",")}`);
    } else if (typeof v === "boolean") {
      pairs.push(`${k}: ${v ? "✓" : "✗"}`);
    } else {
      pairs.push(`${k}: ${v}`);
    }
  }
  return pairs.join(" · ");
}

function durationMs(a: string, b: string | null): string {
  if (!b) return "—";
  const ms = new Date(b).getTime() - new Date(a).getTime();
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60_000)}m${Math.round((ms % 60_000) / 1000)}s`;
}

export function AgentStepper({ reportId, status }: { reportId: number; status: Report["status"] }) {
  const { data: meta } = useSWR<GraphMeta>("/api/runs/graph-meta", fetcher);
  const { data: runs } = useSWR<AgentRun[]>(
    `/api/runs/report/${reportId}/agent-runs`,
    fetcher,
    { refreshInterval: 1500 },
  );

  if (!meta) return null;
  const runByNode = new Map<string, AgentRun>();
  (runs || []).forEach((r) => runByNode.set(r.graph_node, r));

  // Determine "currently running" node = first node in order that has not finished yet, while report is running
  let runningIdx = -1;
  if (status === "running") {
    for (let i = 0; i < meta.nodes.length; i++) {
      if (!runByNode.has(meta.nodes[i].name)) {
        runningIdx = i;
        break;
      }
    }
  }

  return (
    <div className="bg-white border rounded p-3 text-sm">
      <h3 className="font-semibold mb-2">Pipeline progress</h3>
      <ol className="space-y-2">
        {meta.nodes.map((n, idx) => {
          const run = runByNode.get(n.name);
          const isRunning = idx === runningIdx;
          const isDone = !!run;
          const hasError = run?.error;
          const dotClass = hasError
            ? "bg-red-500"
            : isDone
              ? "bg-green-500"
              : isRunning
                ? "bg-blue-500 animate-pulse"
                : "bg-gray-300";
          return (
            <li key={n.name} className="flex items-start gap-2">
              <span className={`mt-1.5 inline-block w-2.5 h-2.5 rounded-full ${dotClass}`} />
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className={isDone || isRunning ? "font-medium" : "text-gray-500"}>
                    {idx + 1}. {n.label}
                  </span>
                  {run && (
                    <span className="text-xs text-gray-500">
                      {durationMs(run.started_at, run.finished_at)}
                      {run.tokens > 0 && ` · ${run.tokens} tok`}
                      {run.cost_usd > 0 && ` · $${run.cost_usd.toFixed(4)}`}
                    </span>
                  )}
                  {isRunning && (
                    <span className="text-xs text-blue-600">running…</span>
                  )}
                </div>
                {run?.state_out && (
                  <div className="text-xs text-gray-600 mt-0.5">
                    {formatStat(n.name, run.state_out)}
                  </div>
                )}
                {hasError && (
                  <div className="text-xs text-red-600 mt-0.5 break-all">
                    ⚠ {run.error}
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
