"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const LINKS = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/matches", label: "Matches" },
  { href: "/investigations", label: "Investigations" },
  { href: "/direct-pilot", label: "Direct Pilot" },
];

/**
 * Horizontal navigation list. Client-side because we need `usePathname()` to
 * highlight the active section.
 */
export function NavLinks({ className }: { className?: string }) {
  const pathname = usePathname();

  return (
    <ul className={cn("flex items-center gap-1", className)}>
      {LINKS.map(({ href, label }) => {
        const active = pathname === href || pathname.startsWith(`${href}/`);
        return (
          <li key={href}>
            <Link
              href={href}
              className={cn(
                "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                "text-muted-foreground hover:text-foreground hover:bg-muted/60",
                active && "text-foreground bg-muted",
              )}
            >
              {label}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

/** Same data, vertical layout — used inside the mobile Sheet. */
export function NavLinksVertical({
  onNavigate,
}: {
  onNavigate?: () => void;
}) {
  const pathname = usePathname();
  return (
    <ul className="flex flex-col gap-1">
      {LINKS.map(({ href, label }) => {
        const active = pathname === href || pathname.startsWith(`${href}/`);
        return (
          <li key={href}>
            <Link
              href={href}
              onClick={onNavigate}
              className={cn(
                "block rounded-md px-3 py-2 text-base font-medium transition-colors",
                "text-muted-foreground hover:text-foreground hover:bg-muted/60",
                active && "text-foreground bg-muted",
              )}
            >
              {label}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
