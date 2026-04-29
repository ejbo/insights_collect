"use client";
import useSWR from "swr";
import Link from "next/link";
import { fetcher } from "../lib/api";
import type { Report, Stats } from "../lib/types";

function StatusPill({ status }: { status: Report["status"] }) {
  const colors: Record<Report["status"], string> = {
    pending: "bg-gray-200 text-gray-700",
    running: "bg-blue-100 text-blue-700",
    succeeded: "bg-green-100 text-green-700",
    failed: "bg-red-100 text-red-700",
    cancelled: "bg-yellow-100 text-yellow-700",
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded ${colors[status]}`}>
      {status}
    </span>
  );
}

export default function Dashboard() {
  const { data: stats } = useSWR<Stats>("/api/stats", fetcher, { refreshInterval: 5000 });
  const { data: reports } = useSWR<Report[]>("/api/reports?limit=10", fetcher, {
    refreshInterval: 3000,
  });

  return (
    <div className="space-y-6">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Dashboard</h1>
        <Link
          href="/reports/new"
          className="bg-blue-600 hover:bg-blue-700 text-white text-sm px-4 py-2 rounded"
        >
          + New report
        </Link>
      </header>

      <section className="grid grid-cols-3 md:grid-cols-6 gap-3">
        {(
          [
            ["Reports", stats?.reports],
            ["Experts", stats?.experts],
            ["Viewpoints", stats?.viewpoints],
            ["Events", stats?.events],
            ["Sources", stats?.sources],
            ["Topics", stats?.topics],
          ] as const
        ).map(([label, value]) => (
          <div key={label} className="bg-white border border-gray-200 rounded p-3">
            <div className="text-xs text-gray-500">{label}</div>
            <div className="text-2xl font-semibold mt-1">{value ?? "-"}</div>
          </div>
        ))}
      </section>

      <section>
        <h2 className="text-lg font-semibold mb-2">Recent reports</h2>
        <div className="bg-white border border-gray-200 rounded overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left">
              <tr>
                <th className="px-3 py-2 w-14">#</th>
                <th className="px-3 py-2">Title</th>
                <th className="px-3 py-2 w-32">Status</th>
                <th className="px-3 py-2 w-32">Cost USD</th>
                <th className="px-3 py-2 w-44">Created</th>
              </tr>
            </thead>
            <tbody>
              {(reports || []).map((r) => (
                <tr key={r.id} className="border-t border-gray-100 hover:bg-gray-50">
                  <td className="px-3 py-2 text-gray-500">{r.id}</td>
                  <td className="px-3 py-2">
                    <Link href={`/reports/${r.id}`} className="text-blue-600 hover:underline">
                      {r.title}
                    </Link>
                    <div className="text-xs text-gray-500">
                      {r.focus_topics.join("、")}
                    </div>
                  </td>
                  <td className="px-3 py-2"><StatusPill status={r.status} /></td>
                  <td className="px-3 py-2">${r.total_cost_usd?.toFixed(3) ?? "0.000"}</td>
                  <td className="px-3 py-2 text-gray-600">
                    {new Date(r.created_at).toLocaleString()}
                  </td>
                </tr>
              ))}
              {(reports || []).length === 0 && (
                <tr>
                  <td colSpan={5} className="px-3 py-6 text-center text-gray-500">
                    No reports yet — <Link href="/reports/new" className="text-blue-600">create one</Link>.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
