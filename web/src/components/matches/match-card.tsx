import { ExternalLink, Star } from "lucide-react";
import type { RankedMatch } from "@/lib/api/types";
import { ScoreBars } from "@/components/matches/score-bars";
import { InvestigateButton } from "@/components/matches/investigate-button";

const DIFFICULTY_STYLE: Record<string, string> = {
  easy: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400",
  medium: "bg-amber-500/15 text-amber-600 dark:text-amber-400",
  hard: "bg-rose-500/15 text-rose-600 dark:text-rose-400",
};

function formatStars(n: number): string {
  if (n >= 10_000) return `${(n / 1000).toFixed(0)}k`;
  if (n >= 1_000) return `${(n / 1000).toFixed(1)}k`;
  return n.toLocaleString();
}

export function MatchCard({
  match,
  rank,
}: {
  match: RankedMatch;
  rank: number;
}) {
  const fit = Math.round(match.final_score * 100);

  return (
    <article className="rounded-xl border border-border bg-card transition-colors hover:border-primary/40">
      <div className="flex flex-col gap-5 p-5 sm:flex-row">
        {/* Left rail — rank + the fit score as the hero number */}
        <div className="flex shrink-0 flex-row items-center gap-4 sm:w-20 sm:flex-col sm:items-center sm:gap-1 sm:border-r sm:border-border sm:pr-5 sm:text-center">
          <span className="font-mono text-[0.6rem] uppercase tracking-wide text-muted-foreground">
            #{rank}
          </span>
          <div className="flex items-baseline gap-1 sm:flex-col sm:items-center sm:gap-0">
            <span className="font-heading text-4xl font-medium leading-none tabular-nums text-primary">
              {fit}
            </span>
            <span className="font-mono text-[0.6rem] uppercase tracking-wide text-muted-foreground">
              fit
            </span>
          </div>
        </div>

        {/* Main column */}
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <a
                href={match.html_url}
                target="_blank"
                rel="noreferrer"
                className="group inline-flex items-center gap-1.5 font-mono text-xs text-muted-foreground transition-colors hover:text-primary"
              >
                <span className="truncate">{match.repo_full_name}</span>
                <span>#{match.issue_number}</span>
                <span className="inline-flex items-center gap-0.5">
                  <Star className="size-3" />
                  {formatStars(match.stargazers_count)}
                </span>
                <ExternalLink className="size-3 opacity-0 transition-opacity group-hover:opacity-100" />
              </a>
              <h3 className="mt-1.5 text-lg font-medium leading-snug">
                {match.title}
              </h3>
            </div>
            {match.difficulty && (
              <span
                className={`shrink-0 rounded-full px-2.5 py-1 text-xs font-medium capitalize ${
                  DIFFICULTY_STYLE[match.difficulty] ?? "bg-muted text-muted-foreground"
                }`}
              >
                {match.difficulty}
              </span>
            )}
          </div>

          {match.why_it_fits && (
            <blockquote className="mt-3 border-l-2 border-primary/40 pl-3 text-sm italic text-muted-foreground">
              {match.why_it_fits}
            </blockquote>
          )}

          <div className="mt-5">
            <ScoreBars match={match} />
          </div>

          <div className="mt-5 flex items-center justify-between gap-3 border-t border-border pt-4">
            <div className="flex min-w-0 flex-wrap gap-1">
              {match.labels.slice(0, 4).map((l) => (
                <span
                  key={l}
                  className="rounded-md bg-secondary px-1.5 py-0.5 font-mono text-[0.65rem] text-secondary-foreground"
                >
                  {l}
                </span>
              ))}
            </div>
            <InvestigateButton
              repo={match.repo_full_name}
              issueNumber={match.issue_number}
            />
          </div>
        </div>
      </div>
    </article>
  );
}
