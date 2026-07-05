import Link from "next/link";
import type { Metadata } from "next";
import { ArrowRight, ExternalLink, Microscope, Search } from "lucide-react";
import { fapi } from "@/lib/api/server";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { StatusBadge } from "@/components/investigations/status-badge";
import type { InvestigationRow } from "@/lib/api/types";

export const metadata: Metadata = { title: "Investigations" };

const STATUS_FILTERS = ["all", "running", "completed", "failed"] as const;
type StatusFilter = (typeof STATUS_FILTERS)[number];

type SearchParams = { status?: string };

function parseStatus(raw: SearchParams): StatusFilter {
  return (STATUS_FILTERS as readonly string[]).includes(raw.status ?? "")
    ? (raw.status as StatusFilter)
    : "all";
}

export default async function InvestigationsListPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const raw = await searchParams;
  const status = parseStatus(raw);

  const all = (await fapi.recentInvestigations(50)) ?? [];
  const rows = status === "all" ? all : all.filter((r) => r.status === status);

  return (
    <div className="mx-auto max-w-5xl px-4 py-8 sm:px-6 sm:py-10">
      <header className="mb-6 border-b border-border pb-6">
        <p className="flex items-center gap-2 font-mono text-xs uppercase tracking-[0.2em] text-muted-foreground">
          <Microscope className="size-3.5" />
          Investigations
        </p>
        <h1 className="mt-3 text-3xl font-medium sm:text-4xl">
          Your investigation history
        </h1>
        <p className="mt-3 max-w-2xl text-muted-foreground">
          Every issue you&apos;ve sent through the multi-agent investigator,
          newest first. Pick one to see the full report or stream a run in
          progress live.
        </p>
      </header>

      {/* Status filter — small tabs */}
      <div className="mb-4 inline-flex rounded-lg border border-border bg-muted/30 p-1">
        {STATUS_FILTERS.map((s) => {
          const active = s === status;
          const count = s === "all" ? all.length : all.filter((r) => r.status === s).length;
          return (
            <Link
              key={s}
              href={s === "all" ? "/investigations" : `/investigations?status=${s}`}
              className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                active
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <span className="capitalize">{s}</span>
              <span className="font-mono text-xs text-muted-foreground tabular-nums">
                {count}
              </span>
            </Link>
          );
        })}
      </div>

      {rows.length === 0 ? (
        <EmptyState hasAny={all.length > 0} status={status} />
      ) : (
        <div className="overflow-hidden rounded-xl border border-border bg-card">
          {rows.map((r) => (
            <InvestigationRowCard key={r.id} r={r} />
          ))}
        </div>
      )}
    </div>
  );
}

const RAIL: Record<string, string> = {
  running: "bg-primary",
  completed: "bg-emerald-500",
  failed: "bg-destructive",
  queued: "bg-muted-foreground/40",
};

function InvestigationRowCard({ r }: { r: InvestigationRow }) {
  const title =
    r.repo && r.issue_number ? `${r.repo}#${r.issue_number}` : "(pending)";
  const when = r.completed_at ?? r.started_at;

  return (
    // Stretched-link pattern: the Link's ::after covers the row so the whole
    // thing is clickable; the GitHub external-link sits on z-10 so its click
    // wins — avoids invalid <a> inside <a> nesting.
    <div className="group relative flex items-stretch gap-4 border-b border-border px-5 py-4 transition-colors last:border-0 hover:bg-accent/40">
      <span
        className={`w-1 shrink-0 rounded-full ${RAIL[r.status] ?? RAIL.queued}`}
      />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <Link
            href={`/investigations/${r.id}`}
            className="truncate font-heading text-base font-medium transition-colors after:absolute after:inset-0 group-hover:text-primary"
          >
            {title}
          </Link>
          {r.issue_url && (
            <a
              href={r.issue_url}
              target="_blank"
              rel="noreferrer"
              className="relative z-10 text-muted-foreground transition-colors hover:text-foreground"
              aria-label="Open issue on GitHub"
            >
              <ExternalLink className="size-3.5" />
            </a>
          )}
        </div>
        {when && (
          <p className="mt-0.5 font-mono text-xs text-muted-foreground">
            {new Date(when).toUTCString().replace(" GMT", "")}
          </p>
        )}
        {r.error && (
          <p className="mt-1 max-w-xl truncate text-xs text-destructive/90">
            {r.error}
          </p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-3">
        <StatusBadge status={r.status} />
        <ArrowRight className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-primary" />
      </div>
    </div>
  );
}

function EmptyState({
  hasAny,
  status,
}: {
  hasAny: boolean;
  status: StatusFilter;
}) {
  if (hasAny && status !== "all") {
    return (
      <Card className="border-border">
        <CardHeader className="space-y-2">
          <CardTitle className="text-lg">
            No <span className="capitalize">{status}</span> investigations
          </CardTitle>
          <CardDescription>
            Switch the filter above or go investigate an issue from your{" "}
            <Link href="/matches" className="underline underline-offset-2">
              matches
            </Link>
            .
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }
  return (
    <Card className="border-border">
      <CardHeader className="space-y-3 text-center">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10 text-primary">
          <Search className="size-6" />
        </div>
        <CardTitle className="text-2xl">No investigations yet</CardTitle>
        <CardDescription className="text-balance text-base">
          Pick a match and hit Investigate — four specialist agents will read
          the issue, map the repo, scan commit history, and synthesize an
          approach in about 15 seconds.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex justify-center pb-8">
        <Button render={<Link href="/matches" />} nativeButton={false} size="lg">
          Browse matches
        </Button>
      </CardContent>
    </Card>
  );
}
