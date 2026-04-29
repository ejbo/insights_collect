"use client";
import useSWR from "swr";
import Link from "next/link";
import { fetcher } from "../../lib/api";
import type { ReportTemplate } from "../../lib/types";

export default function TemplatesPage() {
  const { data } = useSWR<ReportTemplate[]>("/api/templates", fetcher);

  return (
    <div className="space-y-4">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Report templates</h1>
        <Link href="/templates/new" className="bg-blue-600 text-white text-sm px-4 py-2 rounded">
          + New template
        </Link>
      </header>
      <div className="bg-white border rounded">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-left">
            <tr>
              <th className="px-3 py-2 w-12">#</th>
              <th className="px-3 py-2">Name</th>
              <th className="px-3 py-2 w-32">Kind</th>
              <th className="px-3 py-2 w-20">Default</th>
              <th className="px-3 py-2 w-20">Built-in</th>
              <th className="px-3 py-2 w-20">Version</th>
            </tr>
          </thead>
          <tbody>
            {(data || []).map((t) => (
              <tr key={t.id} className="border-t hover:bg-gray-50">
                <td className="px-3 py-2 text-gray-500">{t.id}</td>
                <td className="px-3 py-2">
                  <Link href={`/templates/${t.id}`} className="text-blue-600 hover:underline">
                    {t.name}
                  </Link>
                  {t.description && <div className="text-xs text-gray-500">{t.description}</div>}
                </td>
                <td className="px-3 py-2">{t.kind}</td>
                <td className="px-3 py-2">{t.is_default ? "★" : ""}</td>
                <td className="px-3 py-2">{t.is_builtin ? "✓" : ""}</td>
                <td className="px-3 py-2">{t.version}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
