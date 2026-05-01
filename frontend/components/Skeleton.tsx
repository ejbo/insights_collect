"use client";

/** A shimmering placeholder block. Use sparingly — only while we genuinely
 * have nothing better to show.  Animation is a slow gradient sweep so it
 * doesn't compete with real content. */
export function Skeleton({
  className = "",
  rounded = "rounded-md",
}: {
  className?: string;
  rounded?: string;
}) {
  return (
    <div
      aria-hidden
      className={`relative overflow-hidden bg-pearl ${rounded} ${className}`}
    >
      <div className="absolute inset-0 animate-[shimmer_1.6s_linear_infinite] bg-[linear-gradient(90deg,transparent,rgba(255,255,255,0.55),transparent)] bg-[length:200%_100%]" />
    </div>
  );
}

/** "Working…" pill that pulses gently — drop this anywhere a long-running
 * task is happening, instead of a static "loading" text. */
export function Pulse({
  label = "处理中",
  tone = "primary",
}: {
  label?: string;
  tone?: "primary" | "ink" | "muted";
}) {
  const colorClass: Record<typeof tone, string> = {
    primary: "text-primary bg-primary/10",
    ink: "text-ink bg-ink/10",
    muted: "text-ink-muted-80 bg-pearl",
  } as any;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-pill px-2.5 py-0.5 text-caption-strong ${colorClass[tone]}`}
    >
      <span className="relative flex h-1.5 w-1.5">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-current opacity-60" />
        <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-current" />
      </span>
      {label}
    </span>
  );
}

/** A small set of common shapes you'll re-use most pages. */
export function SkeletonRow({ cols = 5 }: { cols?: number }) {
  return (
    <li className="flex items-center gap-md px-lg py-md">
      {Array.from({ length: cols }).map((_, i) => (
        <Skeleton
          key={i}
          className={
            i === 0
              ? "h-4 w-10"
              : i === 1
                ? "h-4 flex-1"
                : "h-4 w-20"
          }
        />
      ))}
    </li>
  );
}

export function SkeletonCard({ lines = 3 }: { lines?: number }) {
  return (
    <div className="rounded-tile-lg border border-hairline bg-canvas p-md">
      <Skeleton className="h-4 w-1/3" />
      <div className="mt-sm space-y-2">
        {Array.from({ length: lines }).map((_, i) => (
          <Skeleton
            key={i}
            className={i === lines - 1 ? "h-3 w-2/3" : "h-3 w-full"}
          />
        ))}
      </div>
    </div>
  );
}
