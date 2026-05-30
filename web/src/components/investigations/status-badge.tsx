import { CheckCircle2, Clock, Loader2, XCircle } from "lucide-react";
import type { InvestigationRow } from "@/lib/api/types";
import { Badge } from "@/components/ui/badge";

const META: Record<
  InvestigationRow["status"],
  { Icon: React.ComponentType<{ className?: string }>; label: string; cls: string }
> = {
  queued: {
    Icon: Clock,
    label: "queued",
    cls: "bg-muted text-muted-foreground border-border",
  },
  running: {
    Icon: Loader2,
    label: "running",
    cls: "bg-primary/15 text-primary border-primary/30",
  },
  completed: {
    Icon: CheckCircle2,
    label: "completed",
    cls: "bg-emerald-500/15 text-emerald-500 border-emerald-500/30",
  },
  failed: {
    Icon: XCircle,
    label: "failed",
    cls: "bg-rose-500/15 text-rose-500 border-rose-500/30",
  },
};

export function StatusBadge({
  status,
}: {
  status: InvestigationRow["status"];
}) {
  const meta = META[status] ?? META.queued;
  const spinning = status === "running";
  return (
    <Badge
      variant="outline"
      className={`gap-1 font-normal capitalize ${meta.cls}`}
    >
      <meta.Icon className={`size-3 ${spinning ? "animate-spin" : ""}`} />
      {meta.label}
    </Badge>
  );
}
