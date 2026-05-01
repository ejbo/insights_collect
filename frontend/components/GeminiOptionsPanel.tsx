"use client";
import type { GeminiOptions } from "../lib/types";
import { NumberField } from "./NumberField";

/* ---------------- Cost estimator ----------------
 * gemini-3.1-pro-preview pricing assumed at $1.5 / $6 per 1M tokens
 * (preview tier; will be re-baselined when GA pricing is published).
 *
 * Per topic, we approximate:
 *   input  ≈ 2k system + 1k query + 4k * (search ? 1 : 0)
 *   output ≈ 2k base + thinking_budget_factor * 1.5k
 *
 * thinking_budget_factor:
 *   -1 (dynamic) → 1.0
 *    0 (off)     → 0.3
 *    N (fixed)   → clamp(N/8000, 0.3, 4.0)
 */
function thinkingFactor(budget: number): number {
  if (budget === 0) return 0.3;
  if (budget < 0) return 1.0;
  return Math.max(0.3, Math.min(4.0, budget / 8000));
}

export function estimateGeminiCostPerTopic(o: GeminiOptions): { low: number; high: number } {
  const search = o.enable_search ? 1 : 0;
  const f = thinkingFactor(o.thinking_budget);
  const inputTokens = 2000 + 1000 + 4000 * search;
  const outputTokens = 2000 + 1500 * f;
  // gemini-3.1-pro-preview: $1.5 in / $6 out per 1M
  const point = (inputTokens * 1.5 + outputTokens * 6) / 1_000_000;
  return { low: point * 0.6, high: point * 1.4 };
}

export const DEFAULT_GEMINI_OPTIONS: GeminiOptions = {
  model: null,
  thinking_budget: -1,
  temperature: null,
  max_output_tokens: 8192,
  enable_search: true,
  user_location_country: null,
  max_search_queries: 3,
  max_grounding_chunks: 8,
};

/* ---------------- Component ---------------- */

const THINKING_PRESETS: { label: string; value: number; help: string }[] = [
  { label: "Dynamic", value: -1, help: "由模型决定" },
  { label: "Off", value: 0, help: "关闭思考" },
  { label: "1k", value: 1024, help: "轻量思考" },
  { label: "4k", value: 4096, help: "中等" },
  { label: "16k", value: 16384, help: "深度推理" },
  { label: "32k", value: 32768, help: "最深" },
];

