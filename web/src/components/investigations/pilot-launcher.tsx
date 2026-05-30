"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Loader2, Rocket } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

type Props = {
  investigationId: string;
  /** First-time CTA vs "Try again" — affects copy only. */
  firstTime?: boolean;
};

/**
 * Intro card + "Try autonomous fix" button.
 *
 * Used for both the never-attempted state and the after-failure-retry
 * state. Hits POST /api/investigations/<id>/pilot which queues a
 * background task; we refresh the Server Component tree so PilotPanel
 * re-fetches and rolls forward to <PilotProgress>.
 */
export function PilotLauncher({ investigationId, firstTime = true }: Props) {
  const router = useRouter();
  const [pending, setPending] = React.useState(false);

  async function start() {
    if (pending) return;
    setPending(true);
    const toastId = toast.loading("Queuing autonomous pilot…");
    try {
      const res = await fetch(
        `/api/investigations/${investigationId}/pilot`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
        },
      );
      if (!res.ok) {
        const body = await res.text();
        throw new Error(body || `HTTP ${res.status}`);
      }
      toast.success("Pilot queued.", {
        id: toastId,
        description:
          "Cloning the repo and starting the multi-agent fix loop…",
      });
      router.refresh();
    } catch (err) {
      toast.error("Couldn't start pilot.", {
        id: toastId,
        description: err instanceof Error ? err.message.slice(0, 200) : "",
      });
      setPending(false);
    }
  }

  return (
    <Card className="border-border/60 border-dashed">
      <CardHeader>
        <CardTitle className="text-base flex items-center gap-2">
          <Rocket className="size-4 text-primary" />
          {firstTime ? "Try an autonomous fix" : "Try again"}
        </CardTitle>
        <CardDescription className="text-sm">
          The Pilot Coordinator will clone the repo into a sandbox, pick
          candidate files, write a patch, run the project&apos;s tests, and
          loop up to 3 times if the patch breaks anything. You&apos;ll get
          a chance to review the diff before anything touches GitHub.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Button onClick={start} disabled={pending}>
          {pending ? (
            <Loader2 className="mr-2 size-4 animate-spin" />
          ) : (
            <Rocket className="mr-2 size-4" />
          )}
          {pending
            ? "Queuing…"
            : firstTime
              ? "Start autonomous pilot"
              : "Retry autonomous pilot"}
        </Button>
        <p className="mt-3 text-xs text-muted-foreground">
          Typical runtime: 30-90s for explore + patch, plus ~5s per test phase.
          No changes hit GitHub until you click <strong>Push</strong> after
          reviewing the diff.
        </p>
      </CardContent>
    </Card>
  );
}
