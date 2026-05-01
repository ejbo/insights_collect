"use client";
import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { api, fetcher } from "../../lib/api";
import type { ProviderCredentialView } from "../../lib/types";

type ProviderInfo = {
  label: string;
  help: string;
  modelHint: string;
  modelOptions: string[];
  baseUrlHint?: string;
  baseUrlOptions?: { url: string; label: string }[];
  baseUrlNote?: string;
};

const PROVIDER_INFO: Record<string, ProviderInfo> = {
  anthropic: {
    label: "Anthropic Claude",
    help: "claude-opus-4-7 / sonnet-4-6，原生 web_search",
    modelHint: "claude-opus-4-7",
    modelOptions: ["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
  },
  openai: {
    label: "OpenAI",
    help: "gpt-5 + Responses API web_search",
    modelHint: "gpt-5",
    modelOptions: ["gpt-5", "gpt-5-mini"],
  },
  gemini: {
    label: "Google Gemini",
    help: "gemini-3.1-pro-preview + Google Search grounding",
    modelHint: "gemini-3.1-pro-preview",
    modelOptions: ["gemini-3.1-pro-preview", "gemini-2.5-pro", "gemini-2.5-flash"],
  },
  grok: {
    label: "xAI Grok",
    help: "grok-4，X / Twitter 实时检索（Live Search）",
    modelHint: "grok-4",
    modelOptions: ["grok-4", "grok-3"],
  },
  perplexity: {
    label: "Perplexity",
    help: "sonar-pro · 引用透明度顶级",
    modelHint: "sonar-pro",
    modelOptions: ["sonar-pro", "sonar", "sonar-reasoning-pro", "sonar-reasoning"],
  },
  qwen: {
    label: "Qwen (DashScope)",
    help: "qwen3.6-plus + web_search 工具",
    modelHint: "qwen3.6-plus",
    modelOptions: ["qwen3.6-plus", "qwen3.5-plus", "qwen3-max", "qwen3-max-2026-01-23"],
    baseUrlHint: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    baseUrlNote:
      "API key 必须与 Base URL 区域一致，否则会 401。空着用北京默认。",
    baseUrlOptions: [
      { url: "https://dashscope.aliyuncs.com/compatible-mode/v1", label: "华北 2 · 北京（默认）" },
      { url: "https://dashscope-intl.aliyuncs.com/compatible-mode/v1", label: "新加坡" },
      { url: "https://dashscope-us.aliyuncs.com/compatible-mode/v1", label: "美国 · 弗吉尼亚" },
      { url: "https://cn-hongkong.dashscope.aliyuncs.com/compatible-mode/v1", label: "中国香港" },
    ],
  },
  deepseek: {
    label: "DeepSeek",
    help: "deepseek-v3.2 / reasoner",
    modelHint: "deepseek-v3.2",
    modelOptions: ["deepseek-v3.2", "deepseek-chat", "deepseek-reasoner"],
  },
};

type Edit = {
  api_key: string;
  default_model: string;
  base_url: string;
};

function emptyEdit(c: ProviderCredentialView): Edit {
  return {
    api_key: c.api_key || "",
    default_model: c.default_model || PROVIDER_INFO[c.provider]?.modelHint || "",
    base_url: c.base_url || "",
  };
}

function diff(c: ProviderCredentialView, e: Edit): Partial<Edit> | null {
  const out: Partial<Edit> = {};
  if (e.api_key !== (c.api_key || "")) out.api_key = e.api_key;
  if (e.default_model !== (c.default_model || "")) out.default_model = e.default_model;
  if (e.base_url !== (c.base_url || "")) out.base_url = e.base_url;
  return Object.keys(out).length === 0 ? null : out;
}

export default function SettingsPage() {
  const { data, mutate } = useSWR<ProviderCredentialView[]>(
    "/api/settings/providers",
    fetcher,
  );
  const [edits, setEdits] = useState<Record<string, Edit>>({});
  const [savingAll, setSavingAll] = useState(false);
  const [bannerMsg, setBannerMsg] = useState<string | null>(null);

  // Hydrate edits from server data once it arrives.
  useEffect(() => {
    if (!data) return;
    setEdits((prev) => {
      const next = { ...prev };
      for (const c of data) {
        if (!next[c.provider]) next[c.provider] = emptyEdit(c);
      }
      return next;
    });
  }, [data]);

  const dirtyProviders = useMemo(() => {
    if (!data) return [];
    return data.filter((c) => edits[c.provider] && diff(c, edits[c.provider]));
  }, [data, edits]);

  const dirtyCount = dirtyProviders.length;

  function update(provider: string, patch: Partial<Edit>) {
    setEdits((prev) => ({
      ...prev,
      [provider]: { ...(prev[provider] || ({} as Edit)), ...patch },
    }));
  }

  async function saveAll() {
    if (!data || dirtyCount === 0) return;
    setSavingAll(true);
    setBannerMsg(null);
    try {
      const payload = dirtyProviders.map((c) => ({
        provider: c.provider,
        ...diff(c, edits[c.provider]),
      }));
      await api("/api/settings/providers", {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      await mutate();
      setBannerMsg(`Saved ${dirtyCount} provider${dirtyCount > 1 ? "s" : ""}.`);
      setTimeout(() => setBannerMsg(null), 3000);
    } catch (e: any) {
      setBannerMsg(`Save failed: ${e.message || e}`);
    } finally {
      setSavingAll(false);
    }
  }

  function resetEdits() {
    if (!data) return;
    const next: Record<string, Edit> = {};
    for (const c of data) next[c.provider] = emptyEdit(c);
    setEdits(next);
    setBannerMsg(null);
  }

  return (
    <div className="space-y-lg">
      <header className="flex items-end justify-between">
        <div className="text-caption text-ink-muted-48">
          {dirtyCount > 0 ? `${dirtyCount} 项未保存` : "已同步"}
        </div>
        <div className="flex items-center gap-sm">
          {dirtyCount > 0 && (
            <button
              onClick={resetEdits}
              disabled={savingAll}
              className="btn-pearl"
            >
              撤销 ({dirtyCount})
            </button>
          )}
          <button
            onClick={saveAll}
            disabled={savingAll || dirtyCount === 0}
            className="btn-primary"
          >
            {savingAll ? "保存中…" : dirtyCount === 0 ? "保存" : `保存 (${dirtyCount})`}
          </button>
        </div>
      </header>

      {bannerMsg && (
        <div className="card-utility !py-sm text-caption text-ink-muted-80">{bannerMsg}</div>
      )}

      <div className="space-y-md">
        {(data ?? []).map((c) => {
          const e = edits[c.provider] || emptyEdit(c);
          const isDirty = !!diff(c, e);
          return (
            <ProviderCard
              key={c.provider}
              cred={c}
              edit={e}
              isDirty={isDirty}
              onChange={(patch) => update(c.provider, patch)}
              onAfterTestOrSmoke={mutate}
            />
          );
        })}
      </div>
    </div>
  );
}

function ProviderCard({
  cred,
  edit,
  isDirty,
  onChange,
  onAfterTestOrSmoke,
}: {
  cred: ProviderCredentialView;
  edit: Edit;
  isDirty: boolean;
  onChange: (patch: Partial<Edit>) => void;
  onAfterTestOrSmoke: () => void;
}) {
  const info: ProviderInfo = PROVIDER_INFO[cred.provider] || {
    label: cred.provider,
    help: "",
    modelHint: "",
    modelOptions: [],
  };

  // Local UI state — testing & smoke
  const [busy, setBusy] = useState(false);
  const [testMsg, setTestMsg] = useState<string | null>(null);

  const [smokeOpen, setSmokeOpen] = useState(false);
  const [smokeQuery, setSmokeQuery] = useState("近期 AI 行业重要专家观点");
  const [smokeBusy, setSmokeBusy] = useState(false);
  const [smokeResult, setSmokeResult] = useState<any | null>(null);

  async function test() {
    setBusy(true);
    setTestMsg("Testing…");
    try {
      const r: any = await api(
        `/api/settings/providers/${cred.provider}/test`,
        { method: "POST" },
      );
      setTestMsg(`${r.test_status}: ${r.test_message || ""}`);
      onAfterTestOrSmoke();
    } catch (err: any) {
      setTestMsg(`error: ${err.message || err}`);
    } finally {
      setBusy(false);
    }
  }

  async function runSmoke() {
    setSmokeBusy(true);
    setSmokeResult(null);
    try {
      const r: any = await api(
        `/api/settings/providers/${cred.provider}/smoke`,
        {
          method: "POST",
          body: JSON.stringify({ query: smokeQuery, lang: "zh", days: 30, max_results: 5 }),
        },
      );
      setSmokeResult(r);
    } catch (err: any) {
      setSmokeResult({ success: false, error: String(err.message || err) });
    } finally {
      setSmokeBusy(false);
    }
  }

  const enabled = !!edit.api_key;
  const statusBadge =
    cred.test_status === "ok"
      ? "status-succeeded"
      : cred.test_status === "error"
        ? "status-failed"
        : "status-pending";

  return (
    <section className="card-utility">
      {/* Header row */}
      <div className="flex flex-wrap items-start justify-between gap-sm">
        <div className="min-w-0">
          <div className="flex items-center gap-sm">
            <h3 className="font-display text-tagline text-ink">{info.label}</h3>
            {enabled ? (
              <span className="status-succeeded">已启用</span>
            ) : (
              <span className="status-cancelled">未配置</span>
            )}
            {cred.test_status === "ok" && (
              <span className={statusBadge}>测试通过</span>
            )}
            {cred.test_status === "error" && (
              <span className={statusBadge}>测试失败</span>
            )}
            {isDirty && <span className="status-running">未保存</span>}
          </div>
          <p className="mt-xs text-caption text-ink-muted-48">{info.help}</p>
        </div>
        <div className="flex items-center gap-xs">
          <button
            onClick={test}
            disabled={busy || !edit.api_key}
            className="btn-pearl"
            title="GET /v1/models — 快速验证 key"
          >
            {busy ? "测试中…" : "测试 key"}
          </button>
          <button
            onClick={() => setSmokeOpen((v) => !v)}
            disabled={!edit.api_key}
            className="btn-pearl"
            title="跑一次真实 search，验证整条链路"
          >
            {smokeOpen ? "收起搜索" : "试搜索"}
          </button>
        </div>
      </div>

      {/* Inputs */}
      <div className="mt-md grid grid-cols-1 gap-sm md:grid-cols-2">
        <label className="block md:col-span-2">
          <span className="mb-xxs block text-caption-strong text-ink">API key</span>
          <input
            type="text"
            spellCheck={false}
            autoComplete="off"
            className="input-flat font-mono"
            placeholder="sk-... 直接粘贴明文"
            value={edit.api_key}
            onChange={(ev) => onChange({ api_key: ev.target.value })}
          />
        </label>

        <label className="block md:col-span-2">
          <span className="mb-xxs block text-caption-strong text-ink">默认模型</span>
          <input
            list={`models-${cred.provider}`}
            className="input-flat"
            placeholder={info.modelHint}
            value={edit.default_model}
            onChange={(ev) => onChange({ default_model: ev.target.value })}
          />
          <datalist id={`models-${cred.provider}`}>
            {info.modelOptions.map((m) => (
              <option key={m} value={m} />
            ))}
          </datalist>
        </label>

        <label className="block md:col-span-2">
          <span className="mb-xxs flex items-baseline justify-between text-caption-strong text-ink">
            <span>Base URL · 留空 = 默认</span>
            {info.baseUrlOptions && info.baseUrlOptions.length > 0 && (
              <span className="ml-xs flex flex-wrap gap-xxs text-caption text-ink-muted-48">
                {info.baseUrlOptions.map((b) => (
                  <button
                    key={b.url}
                    type="button"
                    className="rounded-sm px-1.5 py-0.5 hover:bg-pearl hover:text-ink"
                    onClick={() => onChange({ base_url: b.url })}
                    title={b.url}
                  >
                    {b.label}
                  </button>
                ))}
                <button
                  type="button"
                  className="rounded-sm px-1.5 py-0.5 hover:bg-pearl hover:text-ink"
                  onClick={() => onChange({ base_url: "" })}
                  title="清空，使用默认 base URL"
                >
                  清空
                </button>
              </span>
            )}
          </span>
          <input
            list={`base-urls-${cred.provider}`}
            className="input-flat font-mono"
            placeholder={info.baseUrlHint || "（保持空白即使用默认 endpoint）"}
            value={edit.base_url}
            onChange={(ev) => onChange({ base_url: ev.target.value })}
            spellCheck={false}
          />
          {info.baseUrlOptions && (
            <datalist id={`base-urls-${cred.provider}`}>
              {info.baseUrlOptions.map((b) => (
                <option key={b.url} value={b.url}>{b.label}</option>
              ))}
            </datalist>
          )}
          {info.baseUrlNote && (
            <p className="mt-xxs text-caption text-ink-muted-48">{info.baseUrlNote}</p>
          )}
        </label>
      </div>

      {/* Test result */}
      {testMsg && (
        <div className="mt-sm rounded-sm bg-parchment px-md py-sm text-caption text-ink-muted-80">
          <span className="font-mono">{testMsg}</span>
        </div>
      )}
      {cred.test_message && !testMsg && (
        <div className="mt-sm rounded-sm bg-parchment px-md py-sm text-caption text-ink-muted-48">
          上次测试：<span className="font-mono">{cred.test_message}</span>
        </div>
      )}

      {/* Smoke panel */}
      {smokeOpen && (
        <div className="mt-md border-t border-hairline pt-md">
          <div className="flex gap-xs">
            <input
              className="input-flat flex-1"
              placeholder="测试查询"
              value={smokeQuery}
              onChange={(ev) => setSmokeQuery(ev.target.value)}
            />
            <button
              onClick={runSmoke}
              disabled={smokeBusy}
              className="btn-primary !py-2 !px-5 text-caption-strong"
            >
              {smokeBusy ? "搜索中…" : "搜索"}
            </button>
          </div>
          {smokeResult && (
            <div
              className={
                "mt-sm rounded-tile-lg border p-md text-caption " +
                (smokeResult.success
                  ? "border-status-success/30 bg-status-success/5"
                  : "border-status-danger/30 bg-status-danger/5")
              }
            >
              <div className="flex flex-wrap gap-x-md gap-y-xxs text-ink-muted-80">
                <span>
                  <span className="text-caption-strong text-ink">结果：</span>
                  {smokeResult.success ? "✓" : "✗"}
                </span>
                <span>
                  <span className="text-caption-strong text-ink">耗时：</span>
                  {smokeResult.duration_ms}ms
                </span>
                <span>
                  <span className="text-caption-strong text-ink">条数：</span>
                  {smokeResult.snippets_count}
                </span>
                {smokeResult.trace && (
                  <>
                    <span>
                      <span className="text-caption-strong text-ink">tokens：</span>
                      {(smokeResult.trace.tokens_input || 0) +
                        (smokeResult.trace.tokens_output || 0)}
                    </span>
                    <span>
                      <span className="text-caption-strong text-ink">花费：</span>
                      ${(smokeResult.trace.cost_usd || 0).toFixed(5)}
                    </span>
                  </>
                )}
              </div>
              {smokeResult.error && (
                <div className="mt-xs break-all text-status-danger">
                  <span className="text-caption-strong">错误：</span>{smokeResult.error}
                </div>
              )}
              {smokeResult.sample && smokeResult.sample.length > 0 && (
                <ol className="mt-sm list-decimal space-y-xs pl-md">
                  {smokeResult.sample.map((s: any, i: number) => (
                    <li key={i}>
                      <span className="text-body-strong text-ink">
                        {s.title || s.source_domain || "(无标题)"}
                      </span>
                      {s.url && (
                        <a
                          href={s.url}
                          target="_blank"
                          rel="noreferrer"
                          className="ml-1 text-primary"
                        >
                          ↗
                        </a>
                      )}
                      <div className="text-ink-muted-80">{s.snippet}</div>
                    </li>
                  ))}
                </ol>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
