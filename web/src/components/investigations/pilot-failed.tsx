import { AlertTriangle } from "lucide-react";
import type { PilotRun } from "@/lib/api/types";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { PilotLauncher } from "@/components/investigations/pilot-launcher";

/**
 * Shown when the latest pilot ended in `rejected` or `failed`.
 *
 * `failed` = infrastructure/clone/sandbox problem — likely transient.
 * `rejected` = the Reviewer loop tried N times and ran out of ideas, or
 * the LLM honestly admitted it couldn't fix this from the candidates given.
 */
export function PilotFailed({
  investigationId,
  pilot,
}: {
  investigationId: string;
  pilot: PilotRun;
}) {
  const isRejected = pilot.status === "rejected";

  return (
    <div className="space-y-3">
      <Card className="border-amber-500/30 bg-amber-500/5">
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2 text-amber-600 dark:text-amber-500">
            <AlertTriangle className="size-4" />
            {isRejected
              ? "Autonomous pilot couldn't produce a working patch"
              : "Autonomous pilot failed"}
          </CardTitle>
          <CardDescription>
            {pilot.summary || pilot.error || "No detail provided."}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2 text-sm text-muted-foreground">
          <div className="flex flex-wrap gap-x-4 gap-y-1 font-mono text-xs">
            <span>attempts: {pilot.attempts_made}</span>
            <span>pilot id: {pilot.id.slice(0, 8)}</span>
            {pilot.completed_at && (
              <span>finished {new Date(pilot.completed_at).toUTCString().replace(" GMT", "")}</span>
            )}
          </div>
          {pilot.error && (
            <pre className="mt-2 max-h-40 overflow-auto rounded bg-muted px-3 py-2 text-xs whitespace-pre-wrap">
              {pilot.error}
            </pre>
          )}
        </CardContent>
      </Card>

      <PilotLauncher investigationId={investigationId} firstTime={false} />
    </div>
  );
}
