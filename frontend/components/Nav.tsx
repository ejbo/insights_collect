"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * 单层、毛玻璃、56px 顶栏。
 *   左：品牌点 + 全局链接
 *   右：主 CTA「新建报告」+ 设置
 *   当前页：底部 1px primary 线指示
 */

type NavLink = { href: string; label: string };

const NAV_LINKS: NavLink[] = [
  { href: "/", label: "概览" },
  { href: "/reports", label: "报告" },
  { href: "/experts", label: "专家" },
  { href: "/viewpoints", label: "观点" },
  { href: "/events", label: "事件" },
  { href: "/templates", label: "模板" },
];

function isActive(pathname: string, href: string) {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(href + "/");
}

export function Nav() {
  const pathname = usePathname() ?? "/";

  return (
    <header className="sticky top-0 z-30 border-b border-hairline bg-canvas/80 backdrop-blur-frosted backdrop-saturate-150">
      <div className="mx-auto flex h-14 max-w-grid items-center gap-lg px-lg">
        {/* Brand */}
        <Link
          href="/"
          className="group flex items-center gap-2 transition-opacity hover:opacity-80"
        >
          <span
            aria-hidden
            className="grid h-7 w-7 place-items-center rounded-md bg-ink text-canvas"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M4 12c0-4 4-8 8-8s8 4 8 8-4 8-8 8" />
              <path d="M4 12h8" />
              <path d="M12 4v16" />
            </svg>
          </span>
          <span className="font-display text-tagline tracking-tight text-ink">
            Insights Collect
          </span>
        </Link>

        {/* Primary nav */}
        <nav className="hidden flex-1 items-center justify-center md:flex">
          <ul className="flex items-center gap-1">
            {NAV_LINKS.map((l) => {
              const active = isActive(pathname, l.href);
              return (
                <li key={l.href}>
                  <Link
                    href={l.href}
                    className={
                      "relative inline-flex items-center rounded-md px-3 py-1.5 text-button-utility transition-colors " +
                      (active
                        ? "text-ink"
                        : "text-ink-muted-48 hover:bg-pearl/60 hover:text-ink")
                    }
                  >
                    {l.label}
                    {active && (
                      <span
                        aria-hidden
                        className="absolute inset-x-3 -bottom-[15px] h-[2px] rounded-full bg-primary"
                      />
                    )}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>

        {/* Actions */}
        <div className="ml-auto flex items-center gap-xs md:ml-0">
          <Link
            href="/reports/new"
            className="inline-flex items-center gap-1 rounded-pill bg-ink px-4 py-1.5 text-caption-strong text-canvas transition-transform duration-100 active:scale-95 hover:bg-ink/90"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round">
              <path d="M12 5v14M5 12h14" />
            </svg>
            新建报告
          </Link>
          <Link
            href="/settings"
            className="inline-flex h-8 w-8 items-center justify-center rounded-md text-ink-muted-48 transition-colors hover:bg-pearl/60 hover:text-ink"
            aria-label="设置"
            title="设置"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="3" />
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
            </svg>
          </Link>
        </div>
      </div>

      {/* Mobile nav row */}
      <nav className="border-t border-hairline md:hidden">
        <ul className="mx-auto flex max-w-grid items-center gap-2 overflow-x-auto px-lg py-2">
          {NAV_LINKS.map((l) => {
            const active = isActive(pathname, l.href);
            return (
              <li key={l.href}>
                <Link
                  href={l.href}
                  className={
                    "whitespace-nowrap rounded-md px-3 py-1 text-caption-strong " +
                    (active ? "bg-ink text-canvas" : "text-ink-muted-80 hover:bg-pearl/60")
                  }
                >
                  {l.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
    </header>
  );
}
