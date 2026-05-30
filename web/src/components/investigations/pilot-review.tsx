import { CheckCircle2, FileEdit, Sparkles } from "lucide-react";
import type { PilotRun } from "@/lib/api/types";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { PilotApprovalActions } from "@/components/investigations/pilot-approval-actions";
import { PilotDiffViewer } from "@/components/investigations/pilot-diff-viewer";

type Props = {
  investigationId: string;
  pilot: PilotRun;
};

/**
 * Shown when status='accepted'. The big screen: diff + transcript-derived
 * facts + the staged approval flow.
 */
export function PilotReview({ investigationId, pilot }: Props) {
  const tx = pilot.transcript as
    | { attempts?: Array<{
        attempt_number?: number;
        patch_result?: {
          edits_applied?: Array<{
            path?: string;
            new_file?: boolean;
            explanation?: string;
          }>;
        };
        test_result?: { classification?: string; summary?: string };
      }>; }
    | null;
  const acceptedAttempt = tx?.attempts?.find(
    (a) => a?.attempt_number === pilot.accepted_attempt_number,
  );
  const edits = acceptedAttempt?.patch_result?.edits_applied ?? [];
  const testClass = acceptedAttempt?.test_result?.classification ?? "unknown";
  const testSummary = acceptedAttempt?.test_result?.summary ?? "";

  return (
    <Card className="border-primary/30">
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <div>
            <CardTitle className="text-base flex items-center gap-2">
              <Sparkles className="size-4 text-primary" />
              Autonomous pilot result
              <Badge
                variant="outline"
                className="bg-emerald-500/15 text-emerald-500 border-emerald-500/30 font-normal"
              >
                <CheckCircle2 className="size-3 mr-1" />
                accepted
              </Badge>
            </CardTitle>
            <CardDescription className="mt-1">
              {pilot.summary || "(no summary)"}
            </CardDescription>
          </div>
          <TestBadge classification={testClass} summary={testSummary} />
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        {/* Quick facts */}
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4 text-xs">
          <Stat label="Attempts" value={String(pilot.attempts_made)} />
          <Stat
            label="Accepted on"
            value={`attempt ${pilot.accepted_attempt_number ?? "?"}`}
          />
          <Stat label="Files changed" value={String(edits.length)} />
          <Stat label="Pilot id" value={pilot.id.slice(0, 8)} mono />
        </dl>

        {/* Files changed */}
        {edits.length > 0 && (
          <section className="space-y-2">
            <h4 className="text-xs uppercase tracking-wide text-muted-foreground flex items-center gap-2">
              <FileEdit className="size-3.5" />
              Files in this patch
            </h4>
            <ul className="space-y-1.5">
              {edits.map((e, i) => (
                <li key={i} className="flex items-baseline gap-2 text-sm">
                  {e.new_file && (
                    <Badge variant="secondary" className="font-normal text-[10px]">
                      NEW
                    </Badge>
                  )}
                  <code className="font-mono text-xs">{e.path}</code>
                  {e.explanation && (
                    <span className="text-xs text-muted-foreground">
                      — {e.explanation}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* Diff */}
        {pilot.accepted_diff && (
          <section className="space-y-2">
            <h4 className="text-xs uppercase tracking-wide text-muted-foreground">
              Proposed diff
            </h4>
            <PilotDiffViewer diff={pilot.accepted_diff} />
          </section>
        )}

        {/* Staged approval flow */}
        <PilotApprovalActions
          investigationId={investigationId}
          pilot={pilot}
        />
      </CardContent>
    </Card>
  );
}

function Stat({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className={`mt-0.5 text-foreground ${mono ? "font-mono" : ""}`}>
        {value}
      </dd>
    </div>
  );
}

function TestBadge({
  classification,
  summary,
}: {
  classification: string;
  summary: string;
}) {
  const style: Record<string, string> = {
    pass: "bg-emerald-500/15 text-emerald-500 border-emerald-500/30",
    needs_env: "bg-amber-500/15 text-amber-500 border-amber-500/30",
    fail: "bg-rose-500/15 text-rose-500 border-rose-500/30",
    error: "bg-rose-500/15 text-rose-500 border-rose-500/30",
  };
  return (
    <Badge
      variant="outline"
      className={`shrink-0 font-normal ${style[classification] ?? ""}`}
      title={summary}
    >
      tests: {classification}
    </Badge>
  );
}
