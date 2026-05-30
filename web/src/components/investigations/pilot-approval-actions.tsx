"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import {
  CheckCircle2,
  ExternalLink,
  GitBranch,
  GitPullRequestArrow,
  Loader2,
  Send,
  Upload,
} from "lucide-react";
import { toast } from "sonner";
import type { PilotRun } from "@/lib/api/types";
import { Button } from "@/components/ui/button";

const POLL_INTERVAL_MS = 2500;

type Props = {
  investigationId: string;
  pilot: PilotRun;
};

/**
 * Two-stage approval flow for an accepted pilot:
 *
 *   1. <PushStage>  — explicit "Push to my fork" button. First action
 *      that actually writes to GitHub. While polling the push status,
 *      we disable the button and show progress.
 *
 *   2. <PRStage>    — after push completes, explicit "Open draft PR"
 *      button. Second consequential step, separate confirm by design.
 *
 *   3. <DoneStage>  — links to fork branch + PR.
 *
 * Each stage polls the latest pilot row when an action is in flight,
 * then calls router.refresh() once the relevant field is populated so
 * the parent Server Component re-renders with the new state.
 */
export function PilotApprovalActions({ investigationId, pilot }: Props) {
  if (pilot.pr_url) {
    return <DoneStage pilot={pilot} />;
  }
  if (pilot.pushed_at) {
    return (
      <PRStage investigationId={investigationId} pilot={pilot} />
    );
  }
  return (
    <PushStage investigationId={investigationId} pilot={pilot} />
  );
}


// ---------------------------------------------------------------------------
// Stage 1: push to fork
// ---------------------------------------------------------------------------

