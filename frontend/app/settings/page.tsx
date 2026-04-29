"use client";
import { useEffect, useState } from "react";
import useSWR from "swr";
import { api, fetcher } from "../../lib/api";
import type { ProviderCredentialView } from "../../lib/types";

const PROVIDER_INFO: Record<string, { label: string; help: string; modelHint: string }> = {
  anthropic: { label: "Anthropic Claude", help: "claude-opus-4-7 / sonnet-4-6 + web_search 工具", modelHint: "claude-opus-4-7" },
  openai: { label: "OpenAI", help: "gpt-5 + Responses API web_search", modelHint: "gpt-5" },
  gemini: { label: "Google Gemini", help: "gemini-2.5-pro + Search grounding", modelHint: "gemini-2.5-pro" },
  grok: { label: "xAI Grok", help: "grok-4 + X / Twitter live search", modelHint: "grok-4" },
  perplexity: { label: "Perplexity", help: "sonar-pro 引用透明度顶级", modelHint: "sonar-pro" },
  qwen: { label: "Qwen (DashScope)", help: "qwen3-max 中文圈最深", modelHint: "qwen3-max" },
  deepseek: { label: "DeepSeek", help: "deepseek-chat / deepseek-reasoner", modelHint: "deepseek-chat" },
};

export default function SettingsPage() {
  const { data, mutate } = useSWR<ProviderCredentialView[]>("/api/settings/providers", fetcher);

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Settings — Provider keys</h1>
      <p className="text-sm text-gray-600">
        在这里配置 7 家搜索 / LLM provider 的 API key。改完点 Save，再点 Test 验证。
        Keys 存在数据库（DB 优先，<code>.env</code> 兜底）。
      </p>
      <div className="space-y-3">
        {(data || []).map((c) => (
          <ProviderCard key={c.provider} cred={c} onChange={mutate} />
        ))}
      </div>
    </div>
  );
}

