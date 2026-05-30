"use client";

import * as React from "react";
import { useRouter, useSearchParams, usePathname } from "next/navigation";
import { Globe, GraduationCap } from "lucide-react";
import { cn } from "@/lib/utils";

const OPTIONS = [
  {
    value: "general",
    label: "General",
    Icon: Globe,
    description: "All of GitHub",
  },
  {
    value: "gsoc",
    label: "GSoC",
    Icon: GraduationCap,
    description: "GSoC orgs only",
  },
] as const;

type Mode = (typeof OPTIONS)[number]["value"];

/**
 * Two-button segmented control for hunt mode.
 *
 * Drives the `?mode=` URL param. Server Component re-renders the page on the
 * resulting navigation. We wrap navigation in startTransition so the UI can
 * show a subtle "loading" cue (consumed by sibling components if needed).
 */
export function ModeToggle({ current }: { current: Mode }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const [pending, startTransition] = React.useTransition();

  function setMode(next: Mode) {
    if (next === current) return;
    const updated = new URLSearchParams(params);
    updated.set("mode", next);
    startTransition(() => {
      router.push(`${pathname}?${updated.toString()}`);
    });
  }

  return (
    <div
      role="radiogroup"
      aria-label="Search scope"
      data-pending={pending || undefined}
      className="inline-flex rounded-lg border border-border/60 bg-muted/30 p-1"
    >
      {OPTIONS.map(({ value, label, Icon, description }) => {
        const active = value === current;
        return (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => setMode(value)}
            disabled={pending}
            className={cn(
              "inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
              active
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
              pending && "opacity-70",
            )}
          >
            <Icon className="size-4" />
            <span>{label}</span>
            <span className="hidden text-xs text-muted-foreground sm:inline">
              · {description}
            </span>
          </button>
        );
      })}
    </div>
  );
}
