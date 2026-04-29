"use client";
import useSWR from "swr";
import { useState } from "react";
import { fetcher } from "../../lib/api";

type Expert = {
  id: number;
  name: string;
  name_zh?: string | null;
  bio?: string | null;
  affiliations?: string[] | null;
};

export default function ExpertsPage() {
  const [q, setQ] = useState("");
  const { data } = useSWR<Expert[]>(`/api/experts?q=${encodeURIComponent(q)}`, fetcher);

  return (
    <div className="space-y-4">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Experts</h1>
        <input className="border rounded px-3 py-2 text-sm w-64"
          placeholder="Search by name…" value={q} onChange={(e) => setQ(e.target.value)} />
      </header>
      <div className="bg-white border rounded">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-left">
            <tr>
              <th className="px-3 py-2 w-12">#</th>
              <th className="px-3 py-2">Name</th>
              <th className="px-3 py-2">Affiliations</th>
              <th className="px-3 py-2">Bio</th>
            </tr>
          </thead>
          <tbody>
            {(data || []).map((e) => (
              <tr key={e.id} className="border-t">
                <td className="px-3 py-2 text-gray-500">{e.id}</td>
                <td className="px-3 py-2">{e.name}{e.name_zh ? ` (${e.name_zh})` : ""}</td>
                <td className="px-3 py-2">{(e.affiliations || []).join("、")}</td>
                <td className="px-3 py-2 text-gray-600">{e.bio}</td>
              </tr>
            ))}
            {(data || []).length === 0 && (
              <tr><td colSpan={4} className="px-3 py-6 text-center text-gray-500">No experts yet — accumulate by running reports.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
