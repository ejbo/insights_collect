export const apiBase = "";  // proxied via Next rewrites → backend

export async function api<T = any>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(apiBase + path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
    cache: "no-store",
  });
  if (!r.ok) {
    const txt = await r.text();
    throw new Error(`${r.status} ${r.statusText}: ${txt}`);
  }
  const ctype = r.headers.get("content-type") || "";
  if (ctype.includes("application/json")) return r.json();
  // fall back to text
  return (await r.text()) as unknown as T;
}

export const fetcher = (url: string) => api(url);
