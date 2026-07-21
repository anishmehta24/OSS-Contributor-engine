"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Loader2, Rocket } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";

/**
 * Direct Pilot entry form.
 *
 * Takes a pasted GitHub issue URL, POSTs to /api/investigations/from-url
 * (which fetches the issue + repo, creates a minimal completed investigation,
 * and queues the pilot), then routes to /direct-pilot?inv=<id> where the
 * shared PilotPanel takes over (progress → review → push → PR).
 */
export function DirectPilotForm() {
  const router = useRouter();
  const [url, setUrl] = React.useState("");
  const [pending, setPending] = React.useState(false);

  async function start(e: React.FormEvent) {
    e.preventDefault();
    if (pending || !url.trim()) return;
    setPending(true);
    const toastId = toast.loading("Starting pilot on that issue…");
    try {
      const res = await fetch("/api/investigations/from-url", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ issue_url: url.trim() }),
      });
      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try {
          const j = await res.json();
          detail = j?.detail ?? detail;
        } catch {
          /* non-JSON error body */
        }
        throw new Error(detail);
      }
      const data = (await res.json()) as {
        investigation_id: string;
        repo: string;
        issue_number: number;
      };
      toast.success(`Pilot queued on ${data.repo}#${data.issue_number}.`, {
        id: toastId,
        description: "Cloning the repo and starting the multi-agent fix loop…",
      });
      router.push(`/direct-pilot?inv=${data.investigation_id}`);
    } catch (err) {
      toast.error("Couldn't start pilot.", {
        id: toastId,
        description: err instanceof Error ? err.message.slice(0, 200) : "",
      });
      setPending(false);
    }
  }

  return (
    <form onSubmit={start} className="flex flex-col gap-3 sm:flex-row">
      <input
        type="text"
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        placeholder="https://github.com/owner/repo/issues/123  (or owner/repo#123)"
        disabled={pending}
        autoComplete="off"
        spellCheck={false}
        className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 font-mono text-sm transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50"
      />
      <Button type="submit" disabled={pending || !url.trim()}>
        {pending ? (
          <Loader2 className="mr-2 size-4 animate-spin" />
        ) : (
          <Rocket className="mr-2 size-4" />
        )}
        {pending ? "Starting…" : "Start pilot"}
      </Button>
    </form>
  );
}
