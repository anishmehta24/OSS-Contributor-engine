import { Suspense } from "react";
import Link from "next/link";
import type { Metadata } from "next";
import { Rocket } from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { DirectPilotForm } from "@/components/pilot/direct-pilot-form";
import { PilotPanel } from "@/components/investigations/pilot-panel";

export const metadata: Metadata = { title: "Direct Pilot" };

export default async function DirectPilotPage({
  searchParams,
}: {
  searchParams: Promise<{ inv?: string }>;
}) {
  const { inv } = await searchParams;

  return (
    <div className="mx-auto max-w-3xl px-4 py-8 sm:px-6 sm:py-10">
      <header className="mb-6 border-b border-border pb-6">
        <p className="flex items-center gap-2 font-mono text-xs uppercase tracking-[0.2em] text-muted-foreground">
          <Rocket className="size-3.5" />
          Direct Pilot
        </p>
        <h1 className="mt-3 text-3xl font-medium sm:text-4xl">
          Point the pilot at{" "}
          <span className="italic text-primary">any issue</span>
        </h1>
        <p className="mt-3 max-w-2xl text-muted-foreground">
          Skip hunting and investigating — paste a GitHub issue URL and the
          Autonomous Pilot clones the repo in a sandbox, writes a patch, runs
          the tests, and (after you review the diff) opens a PR. Best on a
          small, well-scoped issue.
        </p>
      </header>

      {inv ? (
        <div className="flex flex-col gap-6">
          <Suspense fallback={<Skeleton className="h-40 w-full rounded-xl" />}>
            <PilotPanel investigationId={inv} />
          </Suspense>
          <div>
            <Link
              href="/direct-pilot"
              className={buttonVariants({ variant: "outline", size: "sm" })}
            >
              ← Start another
            </Link>
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-4 rounded-xl border border-border bg-muted/30 p-5">
          <DirectPilotForm />
          <p className="text-xs text-muted-foreground">
            Accepts <code>https://github.com/owner/repo/issues/123</code>,{" "}
            <code>owner/repo/issues/123</code>, or <code>owner/repo#123</code>.
            No changes hit GitHub until you review the diff and click Push.
          </p>
        </div>
      )}
    </div>
  );
}
