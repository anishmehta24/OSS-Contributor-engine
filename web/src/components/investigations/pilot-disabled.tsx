import { Server } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

/**
 * Shown when the backend reports `pilot_enabled=false`.
 *
 * The Pilot needs a Docker daemon (for the sandbox) and persistent disk
 * (for git clones), neither of which exists on free PaaS tiers (Render /
 * Vercel / Fly free). The hosted demo turns it off and points users to a
 * local clone if they want to actually run a pilot end-to-end.
 */
export function PilotDisabled() {
  return (
    <Card className="border-border/60 border-dashed bg-muted/30">
      <CardHeader>
        <CardTitle className="text-base flex items-center gap-2 text-muted-foreground">
          <Server className="size-4" />
          Autonomous Pilot — disabled in this deployment
        </CardTitle>
        <CardDescription>
          The Pilot opens a sandboxed Docker container, git-clones the repo,
          and runs the project&apos;s tests in a loop. Free hosting tiers
          don&apos;t give us a Docker daemon or persistent disk, so the
          hosted demo turns it off. Everything else here — profiling,
          matching, the multi-agent investigation — is fully live.
        </CardDescription>
      </CardHeader>
      <CardContent className="text-sm text-muted-foreground">
        To try the Pilot end-to-end, clone the repo and run it locally — the
        full pipeline boots in one command. See{" "}
        <code className="text-xs">DEPLOY.md</code> for the why.
      </CardContent>
    </Card>
  );
}
