"use client";
import type { ClaudeOptions } from "../lib/types";
import { NumberField } from "./NumberField";

/* ---------------- Cost estimator ---------------- */
//
// Opus 4.7 pricing: $5 / $25 per 1M tokens (input / output).
// Per topic, we approximate:
//   input  ≈ 2k system + 1k query + 4k * (max_uses + max_fetches)  (Claude includes
//           web_search results as input tokens on subsequent rounds)
//   output ≈ 2k base + 1.5k * effort_mult * (max_uses + max_fetches)
// effort_mult: low 0.3, medium 0.6, high 1.0, xhigh 1.5, max 2.0
//
const EFFORT_MULT: Record<ClaudeOptions["effort"], number> = {
  low: 0.3, medium: 0.6, high: 1.0, xhigh: 1.5, max: 2.0,
};

export function estimateClaudeCostPerTopic(o: ClaudeOptions): { low: number; high: number } {
  const tools = (o.enable_web_search ? o.max_uses : 0) + (o.enable_web_fetch ? o.max_fetches : 0);
  const eff = EFFORT_MULT[o.effort] ?? 1.0;
  const inputTokens = 2000 + 1000 + 4000 * tools;
  const outputTokens = 2000 + 1500 * eff * Math.max(1, tools);
  // Opus 4.7: $5 in / $25 out per 1M
  const point = (inputTokens * 5 + outputTokens * 25) / 1_000_000;
  return { low: point * 0.6, high: point * 1.4 };
}

export const DEFAULT_CLAUDE_OPTIONS: ClaudeOptions = {
  effort: "low",
  max_uses: 1,
  max_fetches: 0,
  task_budget_tokens: null,
  thinking_display: "summarized",
  enable_web_search: true,
  enable_web_fetch: false,
  allowed_domains: null,
  blocked_domains: null,
  user_location_country: null,
  model: null,
};

/* ---------------- Component ---------------- */

