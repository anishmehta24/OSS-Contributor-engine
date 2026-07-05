import Link from "next/link";
import { CheckCircle2, Loader2, Microscope, XCircle } from "lucide-react";
import { fapi } from "@/lib/api/server";
import type { InvestigationRow } from "@/lib/api/types";

const TOP_N = 6;

export async function InvestigationsPreviewCard() {
  const rows = (await fapi.recentInvestigations(TOP_N).catch(() => null)) ?? [];

  return (
    <section className="rounded-xl border border-border bg-card p-6">
      <div className="flex items-center justify-between">
        <p className="flex items-center gap-2 font-mono text-[0.65rem] uppercase tracking-[0.15em] text-muted-foreground">
          <Microscope className="size-3.5" />
          Recent investigations
        </p>
        <Link
          href="/investigations"
          className="text-xs font-medium text-muted-foreground transition-colors hover:text-primary"
        >
          View all →
        </Link>
      </div>

      {rows.length === 0 ? (
        <p className="mt-4 text-sm leading-relaxed text-muted-foreground">
          Pick a match and hit <span className="font-medium">Investigate</span> —
          four specialist agents read the issue, map the repo, scan history, and
          synthesize an approach.
        </p>
      ) : (
        <ul className="mt-4 grid grid-cols-1 gap-x-8 sm:grid-cols-2">
          {rows.map((r) => (
            <InvestigationRowItem key={r.id} r={r} />
          ))}
        </ul>
      )}
    </section>
  );
}

const STATUS_META = {
  queued: { Icon: Loader2, className: "text-muted-foreground" },
  running: { Icon: Loader2, className: "text-primary animate-spin" },
  completed: { Icon: CheckCircle2, className: "text-primary" },
  failed: { Icon: XCircle, className: "text-destructive" },
} as const;

function InvestigationRowItem({ r }: { r: InvestigationRow }) {
  const meta = STATUS_META[r.status] ?? STATUS_META.queued;
  const title =
    r.repo && r.issue_number ? `${r.repo}#${r.issue_number}` : "(pending)";

  return (
    <li className="border-b border-border/70 last:border-0 sm:[&:nth-last-child(2)]:border-0">
      <Link
        href={`/investigations/${r.id}`}
        className="group flex items-center gap-3 py-3"
      >
        <meta.Icon className={`size-4 shrink-0 ${meta.className}`} />
        <span className="min-w-0 flex-1 truncate text-sm font-medium transition-colors group-hover:text-primary">
          {title}
        </span>
        <span className="shrink-0 font-mono text-[0.65rem] uppercase tracking-wide text-muted-foreground">
          {r.status}
        </span>
      </Link>
    </li>
  );
}
