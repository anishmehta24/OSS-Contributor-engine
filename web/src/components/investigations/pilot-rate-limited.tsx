import { Hourglass } from "lucide-react";
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
 * Shown when the latest pilot ended in `rate_limited`.
 *
 * This is NOT a failure to fix the issue — every LLM provider was throttled
 * or unavailable (free-tier tokens-per-minute caps, or an upstream outage),
 * so the run stopped before it could produce a patch. The fix is simply to
 * wait a moment and retry; the agents never got a fair shot at the problem.
 */
export function PilotRateLimited({
  investigationId,
  pilot,
}: {
  investigationId: string;
  pilot: PilotRun;
}) {
  return (
    <div className="space-y-3">
      <Card className="border-sky-500/30 bg-sky-500/5">
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2 text-sky-600 dark:text-sky-400">
            <Hourglass className="size-4" />
            Paused — LLM providers were rate-limited
          </CardTitle>
          <CardDescription>
            {pilot.summary ||
              "Every model provider was throttled or unavailable, so the pilot couldn't finish. This is a temporary capacity limit, not a problem with the issue — retry in a minute."}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2 text-sm text-muted-foreground">
          <div className="flex flex-wrap gap-x-4 gap-y-1 font-mono text-xs">
            <span>attempts: {pilot.attempts_made}</span>
            <span>pilot id: {pilot.id.slice(0, 8)}</span>
            {pilot.completed_at && (
              <span>
                paused{" "}
                {new Date(pilot.completed_at).toUTCString().replace(" GMT", "")}
              </span>
            )}
          </div>
        </CardContent>
      </Card>

      <PilotLauncher investigationId={investigationId} firstTime={false} />
    </div>
  );
}
