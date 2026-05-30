"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import {
  CheckCircle2,
  Database,
  FileCode,
  Loader2,
  Microscope,
  XCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";

type StreamEvent =
  | { type: "queued"; repo?: string; issue_number?: number }
  | { type: "investigation_started" }
  | { type: "data_fetched"; comments?: number; tree_files?: number }
  | { type: "agent_started"; agent: string }
  | { type: "agent_completed"; agent: string; candidate_files?: number }
  | { type: "investigation_completed"; effort?: string; from_cache?: boolean }
  | { type: "investigation_failed"; error?: string }
  | { type: "stream_timeout" };

type TimelineItem = {
  id: number;
  label: string;
  detail?: string;
  status: "pending" | "active" | "done" | "error";
  Icon: React.ComponentType<{ className?: string }>;
};

const TERMINAL = new Set(["investigation_completed", "investigation_failed"]);

/**
 * SSE consumer for /investigations/{id}/stream.
 *
 * Uses fetch + ReadableStream rather than native EventSource because:
 *   1) EventSource doesn't send cookies by default in older webkit builds
 *   2) We want full control over reconnect / abort
 *
 * On the terminal event (completed/failed), refreshes the Server Component
 * tree so the page rerenders the final report + cost cards.
 */
export function LiveStream({ investigationId }: { investigationId: string }) {
  const router = useRouter();
  const [items, setItems] = React.useState<TimelineItem[]>([]);
  const [done, setDone] = React.useState(false);
  const idCounter = React.useRef(0);

  // Track the currently-active agent so we can mark it done on the matching
  // agent_completed event instead of just appending another row.
  const activeAgentIdx = React.useRef<Map<string, number>>(new Map());

  React.useEffect(() => {
    const controller = new AbortController();

    async function consume() {
      try {
        const res = await fetch(`/api/investigations/${investigationId}/stream`, {
          signal: controller.signal,
          headers: { Accept: "text/event-stream" },
          cache: "no-store",
        });
        if (!res.ok || !res.body) {
          appendError(`Stream HTTP ${res.status}`);
          return;
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done: streamDone, value } = await reader.read();
          if (streamDone) break;
          buffer += decoder.decode(value, { stream: true });

          // SSE frames are separated by blank lines. Split, keep the trailing
          // partial frame in the buffer for the next chunk.
          const frames = buffer.split("\n\n");
          buffer = frames.pop() ?? "";

          for (const frame of frames) {
            const line = frame.split("\n").find((l) => l.startsWith("data: "));
            if (!line) continue; // heartbeat (":heartbeat") or empty
            const payload = line.slice(6);
            try {
              const event = JSON.parse(payload) as StreamEvent;
              handleEvent(event);
              if (TERMINAL.has(event.type)) {
                setDone(true);
                // small delay so the user sees the final "done" tick
                setTimeout(() => router.refresh(), 600);
                return;
              }
            } catch {
              // Malformed payload — skip silently. Backend bug, not ours.
            }
          }
        }
      } catch (err) {
        if ((err as Error).name === "AbortError") return;
        appendError((err as Error).message);
      }
    }

    function handleEvent(event: StreamEvent) {
      switch (event.type) {
        case "queued":
          append({
            label: "Queued",
            detail: event.repo && event.issue_number
              ? `${event.repo}#${event.issue_number}`
              : undefined,
            status: "done",
            Icon: Microscope,
          });
          break;
        case "investigation_started":
          append({ label: "Investigation started", status: "done", Icon: Microscope });
          break;
        case "data_fetched":
          append({
            label: "Repo + issue context fetched",
            detail: `${event.comments ?? 0} comments · ${event.tree_files ?? 0} files`,
            status: "done",
            Icon: Database,
          });
          break;
        case "agent_started": {
          const idx = appendAndIndex({
            label: agentLabel(event.agent),
            status: "active",
            Icon: Loader2,
          });
          activeAgentIdx.current.set(event.agent, idx);
          break;
        }
        case "agent_completed": {
          const idx = activeAgentIdx.current.get(event.agent);
          if (idx !== undefined) {
            updateAt(idx, {
              status: "done",
              Icon: CheckCircle2,
              detail:
                event.candidate_files !== undefined
                  ? `${event.candidate_files} candidate files`
                  : undefined,
            });
            activeAgentIdx.current.delete(event.agent);
          } else {
            append({
              label: agentLabel(event.agent),
              status: "done",
              Icon: CheckCircle2,
            });
          }
          break;
        }
        case "investigation_completed":
          append({
            label: "Investigation complete",
            detail: event.effort ? `Effort: ${event.effort}` : undefined,
            status: "done",
            Icon: CheckCircle2,
          });
          break;
        case "investigation_failed":
          append({
            label: "Investigation failed",
            detail: event.error?.slice(0, 200),
            status: "error",
            Icon: XCircle,
          });
          break;
        case "stream_timeout":
          appendError("Stream timed out — refreshing.");
          break;
      }
    }

    function appendError(msg: string) {
      append({ label: "Error", detail: msg, status: "error", Icon: XCircle });
      setDone(true);
      setTimeout(() => router.refresh(), 800);
    }

    function append(item: Omit<TimelineItem, "id">) {
      setItems((prev) => [...prev, { ...item, id: idCounter.current++ }]);
    }

    function appendAndIndex(item: Omit<TimelineItem, "id">): number {
      let nextIdx = -1;
      setItems((prev) => {
        nextIdx = prev.length;
        return [...prev, { ...item, id: idCounter.current++ }];
      });
      return nextIdx;
    }

    function updateAt(idx: number, patch: Partial<TimelineItem>) {
      setItems((prev) => {
        if (idx < 0 || idx >= prev.length) return prev;
        const next = [...prev];
        next[idx] = { ...next[idx], ...patch };
        return next;
      });
    }

    consume();
    return () => controller.abort();
  }, [investigationId, router]);

  return (
    <div className="rounded-lg border border-border/60 bg-muted/10 p-5">
      <div className="mb-4 flex items-center gap-2 text-sm font-medium">
        {done ? (
          <CheckCircle2 className="size-4 text-emerald-500" />
        ) : (
          <Loader2 className="size-4 animate-spin text-primary" />
        )}
        {done ? "Stream finished. Refreshing…" : "Streaming agent progress…"}
      </div>

      <ol className="relative space-y-3 pl-6">
        {/* connector line */}
        <span
          className="pointer-events-none absolute left-2 top-1.5 bottom-1.5 w-px bg-border"
          aria-hidden
        />
        {items.length === 0 && (
          <li className="text-sm text-muted-foreground italic">
            Waiting for first event…
          </li>
        )}
        {items.map((item) => (
          <li key={item.id} className="relative">
            <span
              className={cn(
                "absolute -left-[18px] top-0.5 flex size-4 items-center justify-center rounded-full ring-4 ring-background",
                item.status === "active" && "text-primary",
                item.status === "done" && "text-emerald-500",
                item.status === "error" && "text-rose-500",
                item.status === "pending" && "text-muted-foreground",
              )}
            >
              <item.Icon
                className={cn(
                  "size-3.5",
                  item.status === "active" && "animate-spin",
                )}
              />
            </span>
            <div className="text-sm">
              <div className="font-medium">{item.label}</div>
              {item.detail && (
                <div className="text-xs text-muted-foreground mt-0.5">
                  {item.detail}
                </div>
              )}
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

function agentLabel(agent: string): string {
  // Convert snake_case to title case.
  return agent
    .split("_")
    .map((s) => s.charAt(0).toUpperCase() + s.slice(1))
    .join(" ");
}

// Imported but only to silence lint if FileCode ends up unused in some builds.
void FileCode;
