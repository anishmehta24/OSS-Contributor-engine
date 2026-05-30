import { Suspense } from "react";
import Link from "next/link";
import type { Metadata } from "next";
import { GraduationCap, Search, Sparkles } from "lucide-react";
import { fapi } from "@/lib/api/server";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { FilterBar, type Filters } from "@/components/matches/filter-bar";
import { MatchCard } from "@/components/matches/match-card";
import { ModeToggle } from "@/components/matches/mode-toggle";

export const metadata: Metadata = { title: "Matches" };

type SearchParams = {
  mode?: string;
  difficulty?: string;
  top?: string;
  explain?: string;
};

function parseFilters(raw: SearchParams): {
  mode: "general" | "gsoc";
  filters: Filters;
} {
  const mode = raw.mode === "gsoc" ? "gsoc" : "general";
  const difficulty = (
    ["any", "easy", "medium", "hard"] as const
  ).includes(raw.difficulty as Filters["difficulty"])
    ? (raw.difficulty as Filters["difficulty"])
    : "any";
  const top = Math.max(1, Math.min(50, Number(raw.top) || 10));
  const explain = raw.explain !== "false"; // default true
  return { mode, filters: { difficulty, top, explain } };
}

export default async function MatchesPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const raw = await searchParams;
  const { mode, filters } = parseFilters(raw);

  return (
    <div className="mx-auto max-w-5xl px-4 py-8 sm:px-6 sm:py-10">
      {/* Header */}
      <header className="mb-6">
        <p className="flex items-center gap-2 text-xs uppercase tracking-wide text-muted-foreground">
          <Search className="size-3.5" />
          Issues that match
        </p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight">
          Ranked by skill fit and repo health
        </h1>
        <p className="mt-2 max-w-2xl text-muted-foreground">
          We pull from the issue pool the Hunter has populated, embed your
          profile against each one, and rank by skill match, repo health,
          freshness, difficulty fit, and impact.
        </p>
      </header>

      {/* Controls */}
      <div className="mb-6 flex flex-col gap-4 rounded-lg border border-border/60 bg-muted/20 p-4">
        <ModeToggle current={mode} />
        <FilterBar filters={filters} />
        {mode === "gsoc" && (
          <p className="text-xs text-muted-foreground flex items-center gap-1.5">
            <GraduationCap className="size-3.5 text-primary" />
            Filtered to orgs that have shipped GSoC projects in the last 3
            years.
          </p>
        )}
      </div>

      {/* Results — Suspense + a key so filter changes don't trigger
          old-data flash. Each key change suspends and re-fetches. */}
      <Suspense
        key={`${mode}:${filters.difficulty}:${filters.top}:${filters.explain}`}
        fallback={<MatchListSkeleton count={Math.min(filters.top, 5)} />}
      >
        <MatchList mode={mode} filters={filters} />
      </Suspense>
    </div>
  );
}

async function MatchList({
  mode,
  filters,
}: {
  mode: "general" | "gsoc";
  filters: Filters;
}) {
  const response = await fapi
    .matches({
      mode,
      top: filters.top,
      difficulty: filters.difficulty,
      explain: filters.explain,
    })
    .catch(() => null);

  if (response === null) {
    return <NoProfileEmpty />;
  }

  const matches = response.matches;
  if (matches.length === 0) {
    return <NoMatchesEmpty mode={mode} />;
  }

  return (
    <div className="space-y-3">
      {matches.map((m, i) => (
        <MatchCard key={m.issue_id} match={m} rank={i + 1} />
      ))}
    </div>
  );
}

function MatchListSkeleton({ count }: { count: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="rounded-lg border border-border/60 p-5 space-y-3">
          <div className="flex items-center gap-3">
            <Skeleton className="h-4 w-8" />
            <Skeleton className="h-4 w-48" />
            <Skeleton className="h-4 w-16 ml-auto" />
          </div>
          <Skeleton className="h-5 w-3/4 ml-9" />
          <Skeleton className="h-4 w-2/3 ml-9" />
          <div className="ml-9 flex justify-between">
            <Skeleton className="h-6 w-72" />
            <Skeleton className="h-8 w-28" />
          </div>
        </div>
      ))}
    </div>
  );
}

function NoProfileEmpty() {
  return (
    <Card className="border-border/60">
      <CardHeader className="space-y-3 text-center">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10 text-primary">
          <Sparkles className="size-6" />
        </div>
        <CardTitle className="text-2xl">No profile yet</CardTitle>
        <CardDescription className="text-balance text-base">
          Matches need a profile so we know what to rank against. Start there
          — takes 30-90 seconds.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex justify-center pb-8">
        <Button render={<Link href="/profile" />} nativeButton={false} size="lg">
          Get profiled
        </Button>
      </CardContent>
    </Card>
  );
}

function NoMatchesEmpty({ mode }: { mode: "general" | "gsoc" }) {
  return (
    <Card className="border-border/60">
      <CardHeader className="space-y-2">
        <CardTitle className="text-lg">No matches yet</CardTitle>
        <CardDescription>
          {mode === "gsoc"
            ? "The issue pool doesn't include anything from GSoC-listed orgs in your languages yet."
            : "The issue pool hasn't been populated for your skill set yet."}
        </CardDescription>
      </CardHeader>
      <CardContent className="text-sm text-muted-foreground">
        Run the Issue Hunter to backfill the pool:
        <pre className="mt-3 rounded-md bg-muted px-3 py-2 text-xs font-mono">
          {mode === "gsoc"
            ? "python -m app.workers hunt --mode gsoc"
            : "python -m app.workers hunt"}
        </pre>
      </CardContent>
    </Card>
  );
}
