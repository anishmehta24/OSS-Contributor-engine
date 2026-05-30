import { Suspense } from "react";
import Link from "next/link";
import type { Metadata } from "next";
import { ArrowLeft, ExternalLink } from "lucide-react";
import { fapi } from "@/lib/api/server";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusBadge } from "@/components/investigations/status-badge";
import { LiveStream } from "@/components/investigations/live-stream";
import { ReportMarkdown } from "@/components/investigations/report-markdown";
import { InvestigationCostCard } from "@/components/investigations/cost-summary";
import { PilotPanel } from "@/components/investigations/pilot-panel";
import { PitchDrafter } from "@/components/investigations/pitch-drafter";

export const metadata: Metadata = { title: "Investigation" };

// Declared above the page component because Turbopack's RSC compiler
// doesn't reliably honor hoisting for function decls referenced from JSX
// children — keeping it in textual order before the reference avoids a
// "PilotPanelSkeleton is not defined" at runtime.
function PilotPanelSkeleton() {
  return (
    <div className="rounded-lg border border-border/60 p-5 space-y-3">
      <Skeleton className="h-4 w-48" />
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-4 w-3/4" />
      <Skeleton className="h-9 w-40 mt-2" />
    </div>
  );
}

export default async function InvestigationDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const inv = await fapi.investigation(id);

  // 404 from FastAPI (other user's investigation, or genuinely missing).
  if (!inv) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-16 sm:px-6">
        <Card className="border-border/60">
          <CardHeader>
            <CardTitle>Investigation not found</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            <Link href="/investigations" className="underline underline-offset-2">
              Back to all investigations
            </Link>
          </CardContent>
        </Card>
      </div>
    );
  }

  const heading =
    inv.repo && inv.issue_number ? `${inv.repo}#${inv.issue_number}` : "(pending)";
  const startTime = inv.started_at ?? null;
  const endTime = inv.completed_at ?? null;

  return (
    <div className="mx-auto max-w-4xl px-4 py-8 sm:px-6 sm:py-10">
      {/* Breadcrumb */}
      <Link
        href="/investigations"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors mb-4"
      >
        <ArrowLeft className="size-3.5" />
        All investigations
      </Link>

      {/* Header */}
      <header className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-1">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-tight font-mono">
              {heading}
            </h1>
            {inv.issue_url && (
              <a
                href={inv.issue_url}
                target="_blank"
                rel="noreferrer"
                className="text-muted-foreground hover:text-foreground transition-colors"
                aria-label="Open issue on GitHub"
              >
                <ExternalLink className="size-4" />
              </a>
            )}
          </div>
          <p className="text-xs text-muted-foreground font-mono">
            id: {inv.id}
          </p>
          {(startTime || endTime) && (
            <p className="text-xs text-muted-foreground font-mono">
              {startTime && <>started {fmtUtc(startTime)}</>}
              {startTime && endTime && " · "}
              {endTime && <>finished {fmtUtc(endTime)}</>}
            </p>
          )}
        </div>
        <StatusBadge status={inv.status} />
      </header>

      {/* Status-conditional body */}
      {(inv.status === "queued" || inv.status === "running") && (
        <LiveStream investigationId={inv.id} />
      )}

      {inv.status === "failed" && (
        <Card className="border-rose-500/30 bg-rose-500/5">
          <CardHeader>
            <CardTitle className="text-base text-rose-500">
              Investigation failed
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm font-mono whitespace-pre-wrap">
            {inv.error || "Unknown error"}
          </CardContent>
        </Card>
      )}

      {inv.status === "completed" && (
        <div className="space-y-6">
          {/* Report */}
          <Card className="border-border/60">
            <CardHeader>
              <CardTitle className="text-base">Report</CardTitle>
            </CardHeader>
            <CardContent>
              {inv.markdown_report ? (
                <ReportMarkdown markdown={inv.markdown_report} />
              ) : (
                <p className="text-sm text-muted-foreground italic">
                  No report body — the investigation completed but produced no
                  markdown.
                </p>
              )}
            </CardContent>
          </Card>

          {/* Cost */}
          <InvestigationCostCard id={inv.id} />

          {/* Autonomous-pilot panel (v3) — Suspense'd because the latest-pilot
              API call is the only thing on the page that can be slow when
              backend has just started. */}
          <section className="space-y-2">
            <h2 className="text-base font-semibold">Autonomous fix</h2>
            <Suspense fallback={<PilotPanelSkeleton />}>
              <PilotPanel investigationId={inv.id} />
            </Suspense>
          </section>

          {/* Pitch */}
          <section className="space-y-2">
            <h2 className="text-base font-semibold">Draft a comment</h2>
            <PitchDrafter
              investigationId={inv.id}
              initialPitch={inv.pitch_md}
            />
          </section>
        </div>
      )}
    </div>
  );
}

function fmtUtc(iso: string): string {
  try {
    return new Date(iso).toUTCString().replace(" GMT", "");
  } catch {
    return iso;
  }
}
