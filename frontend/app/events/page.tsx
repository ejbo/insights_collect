"use client";
import useSWR from "swr";
import { fetcher } from "../../lib/api";

type Event = {
  id: number;
  name: string;
  kind: string;
  host?: string | null;
  url?: string | null;
  description?: string | null;
};

export default function EventsPage() {
  const { data } = useSWR<Event[]>("/api/events", fetcher);
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Events / Forums (anchors)</h1>
      <p className="text-sm text-gray-600">
        ExpertDiscoverer 在主题反向挖人时的优先 anchor 库。下次同主题 run 直接复用。
      </p>
      <div className="bg-white border rounded">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-left">
            <tr>
              <th className="px-3 py-2 w-12">#</th>
              <th className="px-3 py-2">Name</th>
              <th className="px-3 py-2 w-28">Kind</th>
              <th className="px-3 py-2">Host</th>
              <th className="px-3 py-2">Description</th>
            </tr>
          </thead>
          <tbody>
            {(data || []).map((e) => (
              <tr key={e.id} className="border-t">
                <td className="px-3 py-2 text-gray-500">{e.id}</td>
                <td className="px-3 py-2">
                  {e.url ? (
                    <a href={e.url} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline">
                      {e.name}
                    </a>
                  ) : e.name}
                </td>
                <td className="px-3 py-2">{e.kind}</td>
                <td className="px-3 py-2">{e.host}</td>
                <td className="px-3 py-2 text-gray-600">{e.description}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