function PushStage({ investigationId, pilot }: Props) {
  const router = useRouter();
  const [pending, setPending] = React.useState(false);

  // Resume polling if pushed_at is still null but we previously kicked off
  // a push (push_error is null too — still in flight). We don't persist
  // an "in flight" flag client-side; the parent's status is enough.
  React.useEffect(() => {
    if (!pending) return;
    let cancelled = false;
    const id = setInterval(async () => {
      try {
        const res = await fetch(
          `/api/investigations/${investigationId}/pilot`,
          { cache: "no-store" },
        );
        if (!res.ok) return;
        const next = (await res.json()) as PilotRun;
        if (cancelled) return;
        if (next.pushed_at || next.push_error) {
          router.refresh();
        }
      } catch {
        // transient — try again
      }
    }, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [pending, investigationId, router]);

  async function push() {
    if (pending) return;
    setPending(true);
    const toastId = toast.loading("Pushing branch to your fork…");
    try {
      const res = await fetch(
        `/api/investigations/${investigationId}/pilot/${pilot.id}/push`,
        { method: "POST" },
      );
      if (!res.ok) {
        const body = await res.text();
        throw new Error(body || `HTTP ${res.status}`);
      }
      toast.success("Push queued.", {
        id: toastId,
        description: "Forking and pushing a feature branch…",
      });
    } catch (err) {
      toast.error("Couldn't queue push.", {
        id: toastId,
        description: err instanceof Error ? err.message.slice(0, 200) : "",
      });
      setPending(false);
    }
  }

  return (
    <div className="rounded-md border border-border/60 bg-muted/20 p-4 space-y-3">
      <div className="flex items-start gap-3">
        <Upload className="size-4 text-primary mt-0.5" />
        <div className="flex-1">
          <p className="text-sm font-medium">
            Approve &amp; push to your fork
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Forks <code>{(pilot.transcript as { repo?: string } | null)?.repo ?? "the upstream repo"}</code>{" "}
            into your account (idempotent) and pushes a feature branch.
            Nothing opens upstream until you click the next button.
          </p>
        </div>
      </div>

      {pilot.push_error && !pending && (
        <div className="rounded bg-rose-500/10 p-2 text-xs text-rose-400">
          Previous push attempt failed: {pilot.push_error}
        </div>
      )}

      <Button onClick={push} disabled={pending}>
        {pending ? (
          <Loader2 className="mr-2 size-4 animate-spin" />
        ) : (
          <Upload className="mr-2 size-4" />
        )}
        {pending ? "Pushing…" : "Push to my fork"}
      </Button>
    </div>
  );
}


// ---------------------------------------------------------------------------
// Stage 2: open draft PR
// ---------------------------------------------------------------------------

function PRStage({ investigationId, pilot }: Props) {
  const router = useRouter();
  const [pending, setPending] = React.useState(false);

  React.useEffect(() => {
    if (!pending) return;
    let cancelled = false;
    const id = setInterval(async () => {
      try {
        const res = await fetch(
          `/api/investigations/${investigationId}/pilot`,
          { cache: "no-store" },
        );
        if (!res.ok) return;
        const next = (await res.json()) as PilotRun;
        if (cancelled) return;
        if (next.pr_url || next.pr_error) {
          router.refresh();
        }
      } catch {
        // transient
      }
    }, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [pending, investigationId, router]);

  async function openPR() {
    if (pending) return;
    setPending(true);
    const toastId = toast.loading("Opening draft PR…");
    try {
      const res = await fetch(
        `/api/investigations/${investigationId}/pilot/${pilot.id}/pr`,
        { method: "POST" },
      );
      if (!res.ok) {
        const body = await res.text();
        throw new Error(body || `HTTP ${res.status}`);
      }
      toast.success("PR creation queued.", { id: toastId });
    } catch (err) {
      toast.error("Couldn't queue PR.", {
        id: toastId,
        description: err instanceof Error ? err.message.slice(0, 200) : "",
      });
      setPending(false);
    }
  }

  return (
    <div className="rounded-md border border-border/60 bg-muted/20 p-4 space-y-3">
      <div className="flex items-start gap-3">
        <GitBranch className="size-4 text-emerald-500 mt-0.5" />
        <div className="flex-1">
          <p className="text-sm font-medium flex items-center gap-2">
            Branch pushed
            <CheckCircle2 className="size-4 text-emerald-500" />
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            On your fork:{" "}
            <a
              href={`${pilot.fork_url}/tree/${pilot.branch_ref}`}
              target="_blank"
              rel="noreferrer"
              className="font-mono underline hover:text-foreground"
            >
              {pilot.branch_ref}
              <ExternalLink className="inline ml-1 size-3" />
            </a>
          </p>
        </div>
      </div>

      {pilot.pr_error && !pending && (
        <div className="rounded bg-rose-500/10 p-2 text-xs text-rose-400">
          Previous PR attempt failed: {pilot.pr_error}
        </div>
      )}

      <Button onClick={openPR} disabled={pending}>
        {pending ? (
          <Loader2 className="mr-2 size-4 animate-spin" />
        ) : (
          <Send className="mr-2 size-4" />
        )}
        {pending ? "Opening PR…" : "Open draft PR upstream"}
      </Button>

      <p className="text-[11px] text-muted-foreground">
        The PR is opened as a <strong>draft</strong> and includes a clear
        AI-generated banner. The maintainer can close it without notice or
        leave a review.
      </p>
    </div>
  );
}


// ---------------------------------------------------------------------------
// Stage 3: done
// ---------------------------------------------------------------------------

function DoneStage({ pilot }: { pilot: PilotRun }) {
  return (
    <div className="rounded-md border border-emerald-500/40 bg-emerald-500/5 p-4 space-y-3">
      <div className="flex items-start gap-3">
        <GitPullRequestArrow className="size-4 text-emerald-500 mt-0.5" />
        <div className="flex-1">
          <p className="text-sm font-medium">Draft PR opened</p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            The agent&apos;s work is now in the maintainer&apos;s hands.
            You can keep pushing commits to the branch on your fork; they&apos;ll
            show up automatically on the PR.
          </p>
        </div>
      </div>

      <div className="flex flex-col gap-1.5 text-xs">
        <a
          href={pilot.pr_url ?? "#"}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1.5 text-primary hover:underline"
        >
          <GitPullRequestArrow className="size-3.5" />
          PR #{pilot.pr_number ?? "?"} on upstream
          <ExternalLink className="size-3" />
        </a>
        <a
          href={`${pilot.fork_url}/tree/${pilot.branch_ref}`}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1.5 text-muted-foreground hover:text-foreground"
        >
          <GitBranch className="size-3.5" />
          Branch on your fork: <code>{pilot.branch_ref}</code>
          <ExternalLink className="size-3" />
        </a>
      </div>
    </div>
  );
}
