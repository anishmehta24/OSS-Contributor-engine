import { cn } from "@/lib/utils";

const COMPONENTS = [
  { key: "skill_match", label: "Skill" },
  { key: "repo_health", label: "Health" },
  { key: "freshness", label: "Fresh" },
  { key: "difficulty_match", label: "Diff" },
  { key: "impact", label: "Impact" },
] as const;

type Match = {
  skill_match: number;
  repo_health: number;
  freshness: number;
  difficulty_match: number;
  impact: number;
};

/**
 * Compact horizontal bars for the 5 score components. Numbers are 0-1.
 * We don't show the values numerically — too much density. The bar widths
 * are the signal.
 */
export function ScoreBars({ match }: { match: Match }) {
  return (
    <dl className="grid grid-cols-5 gap-x-3 gap-y-1">
      {COMPONENTS.map(({ key, label }) => {
        const value = Math.max(0, Math.min(1, match[key] ?? 0));
        const pct = Math.round(value * 100);
        return (
          <div key={key} className="space-y-0.5">
            <dt className="flex items-center justify-between text-[10px] uppercase tracking-wide text-muted-foreground">
              <span>{label}</span>
              <span className="font-mono tabular-nums">{pct}</span>
            </dt>
            <dd>
              <div className="h-1 w-full overflow-hidden rounded-full bg-muted">
                <div
                  className={cn(
                    "h-full rounded-full transition-all",
                    pct >= 70
                      ? "bg-primary"
                      : pct >= 40
                        ? "bg-primary/60"
                        : "bg-primary/30",
                  )}
                  style={{ width: `${pct}%` }}
                />
              </div>
            </dd>
          </div>
        );
      })}
    </dl>
  );
}