export function ClaudeOptionsPanel({
  value,
  onChange,
  topicCount,
}: {
  value: ClaudeOptions;
  onChange: (next: ClaudeOptions) => void;
  topicCount: number;
}) {
  const cost = estimateClaudeCostPerTopic(value);
  const totalLow = cost.low * Math.max(1, topicCount);
  const totalHigh = cost.high * Math.max(1, topicCount);

  function patch<K extends keyof ClaudeOptions>(k: K, v: ClaudeOptions[K]) {
    onChange({ ...value, [k]: v });
  }

  function parseDomains(s: string): string[] | null {
    const arr = s.split(/[,\n\s]+/).map((x) => x.trim()).filter(Boolean);
    return arr.length > 0 ? arr : null;
  }

  return (
    <section className="card-utility space-y-md">
      <div className="flex items-baseline justify-between">
        <div>
          <h3 className="font-display text-tagline text-ink">
            Claude options · Opus 4.7
          </h3>
          <p className="mt-xxs text-caption text-ink-muted-48">
            自定义 effort / web 工具 / task budget — 影响召回质量与花费
          </p>
        </div>
        <button
          type="button"
          onClick={() => onChange(DEFAULT_CLAUDE_OPTIONS)}
          className="btn-pearl"
        >
          Reset to defaults
        </button>
      </div>

      {/* Effort */}
      <div>
        <label className="mb-xs block text-caption-strong text-ink">
          Effort · 思考深度与 token 花费
        </label>
        <div className="flex flex-wrap gap-xs">
          {(["low", "medium", "high", "xhigh", "max"] as const).map((e) => {
            const active = value.effort === e;
            const help: Record<typeof e, string> = {
              low: "最省钱",
              medium: "平衡",
              high: "推荐",
              xhigh: "agentic 最佳",
              max: "极限智能",
            } as any;
            return (
              <button
                key={e}
                type="button"
                onClick={() => patch("effort", e)}
                className={active ? "chip chip-selected" : "chip"}
                title={help[e]}
              >
                {e}
                {active && <span className="ml-1 text-ink-muted-48">· {help[e]}</span>}
              </button>
            );
          })}
        </div>
      </div>

      {/* Tool toggles + counts — web_fetch retired, only web_search exposed */}
      <div className="space-y-xs">
        <label className="inline-flex items-center gap-xs text-caption-strong text-ink">
          <input
            type="checkbox"
            checked={value.enable_web_search}
            onChange={(e) => patch("enable_web_search", e.target.checked)}
            className="accent-primary"
          />
          web_search · 让 Claude 自行搜网
        </label>
        {value.enable_web_search && (
          <div>
            <label className="mb-xxs block text-caption text-ink-muted-48">
              每条子查询里最多调用几次 web_search · 单次返回 ~5–10 条
            </label>
            <NumberField
              className="input-flat md:max-w-xs"
              min={1}
              max={10}
              value={value.max_uses}
              onChange={(n) => patch("max_uses", n ?? 1)}
            />
          </div>
        )}
      </div>

      {/* Task budget + thinking */}
      <div className="grid grid-cols-1 gap-md md:grid-cols-2">
        <div>
          <label className="mb-xs block text-caption-strong text-ink">
            Task budget tokens · 可选 (≥ 20000)
          </label>
          <NumberField
            className="input-flat"
            step={5000}
            min={0}
            placeholder="留空 = 不启用"
            value={value.task_budget_tokens}
            onChange={(n) => patch("task_budget_tokens", n)}
          />
          <p className="mt-xxs text-caption text-ink-muted-48">
            告诉 Claude 它在一个 agentic 循环里有多少 token 可花，模型自我节制。&lt;20000 会被忽略。
          </p>
        </div>
        <div>
          <label className="mb-xs block text-caption-strong text-ink">
            Thinking display
          </label>
          <select
            className="input-flat"
            value={value.thinking_display}
            onChange={(e) =>
              patch("thinking_display", e.target.value as ClaudeOptions["thinking_display"])
            }
          >
            <option value="summarized">summarized · 显示思考摘要</option>
            <option value="omitted">omitted · 不传回思考内容</option>
          </select>
          <p className="mt-xxs text-caption text-ink-muted-48">
            Opus 4.7 默认 omitted；选 summarized 才能在 UI 看到推理摘要。
          </p>
        </div>
      </div>

      {/* Domain filters (advanced) */}
      <details className="text-caption">
        <summary className="cursor-pointer text-caption-strong text-ink">
          Advanced · domain 过滤 / model 覆盖
        </summary>
        <div className="mt-md grid grid-cols-1 gap-md md:grid-cols-2">
          <div>
            <label className="mb-xxs block text-caption text-ink-muted-48">
              Allowed domains
            </label>
            <textarea
              className="textarea-flat h-20 font-mono"
              placeholder="逗号或换行分隔"
              value={(value.allowed_domains || []).join(", ")}
              onChange={(e) => patch("allowed_domains", parseDomains(e.target.value))}
            />
          </div>
          <div>
            <label className="mb-xxs block text-caption text-ink-muted-48">
              Blocked domains
            </label>
            <textarea
              className="textarea-flat h-20 font-mono"
              placeholder="逗号或换行分隔"
              value={(value.blocked_domains || []).join(", ")}
              onChange={(e) => patch("blocked_domains", parseDomains(e.target.value))}
            />
          </div>
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
              list="claude-models"
              className="input-flat font-mono"
              placeholder="default: claude-opus-4-7"
              value={value.model || ""}
              onChange={(e) => patch("model", e.target.value || null)}
            />
            <datalist id="claude-models">
              <option value="claude-opus-4-7" />
              <option value="claude-opus-4-6" />
              <option value="claude-sonnet-4-6" />
              <option value="claude-haiku-4-5-20251001" />
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
          基于 Opus 4.7 定价 ($5 / $25 per 1M tokens)，按 effort × 工具调用次数粗估。
          实际费用见报告详情页 Provider calls。
        </p>
      </div>
    </section>
  );
}
