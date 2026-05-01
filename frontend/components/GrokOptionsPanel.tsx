"use client";
import type { GrokOptions } from "../lib/types";
import { NumberField } from "./NumberField";

/* ---------------- Cost estimator ----------------
 * grok-4.20-reasoning pricing assumed at $3 / $15 per 1M tokens.
 * Per topic, we approximate:
 *   pass 1 (event): 1k system + 1k query + reasoning ~ 6k → in 8k, out 4k
 *   pass 2 (people, optional): in 8k (incl. 1.5k carry) + out 4k
 * image / video understanding adds ~2k input per used media.
 */
function passEstimate(o: GrokOptions): { inT: number; outT: number } {
  const baseIn = 8000;
  const baseOut = 4000;
  const mediaPad =
    (o.enable_image_understanding ? 1500 : 0) +
    (o.enable_video_understanding ? 2500 : 0);
  return { inT: baseIn + mediaPad, outT: baseOut };
}

export function estimateGrokCostPerTopic(o: GrokOptions): { low: number; high: number } {
  const { inT, outT } = passEstimate(o);
  const passes = o.enable_dual_pass ? 2 : 1;
  // grok-4.20-reasoning: $3 in / $15 out per 1M
  const point = passes * (inT * 3 + outT * 15) / 1_000_000;
  return { low: point * 0.6, high: point * 1.4 };
}

export const DEFAULT_GROK_OPTIONS: GrokOptions = {
  model: null,
  allowed_x_handles: null,
  excluded_x_handles: null,
  enable_image_understanding: true,
  enable_video_understanding: true,
  enable_dual_pass: true,
  max_candidate_handles: 8,
};

/* ---------------- Component ---------------- */

function parseHandles(s: string): string[] | null {
  const arr = s
    .split(/[,\n\s]+/)
    .map((x) => x.trim().replace(/^@/, ""))
    .filter(Boolean);
  return arr.length > 0 ? arr.slice(0, 10) : null;
}

export function GrokOptionsPanel({
  value,
  onChange,
  topicCount,
}: {
  value: GrokOptions;
  onChange: (next: GrokOptions) => void;
  topicCount: number;
}) {
  const cost = estimateGrokCostPerTopic(value);
  const totalLow = cost.low * Math.max(1, topicCount);
  const totalHigh = cost.high * Math.max(1, topicCount);

  function patch<K extends keyof GrokOptions>(k: K, v: GrokOptions[K]) {
    onChange({ ...value, [k]: v });
  }

  const allowedPinned = (value.allowed_x_handles?.length ?? 0) > 0;

  return (
    <section className="card-utility space-y-md">
      <div className="flex items-baseline justify-between">
        <div>
          <h3 className="font-display text-tagline text-ink">
            Grok options · grok-4.20-reasoning · X 搜索
          </h3>
          <p className="mt-xxs text-caption text-ink-muted-48">
            事 ↔ 人 双向挖掘 · 阅读视频 / 图片 · inline citations
          </p>
        </div>
        <button
          type="button"
          onClick={() => onChange(DEFAULT_GROK_OPTIONS)}
          className="btn-pearl"
        >
          Reset to defaults
        </button>
      </div>

      {/* Dual-pass toggle */}
      <label className="inline-flex items-center gap-xs text-caption-strong text-ink">
        <input
          type="checkbox"
          checked={value.enable_dual_pass}
          onChange={(e) => patch("enable_dual_pass", e.target.checked)}
          className="accent-primary"
          disabled={allowedPinned}
        />
        启用双向挖掘 · 第 1 轮事→人，第 2 轮人→事
        {allowedPinned && (
          <span className="ml-xs text-caption text-ink-muted-48">
            （已锁定 handle，跳过第 2 轮）
          </span>
        )}
      </label>

      {/* Media understanding — Grok-4 reads images / videos in posts
          natively when it visits them. There is no Live Search-level toggle,
          so these knobs were removed. */}

      {/* Candidate handle budget */}
      <div>
        <label className="mb-xs block text-caption-strong text-ink">
          第 2 轮候选人物上限（1-10）
        </label>
        <NumberField
          className="input-flat w-32"
          min={1}
          max={10}
          value={value.max_candidate_handles}
          onChange={(n) => patch("max_candidate_handles", Math.max(1, Math.min(10, n ?? 8)))}
        />
        <p className="mt-xxs text-caption text-ink-muted-48">
          第 1 轮挖出的关键人物数量；越多越贵但覆盖越广。
        </p>
      </div>

      {/* Handle filters */}
      <div className="grid grid-cols-1 gap-md md:grid-cols-2">
        <div>
          <label className="mb-xxs block text-caption text-ink-muted-48">
            Allowed handles · 锁定到这些 X 账号（≤10）
          </label>
          <textarea
            className="textarea-flat h-20 font-mono"
            placeholder="逗号或换行分隔，如 elonmusk, sundarpichai"
            value={(value.allowed_x_handles || []).join(", ")}
            onChange={(e) => patch("allowed_x_handles", parseHandles(e.target.value))}
          />
        </div>
        <div>
          <label className="mb-xxs block text-caption text-ink-muted-48">
            Excluded handles · 排除（≤10，与 allowed 互斥）
          </label>
          <textarea
            className="textarea-flat h-20 font-mono"
            placeholder="逗号或换行分隔"
            value={(value.excluded_x_handles || []).join(", ")}
            onChange={(e) => patch("excluded_x_handles", parseHandles(e.target.value))}
            disabled={allowedPinned}
          />
        </div>
      </div>

      {/* Model override */}
      <details className="text-caption">
        <summary className="cursor-pointer text-caption-strong text-ink">
          Advanced · model 覆盖
        </summary>
        <div className="mt-md">
          <label className="mb-xxs block text-caption text-ink-muted-48">
            Model override
          </label>
          <input
            list="grok-models"
            className="input-flat font-mono"
            placeholder="default: grok-4.20-reasoning"
            value={value.model || ""}
            onChange={(e) => patch("model", e.target.value || null)}
          />
          <datalist id="grok-models">
            <option value="grok-4.20-reasoning" />
            <option value="grok-4" />
          </datalist>
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
          基于 grok-4.20-reasoning 估价（$3 / $15 per 1M tokens），
          按 {value.enable_dual_pass ? "双轮" : "单轮"} × 媒体阅读 粗估。
          实际花费见报告详情页 Provider calls 明细。
        </p>
      </div>
    </section>
  );
}
