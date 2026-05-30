"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, Loader2, Microscope } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";

type Props = {
  repo: string;
  issueNumber: number;
};

/**
 * One-click "investigate this issue" — POSTs to /api/investigations and
 * routes to the per-investigation detail page. The detail page (Batch 25)
 * streams agent progress via SSE.
 */
export function InvestigateButton({ repo, issueNumber }: Props) {
  const router = useRouter();
  const [pending, setPending] = React.useState(false);

  async function run() {
    if (pending) return;
    setPending(true);
    const toastId = toast.loading("Queuing investigation…");
    try {
      const res = await fetch("/api/investigations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo, issue_number: issueNumber }),
      });
      if (!res.ok) {
        const body = await res.text();
        throw new Error(body || `HTTP ${res.status}`);
      }
      const { job_id } = (await res.json()) as { job_id: string };
      toast.success("Investigation queued.", {
        id: toastId,
        description: "Streaming agent progress…",
      });
      router.push(`/investigations/${job_id}`);
    } catch (err) {
      toast.error("Couldn't queue investigation.", {
        id: toastId,
        description: err instanceof Error ? err.message.slice(0, 200) : "",
      });
      setPending(false);
    }
  }

  return (
    <Button onClick={run} disabled={pending} size="sm">
      {pending ? (
        <Loader2 className="mr-2 size-3.5 animate-spin" />
      ) : (
        <Microscope className="mr-2 size-3.5" />
      )}
      {pending ? "Queuing…" : "Investigate"}
      {!pending && <ArrowRight className="ml-1 size-3.5" />}
    </Button>
  );
}
