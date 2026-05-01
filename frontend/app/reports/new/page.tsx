"use client";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { api, fetcher } from "../../../lib/api";
import type {
  ClaudeOptions,
  GeminiOptions,
  GrokOptions,
  ProviderCredentialView,
  QwenOptions,
  ReportTemplate,
} from "../../../lib/types";
import {
  ClaudeOptionsPanel,
  DEFAULT_CLAUDE_OPTIONS,
} from "../../../components/ClaudeOptionsPanel";
import {
  GeminiOptionsPanel,
  DEFAULT_GEMINI_OPTIONS,
} from "../../../components/GeminiOptionsPanel";
import {
  GrokOptionsPanel,
  DEFAULT_GROK_OPTIONS,
} from "../../../components/GrokOptionsPanel";
import {
  QwenOptionsPanel,
  DEFAULT_QWEN_OPTIONS,
} from "../../../components/QwenOptionsPanel";
import { NumberField } from "../../../components/NumberField";

const ALL_PROVIDERS = ["anthropic", "openai", "gemini", "grok", "perplexity", "qwen", "deepseek"];

const QUICK_RANGES = [
  { label: "近 7 天", days: 7 },
  { label: "近 30 天", days: 30 },
  { label: "近 90 天", days: 90 },
  { label: "近 180 天", days: 180 },
];

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <label className="mb-xs block text-caption-strong text-ink">{children}</label>
  );
}

