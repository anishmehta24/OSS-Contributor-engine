import { Suspense } from "react";
import { fapi } from "@/lib/api/server";
import { InvestigationsPreviewCard } from "@/components/dashboard/investigations-preview-card";
import { MatchesPreviewCard } from "@/components/dashboard/matches-preview-card";
import { ProfileCard } from "@/components/dashboard/profile-card";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata = { title: "Dashboard" };

export default async function DashboardPage() {
  const me = await fapi.me();
  const greetName = me?.name?.trim().split(" ")[0] || me?.github_login || "";

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 sm:py-10">
      {/* Editorial header */}
      <header className="mb-8 border-b border-border pb-6">
        <p className="font-mono text-xs uppercase tracking-[0.2em] text-muted-foreground">
          Dashboard
        </p>
        <h1 className="mt-3 text-3xl font-medium sm:text-4xl">
          Hi, {greetName}.
        </h1>
        <p className="mt-2 text-muted-foreground">
          A quick look at where things stand.
        </p>
      </header>

      {/* Quick-stats strip */}
      <Suspense fallback={<StatStripSkeleton />}>
        <QuickStats />
      </Suspense>

      {/* Bento: profile (1) + latest matches (2), then investigations full-width */}
      <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="lg:col-span-1">
          <Suspense fallback={<PanelSkeleton />}>
            <ProfileCard />
          </Suspense>
        </div>
        <div className="lg:col-span-2">
          <Suspense fallback={<PanelSkeleton tall />}>
            <MatchesPreviewCard />
          </Suspense>
        </div>
        <div className="lg:col-span-3">
          <Suspense fallback={<PanelSkeleton />}>
            <InvestigationsPreviewCard />
          </Suspense>
        </div>
      </div>
    </div>
  );
}

async function QuickStats() {
  const [stats, cost] = await Promise.all([
    fapi.dbStats().catch(() => null),
    fapi.globalCost().catch(() => null),
  ]);
  const cells = [
    { label: "issues in pool", value: (stats?.issues ?? 0).toLocaleString() },
    {
      label: "investigations",
      value: (stats?.investigations ?? 0).toLocaleString(),
    },
    { label: "llm calls", value: (cost?.total_calls ?? 0).toLocaleString() },
    { label: "spent", value: `$${(cost?.total_cost_usd ?? 0).toFixed(2)}` },
  ];
  return (
    <dl className="grid grid-cols-2 divide-x divide-y divide-border overflow-hidden rounded-xl border border-border bg-card sm:grid-cols-4 sm:divide-y-0">
      {cells.map((c) => (
        <div key={c.label} className="px-5 py-5">
          <dt className="font-mono text-[0.65rem] uppercase tracking-[0.15em] text-muted-foreground">
            {c.label}
          </dt>
          <dd className="mt-2 font-heading text-2xl font-medium tabular-nums">
            {c.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function StatStripSkeleton() {
  return (
    <div className="grid grid-cols-2 divide-x divide-y divide-border overflow-hidden rounded-xl border border-border bg-card sm:grid-cols-4 sm:divide-y-0">
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className="space-y-2 px-5 py-5">
          <Skeleton className="h-3 w-20" />
          <Skeleton className="h-7 w-16" />
        </div>
      ))}
    </div>
  );
}

function PanelSkeleton({ tall = false }: { tall?: boolean }) {
  return (
    <div className="space-y-4 rounded-xl border border-border bg-card p-6">
      <Skeleton className="h-3.5 w-24" />
      <Skeleton className="h-6 w-40" />
      <div className="space-y-2 pt-2">
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-3/4" />
        {tall && (
          <>
            <Skeleton className="h-4 w-5/6" />
            <Skeleton className="h-4 w-2/3" />
          </>
        )}
      </div>
    </div>
  );
}
