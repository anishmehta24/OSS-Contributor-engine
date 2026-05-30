/**
 * Pilot panel — the v3 autonomous-fix UI on the investigation detail page.
 *
 * Server Component: fetches the latest PilotRun and dispatches to the
 * right sub-component based on status.
 *
 *   no pilot   → <PilotLauncher>      (intro + "Try fix" button)
 *   queued/running → <PilotProgress>  (polls + shows status)
 *   rate_limited → <PilotRateLimited> (transient capacity wall + retry)
 *   failed/rejected → <PilotFailed>   (error + "Try again" button)
 *   accepted   → <PilotReview>        (diff + approval flow)
 */
import { fapi } from "@/lib/api/server";
import { PilotFailed } from "@/components/investigations/pilot-failed";
import { PilotLauncher } from "@/components/investigations/pilot-launcher";
import { PilotProgress } from "@/components/investigations/pilot-progress";
import { PilotRateLimited } from "@/components/investigations/pilot-rate-limited";
import { PilotReview } from "@/components/investigations/pilot-review";

export async function PilotPanel({
  investigationId,
}: {
  investigationId: string;
}) {
  const pilot = await fapi.latestPilot(investigationId);

  // No pilot yet — show the launcher.
  if (!pilot) {
    return <PilotLauncher investigationId={investigationId} firstTime />;
  }

  if (pilot.status === "queued" || pilot.status === "running") {
    return (
      <PilotProgress investigationId={investigationId} pilot={pilot} />
    );
  }

  if (pilot.status === "rate_limited") {
    return (
      <PilotRateLimited investigationId={investigationId} pilot={pilot} />
    );
  }

  if (pilot.status === "failed" || pilot.status === "rejected") {
    return (
      <PilotFailed investigationId={investigationId} pilot={pilot} />
    );
  }

  // accepted
  return (
    <PilotReview investigationId={investigationId} pilot={pilot} />
  );
}