export default function NewReportPage() {
  const router = useRouter();
  const { data: templates } = useSWR<ReportTemplate[]>("/api/templates", fetcher);
  const { data: creds } = useSWR<ProviderCredentialView[]>("/api/settings/providers", fetcher);

  const today = new Date();
  const fmt = (d: Date) => d.toISOString().slice(0, 10);
  const thirtyAgo = new Date(today);
  thirtyAgo.setDate(today.getDate() - 30);

  const [title, setTitle] = useState("");
  const [topicsRaw, setTopicsRaw] = useState("");
  const [startDate, setStartDate] = useState(fmt(thirtyAgo));
  const [endDate, setEndDate] = useState(fmt(today));
  const [providers, setProviders] = useState<string[]>([]);
  const [mdTemplateId, setMdTemplateId] = useState<number | "">("");
  const [outlineTemplateId, setOutlineTemplateId] = useState<number | "">("");
  const [costCap, setCostCap] = useState<number | null>(10);
  const [claudeOpts, setClaudeOpts] = useState<ClaudeOptions>(DEFAULT_CLAUDE_OPTIONS);
  const [geminiOpts, setGeminiOpts] = useState<GeminiOptions>(DEFAULT_GEMINI_OPTIONS);
  const [grokOpts, setGrokOpts] = useState<GrokOptions>(DEFAULT_GROK_OPTIONS);
  const [qwenOpts, setQwenOpts] = useState<QwenOptions>(DEFAULT_QWEN_OPTIONS);
  const [providersTouched, setProvidersTouched] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const focusTopics = useMemo(
    () => topicsRaw.split(/[,、，;;;\n]/).map((s) => s.trim()).filter(Boolean),
    [topicsRaw],
  );
  const claudeSelected = providers.includes("anthropic");
  const geminiSelected = providers.includes("gemini");
  const grokSelected = providers.includes("grok");
  const qwenSelected = providers.includes("qwen");

  // Default-check every configured provider (has_key && enabled) on first
  // creds load. Once the user toggles anything, stop overriding their choice.
  useEffect(() => {
    if (!creds || providersTouched) return;
    const configured = creds.filter((c) => c.enabled && c.has_key).map((c) => c.provider);
    setProviders(configured);
  }, [creds, providersTouched]);

  useEffect(() => {
    if (!templates) return;
    setMdTemplateId((cur) =>
      cur !== ""
        ? cur
        : templates.find((t) => t.kind === "md_report" && t.is_default)?.id ??
          templates.find((t) => t.kind === "md_report")?.id ??
          "",
    );
    setOutlineTemplateId((cur) =>
      cur !== ""
        ? cur
        : templates.find((t) => t.kind === "ppt_outline" && t.is_default)?.id ??
          templates.find((t) => t.kind === "ppt_outline")?.id ??
          "",
    );
  }, [templates]);

  function toggleProvider(p: string) {
    setProvidersTouched(true);
    setProviders((cur) => (cur.includes(p) ? cur.filter((x) => x !== p) : [...cur, p]));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setErr(null);
    try {
      const focus = topicsRaw
        .split(/[,、，;；\n]/)
        .map((s) => s.trim())
        .filter(Boolean);
      const providersOptions: Record<string, any> = {};
      if (claudeSelected) {
        providersOptions.anthropic = claudeOpts;
      }
      if (geminiSelected) {
        providersOptions.gemini = geminiOpts;
      }
      if (grokSelected) {
        providersOptions.grok = grokOpts;
      }
      if (qwenSelected) {
        providersOptions.qwen = qwenOpts;
      }
      const body = {
        title,
        focus_topics: focus,
        time_range_start: new Date(startDate + "T00:00:00").toISOString(),
        time_range_end: new Date(endDate + "T23:59:59").toISOString(),
        md_template_id: mdTemplateId || null,
        outline_template_id: outlineTemplateId || null,
        providers_enabled: providers,
        providers_options:
          Object.keys(providersOptions).length > 0 ? providersOptions : null,
        cost_cap_usd: costCap ?? 0,
        max_reflection_rounds: 3,
      };
      const created: any = await api("/api/reports", {
        method: "POST",
        body: JSON.stringify(body),
      });
      router.push(`/reports/${created.id}`);
    } catch (e: any) {
      setErr(String(e.message || e));
    } finally {
      setSubmitting(false);
    }
  }

  const noKeys = creds && creds.filter((c) => c.has_key && c.enabled).length === 0;

  return (
    <form onSubmit={submit} className="mx-auto max-w-text space-y-xl">
      <section className="card-utility space-y-md">
        <div>
          <FieldLabel>标题</FieldLabel>
          <input
            className="input-flat"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
        </div>

        <div>
          <FieldLabel>主题</FieldLabel>
          <textarea
            className="textarea-flat h-24"
            value={topicsRaw}
            onChange={(e) => setTopicsRaw(e.target.value)}
            placeholder="逗号 / 顿号分隔"
          />
        </div>
      </section>

      <section className="card-utility space-y-md">
        <FieldLabel>时间范围</FieldLabel>
        <div className="grid grid-cols-1 gap-md md:grid-cols-3">
          <div>
            <label className="text-caption text-ink-muted-48">开始</label>
            <input
              type="date"
              className="input-flat mt-xxs"
              value={startDate}
              max={endDate}
              onChange={(e) => setStartDate(e.target.value)}
            />
          </div>
          <div>
            <label className="text-caption text-ink-muted-48">结束</label>
            <input
              type="date"
              className="input-flat mt-xxs"
              value={endDate}
              min={startDate}
              onChange={(e) => setEndDate(e.target.value)}
            />
          </div>
          <div>
            <label className="text-caption text-ink-muted-48">花费上限 (USD)</label>
            <NumberField
              className="input-flat mt-xxs"
              min={0}
              step={0.5}
              placeholder="不限"
              value={costCap}
              onChange={setCostCap}
            />
          </div>
        </div>
        <div className="flex flex-wrap gap-xs pt-xxs">
          {QUICK_RANGES.map((p) => (
            <button
              key={p.days}
              type="button"
              className="chip"
              onClick={() => {
                const e = new Date();
                const s = new Date(e);
                s.setDate(e.getDate() - p.days);
                setStartDate(fmt(s));
                setEndDate(fmt(e));
              }}
            >
              {p.label}
            </button>
          ))}
        </div>
      </section>

      <section className="card-utility space-y-md">
        <div className="flex items-center justify-between">
          <FieldLabel>Provider</FieldLabel>
          <span className="text-caption text-ink-muted-48">
            已选 {providers.length}
          </span>
        </div>
        <div className="flex flex-wrap gap-xs">
          {ALL_PROVIDERS.map((p) => {
            const c = creds?.find((x) => x.provider === p);
            const hasKey = !!c?.has_key;
            const selected = providers.includes(p);
            if (!hasKey) {
              return (
                <span key={p} className="chip-disabled">
                  {p}
                </span>
              );
            }
            return (
              <button
                key={p}
                type="button"
                onClick={() => toggleProvider(p)}
                className={selected ? "chip chip-selected" : "chip"}
              >
                {p}
              </button>
            );
          })}
        </div>
        {noKeys && (
          <p className="text-caption text-status-danger">
            没有已启用的 key ·{" "}
            <a href="/settings" className="text-primary">
              去设置
            </a>
          </p>
        )}
      </section>

      {claudeSelected && (
        <ClaudeOptionsPanel
          value={claudeOpts}
          onChange={setClaudeOpts}
          topicCount={focusTopics.length}
        />
      )}

      {geminiSelected && (
        <GeminiOptionsPanel
          value={geminiOpts}
          onChange={setGeminiOpts}
          topicCount={focusTopics.length}
        />
      )}

      {grokSelected && (
        <GrokOptionsPanel
          value={grokOpts}
          onChange={setGrokOpts}
          topicCount={focusTopics.length}
        />
      )}

      {qwenSelected && (
        <QwenOptionsPanel
          value={qwenOpts}
          onChange={setQwenOpts}
          topicCount={focusTopics.length}
        />
      )}

      <section className="card-utility space-y-md">
        <FieldLabel>模板</FieldLabel>
        <div className="grid grid-cols-1 gap-md md:grid-cols-2">
          <div>
            <label className="text-caption text-ink-muted-48">Markdown 模板</label>
            <select
              className="input-flat mt-xxs"
              value={mdTemplateId}
              onChange={(e) =>
                setMdTemplateId(e.target.value ? Number(e.target.value) : "")
              }
            >
              <option value="">— 默认 —</option>
              {(templates || [])
                .filter((t) => t.kind === "md_report")
                .map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                    {t.is_default ? "  · 默认" : ""}
                  </option>
                ))}
            </select>
          </div>
          <div>
            <label className="text-caption text-ink-muted-48">PPT 大纲模板</label>
            <select
              className="input-flat mt-xxs"
              value={outlineTemplateId}
              onChange={(e) =>
                setOutlineTemplateId(e.target.value ? Number(e.target.value) : "")
              }
            >
              <option value="">— 默认 —</option>
              {(templates || [])
                .filter((t) => t.kind === "ppt_outline")
                .map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                    {t.is_default ? "  · 默认" : ""}
                  </option>
                ))}
            </select>
          </div>
        </div>
      </section>

      {err && (
        <div className="rounded-tile-lg border border-status-danger/30 bg-status-danger/10 px-lg py-md text-caption text-status-danger">
          {err}
        </div>
      )}

      <div className="flex items-center gap-sm">
        <button
          type="submit"
          disabled={
            submitting ||
            providers.length === 0 ||
            title.trim() === "" ||
            focusTopics.length === 0
          }
          className="btn-primary"
        >
          {submitting ? "提交中…" : "生成报告"}
        </button>
        <button
          type="button"
          onClick={() => router.back()}
          className="btn-secondary-pill"
        >
          取消
        </button>
      </div>
    </form>
  );
}
