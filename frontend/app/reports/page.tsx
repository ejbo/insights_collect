"use client";
import useSWR from "swr";
import Link from "next/link";
import { fetcher } from "../../lib/api";
import type { Report } from "../../lib/types";

export default function ReportsList() {
  const { data } = useSWR<Report[]>("/api/reports?limit=100", fetcher, { refreshInterval: 3000 });
  return (
    <div className="space-y-4">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Reports</h1>
        <Link href="/reports/new" className="bg-blue-600 text-white text-sm px-4 py-2 rounded">
          + New report
        </Link>
      </header>
      <div className="bg-white border rounded">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-left">
            <tr>
              <th className="px-3 py-2 w-14">#</th>
              <th className="px-3 py-2">Title</th>
              <th className="px-3 py-2 w-28">Status</th>
              <th className="px-3 py-2 w-28">Cost</th>
              <th className="px-3 py-2 w-44">Created</th>
            </tr>
          </thead>
          <tbody>
            {(data || []).map((r) => (
              <tr key={r.id} className="border-t hover:bg-gray-50">
                <td className="px-3 py-2 text-gray-500">{r.id}</td>
                <td className="px-3 py-2">
                  <Link href={`/reports/${r.id}`} className="text-blue-600 hover:underline">
                    {r.title}
                  </Link>
                  <div className="text-xs text-gray-500">{r.focus_topics?.join("、")}</div>
                </td>
                <td className="px-3 py-2">{r.status}</td>
                <td className="px-3 py-2">${r.total_cost_usd?.toFixed(3) ?? "0.000"}</td>
                <td className="px-3 py-2">{new Date(r.created_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