function ProviderCard({ cred, onChange }: { cred: ProviderCredentialView; onChange: () => void }) {
  const info = PROVIDER_INFO[cred.provider] || { label: cred.provider, help: "", modelHint: "" };
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState(cred.base_url || "");
  const [model, setModel] = useState(cred.default_model || info.modelHint);
  const [enabled, setEnabled] = useState(cred.enabled);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  // Smoke-test panel
  const [smokeOpen, setSmokeOpen] = useState(false);
  const [smokeQuery, setSmokeQuery] = useState("近期 AI 行业重要专家观点");
  const [smokeBusy, setSmokeBusy] = useState(false);
  const [smokeResult, setSmokeResult] = useState<any | null>(null);

  useEffect(() => {
    setBaseUrl(cred.base_url || "");
    setModel(cred.default_model || info.modelHint);
    setEnabled(cred.enabled);
  }, [cred, info.modelHint]);

  async function save() {
    setBusy(true);
    setMsg(null);
    try {
      const body: any = {
        base_url: baseUrl || null,
        default_model: model || null,
        enabled,
      };
      if (apiKey) body.api_key = apiKey;
      await api(`/api/settings/providers/${cred.provider}`, { method: "PUT", body: JSON.stringify(body) });
      setApiKey("");
      onChange();
      setMsg("Saved.");
    } catch (e: any) {
      setMsg(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  async function test() {
    setBusy(true);
    setMsg("Testing…");
    try {
      const r: any = await api(`/api/settings/providers/${cred.provider}/test`, { method: "POST" });
      setMsg(`${r.test_status}: ${r.test_message || ""}`);
      onChange();
    } catch (e: any) {
      setMsg(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  async function runSmoke() {
    setSmokeBusy(true);
    setSmokeResult(null);
    try {
      const r: any = await api(`/api/settings/providers/${cred.provider}/smoke`, {
        method: "POST",
        body: JSON.stringify({ query: smokeQuery, lang: "zh", days: 30, max_results: 5 }),
      });
      setSmokeResult(r);
    } catch (e: any) {
      setSmokeResult({ success: false, error: String(e.message || e) });
    } finally {
      setSmokeBusy(false);
    }
  }

  return (
    <div className="bg-white border rounded p-4">
      <div className="flex items-start justify-between">
        <div>
          <div className="font-semibold">
            {info.label}
            {cred.has_key && <span className="ml-2 text-xs text-green-600">key set</span>}
            {cred.test_status === "ok" && <span className="ml-2 text-xs text-green-700">tested ✓</span>}
            {cred.test_status === "error" && <span className="ml-2 text-xs text-red-600">test failed</span>}
          </div>
          <div className="text-xs text-gray-500">{info.help}</div>
        </div>
        <label className="text-sm flex items-center gap-1">
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
          enabled
        </label>
      </div>

      <div className="grid grid-cols-3 gap-3 mt-3">
        <input type="password" className="border rounded px-3 py-2 col-span-3"
          placeholder={cred.has_key ? "•••••••• (leave empty to keep)" : "API key"}
          value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
        <input className="border rounded px-3 py-2"
          placeholder="default model" value={model} onChange={(e) => setModel(e.target.value)} />
        <input className="border rounded px-3 py-2 col-span-2"
          placeholder="custom base url (optional)" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
      </div>

      <div className="flex items-center gap-2 mt-3">
        <button onClick={save} disabled={busy} className="bg-blue-600 text-white text-sm px-4 py-1.5 rounded">
          Save
        </button>
        <button onClick={test} disabled={busy || (!cred.has_key && !apiKey)}
          className="border border-gray-300 text-sm px-4 py-1.5 rounded">
          Test connection
        </button>
        <button onClick={() => setSmokeOpen((v) => !v)} disabled={!cred.has_key && !apiKey}
          className="border border-purple-400 text-purple-700 text-sm px-4 py-1.5 rounded">
          {smokeOpen ? "Hide smoke" : "Smoke search"}
        </button>
        {msg && <span className="text-xs text-gray-600">{msg}</span>}
      </div>

      {smokeOpen && (
        <div className="mt-3 border-t pt-3 space-y-2">
          <div className="flex gap-2">
            <input className="border rounded px-3 py-1.5 text-sm flex-1"
              placeholder="测试查询（中文）"
              value={smokeQuery} onChange={(e) => setSmokeQuery(e.target.value)} />
            <button onClick={runSmoke} disabled={smokeBusy}
              className="bg-purple-600 text-white text-sm px-4 py-1.5 rounded">
              {smokeBusy ? "Running…" : "Run"}
            </button>
          </div>
          {smokeResult && (
            <div className={`text-xs p-3 rounded ${smokeResult.success ? "bg-green-50 border border-green-200" : "bg-red-50 border border-red-200"}`}>
              <div className="flex flex-wrap gap-x-4 gap-y-1 mb-2">
                <span><strong>success:</strong> {smokeResult.success ? "✓" : "✗"}</span>
                <span><strong>duration:</strong> {smokeResult.duration_ms}ms</span>
                <span><strong>snippets:</strong> {smokeResult.snippets_count}</span>
                {smokeResult.trace && (
                  <>
                    <span><strong>tokens:</strong> {(smokeResult.trace.tokens_input || 0) + (smokeResult.trace.tokens_output || 0)}</span>
                    <span><strong>cost:</strong> ${(smokeResult.trace.cost_usd || 0).toFixed(5)}</span>
                  </>
                )}
              </div>
              {smokeResult.error && (
                <div className="text-red-700 break-all"><strong>error:</strong> {smokeResult.error}</div>
              )}
              {smokeResult.sample && smokeResult.sample.length > 0 && (
                <ol className="list-decimal ml-5 space-y-1 mt-1">
                  {smokeResult.sample.map((s: any, i: number) => (
                    <li key={i}>
                      <span className="font-medium">{s.title || s.source_domain || "(no title)"}</span>
                      {s.url && (
                        <a href={s.url} target="_blank" rel="noreferrer" className="ml-1 text-blue-600 hover:underline">
                          ↗
                        </a>
                      )}
                      <div className="text-gray-600">{s.snippet}</div>
                    </li>
                  ))}
                </ol>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
