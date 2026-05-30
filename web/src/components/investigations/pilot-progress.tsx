"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { CheckCircle2, Loader2 } from "lucide-react";
import type { PilotRun } from "@/lib/api/types";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

const POLL_INTERVAL_MS = 3000;

/**
 * Polls /api/investigations/<id>/pilot every few seconds while the
 * pilot is still running. On any status change away from queued/running
 * (so accepted/rejected/failed), calls router.refresh() so the parent
 * Server Component re-fetches and dispatches to the right next state.
 *
 * No SSE here — keeping the v3 backend deliberately polling-friendly so
 * the UI stays simple. SSE can come if the latency matters.
 */
export function PilotProgress({
  investigationId,
  pilot,
}: {
  investigationId: string;
  pilot: PilotRun;
}) {
  const router = useRouter();
  const [elapsedS, setElapsedS] = React.useState(0);

  React.useEffect(() => {
    const startedAt = pilot.started_at
      ? new Date(pilot.started_at).getTime()
      : Date.now();
    const tick = () => setElapsedS(Math.round((Date.now() - startedAt) / 1000));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [pilot.started_at]);

  React.useEffect(() => {
    let cancelled = false;

    async function poll() {
      try {
        const res = await fetch(
          `/api/investigations/${investigationId}/pilot`,
          { cache: "no-store" },
        );
        if (!res.ok) return; // transient, try again next tick
        const next = (await res.json()) as PilotRun;
        if (cancelled) return;
        // Status changed away from queued/running — refresh the Server
        // Component tree so PilotPanel re-dispatches.
        if (next.status !== "queued" && next.status !== "running") {
          router.refresh();
        }
      } catch {
        // swallow — next tick will try again
      }
    }

    const id = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [investigationId, router]);

  const stages = [
    { label: "Queued", done: true },
    { label: "Cloning repo + exploring candidate files", done: pilot.attempts_made > 0 || pilot.status === "running" },
    { label: `Patch + test loop (${pilot.attempts_made} attempt${pilot.attempts_made === 1 ? "" : "s"})`, done: false },
  ];

  return (
    <Card className="border-border/60">
      <CardHeader>
        <CardTitle className="text-base flex items-center gap-2">
          <Loader2 className="size-4 text-primary animate-spin" />
          Autonomous pilot {pilot.status}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ol className="space-y-2 text-sm">
          {stages.map((s, i) => (
            <li key={i} className="flex items-center gap-2">
              {s.done ? (
                <CheckCircle2 className="size-4 text-emerald-500" />
              ) : (
                <Loader2 className="size-4 text-primary animate-spin" />
              )}
              <span className={s.done ? "text-foreground" : "text-muted-foreground"}>
                {s.label}
              </span>
            </li>
          ))}
        </ol>
        <p className="mt-4 text-xs text-muted-foreground font-mono">
          Pilot id: <code>{pilot.id.slice(0, 8)}</code> · elapsed{" "}
          {elapsedS}s · polling every {POLL_INTERVAL_MS / 1000}s
        </p>
      </CardContent>
    </Card>
  );
}