export function GeminiOptionsPanel({
  value,
  onChange,
  topicCount,
}: {
  value: GeminiOptions;
  onChange: (next: GeminiOptions) => void;
  topicCount: number;
}) {
  const cost = estimateGeminiCostPerTopic(value);
  const totalLow = cost.low * Math.max(1, topicCount);
  const totalHigh = cost.high * Math.max(1, topicCount);

  function patch<K extends keyof GeminiOptions>(k: K, v: GeminiOptions[K]) {
    onChange({ ...value, [k]: v });
  }

  const isCustomBudget =
    value.thinking_budget !== -1 &&
    value.thinking_budget !== 0 &&
    !THINKING_PRESETS.find((p) => p.value === value.thinking_budget);

  return (
    <section className="card-utility space-y-md">
      <div className="flex items-baseline justify-between">
        <div>
          <h3 className="font-display text-tagline text-ink">
            Gemini options · 3.1 Pro Preview
          </h3>
          <p className="mt-xxs text-caption text-ink-muted-48">
            Google Search grounding · 自定义思考预算 / 温度 / 输出长度
          </p>
        </div>
        <button
          type="button"
          onClick={() => onChange(DEFAULT_GEMINI_OPTIONS)}
          className="btn-pearl"
        >
          Reset to defaults
        </button>
      </div>

      {/* Search toggle */}
      <label className="inline-flex items-center gap-xs text-caption-strong text-ink">
        <input
          type="checkbox"
          checked={value.enable_search}
          onChange={(e) => patch("enable_search", e.target.checked)}
          className="accent-primary"
        />
        启用 google_search 工具 · 让 Gemini 自行检索网络
      </label>

      {/* Search-volume caps (only meaningful when search enabled) */}
      {value.enable_search && (
        <div className="grid grid-cols-1 gap-md md:grid-cols-2">
          <div>
            <label className="mb-xs block text-caption-strong text-ink">
              最大 google_search 调用次数
            </label>
            <NumberField
              className="input-flat"
              min={1}
              max={10}
              step={1}
              value={value.max_search_queries}
              onChange={(n) => patch("max_search_queries", n ?? 3)}
            />
            <p className="mt-xxs text-caption text-ink-muted-48">
              软上限（写在 prompt 里让模型自我约束）。默认 3，越小越省钱。
            </p>
          </div>
          <div>
            <label className="mb-xs block text-caption-strong text-ink">
              保留 grounding 引用条数
            </label>
            <NumberField
              className="input-flat"
              min={1}
              max={30}
              step={1}
              value={value.max_grounding_chunks}
              onChange={(n) => patch("max_grounding_chunks", n ?? 8)}
            />
            <p className="mt-xxs text-caption text-ink-muted-48">
              落库前对 grounding_chunks 截断，避免长尾低相关链接。
            </p>
          </div>
        </div>
      )}

      {/* Thinking budget */}
      <div>
        <label className="mb-xs block text-caption-strong text-ink">
          Thinking budget · 思考 token 预算
        </label>
        <div className="flex flex-wrap gap-xs">
          {THINKING_PRESETS.map((p) => {
            const active = !isCustomBudget && value.thinking_budget === p.value;
            return (
              <button
                key={p.value}
                type="button"
                onClick={() => patch("thinking_budget", p.value)}
                className={active ? "chip chip-selected" : "chip"}
                title={p.help}
              >
                {p.label}
                {active && <span className="ml-1 text-ink-muted-48">· {p.help}</span>}
              </button>
            );
          })}
          {isCustomBudget && (
            <span className="chip chip-selected">
              custom · {value.thinking_budget}
            </span>
          )}
        </div>
        <NumberField
          className="input-flat mt-xs"
          min={0}
          max={32768}
          step={512}
          placeholder="自定义 token 数 (128-32768)"
          value={value.thinking_budget < 0 ? null : isCustomBudget ? value.thinking_budget : null}
          onChange={(n) => {
            if (n === null) return;
            patch("thinking_budget", n);
          }}
        />
        <p className="mt-xxs text-caption text-ink-muted-48">
          -1 = 动态（推荐）；0 = 关闭思考；128-32768 = 固定预算。仅 Gemini 2.5+ 支持。
        </p>
      </div>

      {/* Temperature + max_output_tokens */}
      <div className="grid grid-cols-1 gap-md md:grid-cols-2">
        <div>
          <label className="mb-xs block text-caption-strong text-ink">
            Temperature · 创造性 (可选 0.0-2.0)
          </label>
          <NumberField
            className="input-flat"
            min={0}
            max={2}
            step={0.1}
            placeholder="留空 = 默认 1.0"
            value={value.temperature}
            onChange={(n) => patch("temperature", n)}
          />
        </div>
        <div>
          <label className="mb-xs block text-caption-strong text-ink">
            Max output tokens
          </label>
          <NumberField
            className="input-flat"
            min={512}
            max={32768}
            step={512}
            value={value.max_output_tokens}
            onChange={(n) => patch("max_output_tokens", n ?? 8192)}
          />
        </div>
      </div>

      {/* Advanced */}
      <details className="text-caption">
        <summary className="cursor-pointer text-caption-strong text-ink">
          Advanced · location / model override
        </summary>
        <div className="mt-md grid grid-cols-1 gap-md md:grid-cols-2">
          <div>
            <label className="mb-xxs block text-caption text-ink-muted-48">
              User location country (ISO-3166)
            </label>
            <input
              className="input-flat font-mono"
              placeholder="CN / US / JP …"
              value={value.user_location_country || ""}
              onChange={(e) => patch("user_location_country", e.target.value || null)}
            />
          </div>
          <div>
            <label className="mb-xxs block text-caption text-ink-muted-48">
              Model override
            </label>
            <input
              list="gemini-models"
              className="input-flat font-mono"
              placeholder="default: gemini-3.1-pro-preview"
              value={value.model || ""}
              onChange={(e) => patch("model", e.target.value || null)}
            />
            <datalist id="gemini-models">
              <option value="gemini-3.1-pro-preview" />
              <option value="gemini-2.5-pro" />
              <option value="gemini-2.5-flash" />
            </datalist>
          </div>
        </div>
      </details>

      {/* Cost estimate */}
      <div className="rounded-tile-lg border border-hairline bg-pearl px-md py-sm">
        <div className="flex flex-wrap items-baseline gap-x-md gap-y-xxs text-caption">
          <span className="text-caption-strong text-ink">预计费用</span>
          <span className="text-ink-muted-80 tabular-nums">
            每个主题 ${cost.low.toFixed(3)} – ${cost.high.toFixed(3)}
          </span>
          <span className="text-ink-muted-48">·</span>
          <span className="text-ink-muted-80 tabular-nums">
            {topicCount} 个主题合计{" "}
            <span className="text-caption-strong text-ink">
              ${totalLow.toFixed(3)} – ${totalHigh.toFixed(3)}
            </span>
          </span>
        </div>
        <p className="mt-xxs text-caption text-ink-muted-48">
          基于 gemini-3.1-pro-preview 估价 ($1.5 / $6 per 1M tokens)，
          按思考预算 × 是否检索粗估。实际费用见报告详情页 Provider calls。
        </p>
      </div>
    </section>
  );
}
