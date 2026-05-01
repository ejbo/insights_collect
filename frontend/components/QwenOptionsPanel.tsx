"use client";
import type { QwenOptions } from "../lib/types";
import { NumberField } from "./NumberField";

/* ---------------- Cost estimator ----------------
 * qwen3.6-plus pricing assumed at $0.4 / $1.2 per 1M tokens (qwen-plus tier).
 * Per topic, we approximate:
 *   input  ≈ 1.5k system + 1k query + 3k * (search ? 1 : 0)
 *   output ≈ 2k base + thinking ? 2k : 0
 *   strategy 'agent_max' ≈ +1.5x output (web scraping pulls more text in)
 */
function thinkingFactor(enabled: boolean): number {
  return enabled ? 1.0 : 0.4;
}
function strategyFactor(s: QwenOptions["search_strategy"]): number {
  return s === "agent_max" ? 1.5 : 1.0;
}

export function estimateQwenCostPerTopic(o: QwenOptions): { low: number; high: number } {
  const search = o.enable_search ? 1 : 0;
  const tf = thinkingFactor(o.enable_thinking);
  const sf = strategyFactor(o.search_strategy);
  const inputTokens = 1500 + 1000 + 3000 * search;
  const outputTokens = (2000 + 2000 * tf) * sf;
  // qwen3.6-plus: $0.4 in / $1.2 out per 1M
  const point = (inputTokens * 0.4 + outputTokens * 1.2) / 1_000_000;
  return { low: point * 0.6, high: point * 1.4 };
}

export const DEFAULT_QWEN_OPTIONS: QwenOptions = {
  model: null,
  enable_search: true,
  enable_thinking: true,
  search_strategy: "agent",
  max_output_tokens: 8192,
};

/* ---------------- Component ---------------- */

export function QwenOptionsPanel({
  value,
  onChange,
  topicCount,
}: {
  value: QwenOptions;
  onChange: (next: QwenOptions) => void;
  topicCount: number;
}) {
  const cost = estimateQwenCostPerTopic(value);
  const totalLow = cost.low * Math.max(1, topicCount);
  const totalHigh = cost.high * Math.max(1, topicCount);

  function patch<K extends keyof QwenOptions>(k: K, v: QwenOptions[K]) {
    onChange({ ...value, [k]: v });
  }

  return (
    <section className="card-utility space-y-md">
      <div className="flex items-baseline justify-between">
        <div>
          <h3 className="font-display text-tagline text-ink">
            Qwen options · qwen3.6-plus · DashScope web_search
          </h3>
          <p className="mt-xxs text-caption text-ink-muted-48">
            通义千问 web_search 工具 · 思考模式 · agent / agent_max 策略
          </p>
        </div>
        <button
          type="button"
          onClick={() => onChange(DEFAULT_QWEN_OPTIONS)}
          className="btn-pearl"
        >
          Reset to defaults
        </button>
      </div>

      <div className="grid grid-cols-1 gap-md md:grid-cols-2">
        <label className="inline-flex items-center gap-xs text-caption-strong text-ink">
          <input
            type="checkbox"
            checked={value.enable_search}
            onChange={(e) => patch("enable_search", e.target.checked)}
            className="accent-primary"
          />
          启用 web_search 工具
        </label>
        <label className="inline-flex items-center gap-xs text-caption-strong text-ink">
          <input
            type="checkbox"
            checked={value.enable_thinking}
            onChange={(e) => patch("enable_thinking", e.target.checked)}
            className="accent-primary"
          />
          启用 thinking 模式
        </label>
      </div>

      {value.enable_search && (
        <div>
          <label className="mb-xs block text-caption-strong text-ink">
            Search strategy · 搜索深度
          </label>
          <div className="flex flex-wrap gap-xs">
            {(["agent", "agent_max"] as const).map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => patch("search_strategy", s)}
                className={value.search_strategy === s ? "chip chip-selected" : "chip"}
                title={s === "agent" ? "仅检索网页" : "检索 + 抓取正文（更深，需 thinking 模式）"}
              >
                {s === "agent" ? "agent · 仅检索" : "agent_max · 检索 + 抓取正文"}
              </button>
            ))}
          </div>
          <p className="mt-xxs text-caption text-ink-muted-48">
            agent_max 会对结果页进行抓取，相关度更高但费用约 1.5x。
            部分模型只在 thinking 模式下支持 agent_max。
          </p>
        </div>
      )}

      <div>
        <label className="mb-xs block text-caption-strong text-ink">
          Max output tokens
        </label>
        <NumberField
          className="input-flat w-40"
          min={512}
          max={32768}
          step={512}
          value={value.max_output_tokens}
          onChange={(n) => patch("max_output_tokens", n ?? 8192)}
        />
      </div>

      <details className="text-caption">
        <summary className="cursor-pointer text-caption-strong text-ink">
          Advanced · model 覆盖
        </summary>
        <div className="mt-md">
          <label className="mb-xxs block text-caption text-ink-muted-48">
            Model override
          </label>
          <input
            list="qwen-models"
            className="input-flat font-mono"
            placeholder="default: qwen3.6-plus"
            value={value.model || ""}
            onChange={(e) => patch("model", e.target.value || null)}
          />
          <datalist id="qwen-models">
            <option value="qwen3.6-plus" />
            <option value="qwen3.5-plus" />
            <option value="qwen3-max" />
            <option value="qwen3-max-2026-01-23" />
          </datalist>
        </div>
      </details>

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
          基于 qwen3.6-plus 估价（$0.4 / $1.2 per 1M tokens），按 search /
          thinking / strategy 粗估。实际花费见报告详情页 Provider calls 明细。
        </p>
      </div>
    </section>
  );
}
