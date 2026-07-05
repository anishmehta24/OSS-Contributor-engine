import { Suspense } from "react";
import { fapi } from "@/lib/api/server";
import { CostCard } from "@/components/dashboard/cost-card";
import {
  InvestigationsPreviewCard,
} from "@/components/dashboard/investigations-preview-card";
import {
  MatchesPreviewCard,
} from "@/components/dashboard/matches-preview-card";
import { ProfileCard } from "@/components/dashboard/profile-card";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata = { title: "Dashboard" };

export default async function DashboardPage() {
  // `me` is already fetched in the layout, but each card is its own data
  // boundary so they can stream in independently when a card is slow.
  // Cheap call here is fine — Next memoizes fetch() within a render pass.
  const me = await fapi.me();
  const greetName = me?.name?.trim().split(" ")[0] || me?.github_login || "";

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 sm:py-10">
      {/* Hero greeting */}
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

      {/* 2-column grid on md+, single column on mobile. Each card streams
          independently via Suspense so a slow API doesn't block the others. */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Suspense fallback={<CardSkeleton />}>
          <ProfileCard />
        </Suspense>
        <Suspense fallback={<CardSkeleton />}>
          <CostCard />
        </Suspense>
        <Suspense fallback={<CardSkeleton tall />}>
          <MatchesPreviewCard />
        </Suspense>
        <Suspense fallback={<CardSkeleton tall />}>
          <InvestigationsPreviewCard />
        </Suspense>
      </div>
    </div>
  );
}

function CardSkeleton({ tall = false }: { tall?: boolean }) {
  return (
    <div className="rounded-xl border border-border p-6 space-y-3">
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
