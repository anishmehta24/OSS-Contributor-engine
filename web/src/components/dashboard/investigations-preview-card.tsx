import Link from "next/link";
import {
  ArrowRight,
  CheckCircle2,
  Loader2,
  Microscope,
  XCircle,
} from "lucide-react";
import { fapi } from "@/lib/api/server";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { InvestigationRow } from "@/lib/api/types";

const TOP_N = 5;

export async function InvestigationsPreviewCard() {
  const rows = (await fapi.recentInvestigations(TOP_N).catch(() => null)) ?? [];

  return (
    <Card className="border-border/60">
      <CardHeader className="flex flex-row items-start justify-between space-y-0">
        <div className="space-y-1.5">
          <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-muted-foreground">
            <Microscope className="size-3.5" />
            Recent investigations
          </div>
          <CardTitle className="text-lg">
            {rows.length > 0 ? `${rows.length} runs` : "No investigations yet"}
          </CardTitle>
        </div>
        <Button
          render={<Link href="/investigations" />}
          nativeButton={false}
          variant="ghost"
          size="sm"
        >
          View all <ArrowRight className="ml-1 size-3.5" />
        </Button>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Pick a match and hit <span className="font-medium">Investigate</span> —
            four specialist agents will read the issue, map the repo, scan
            history, and synthesize an approach.
          </p>
        ) : (
          <ul className="divide-y divide-border/60">
            {rows.map((r) => (
              <InvestigationRowItem key={r.id} r={r} />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

const STATUS_META = {
  queued: { Icon: Loader2, label: "queued", className: "text-muted-foreground" },
  running: {
    Icon: Loader2,
    label: "running",
    className: "text-primary animate-spin",
  },
  completed: {
    Icon: CheckCircle2,
    label: "completed",
    className: "text-emerald-500",
  },
  failed: { Icon: XCircle, label: "failed", className: "text-destructive" },
} as const;

function InvestigationRowItem({ r }: { r: InvestigationRow }) {
  const meta = STATUS_META[r.status] ?? STATUS_META.queued;
  const title =
    r.repo && r.issue_number ? `${r.repo}#${r.issue_number}` : "(pending)";

  return (
    <li className="py-2.5 first:pt-0 last:pb-0">
      <Link
        href={`/investigations/${r.id}`}
        className="group flex items-center justify-between gap-3"
      >
        <div className="min-w-0">
          <div className="text-sm font-medium group-hover:text-primary transition-colors">
            {title}
          </div>
          {r.error && (
            <p className="mt-0.5 text-xs text-muted-foreground truncate">
              {r.error}
            </p>
          )}
        </div>
        <Badge
          variant="secondary"
          className="shrink-0 gap-1 font-normal capitalize"
        >
          <meta.Icon className={`size-3 ${meta.className}`} />
          {meta.label}
        </Badge>
      </Link>
    </li>
  );
}
