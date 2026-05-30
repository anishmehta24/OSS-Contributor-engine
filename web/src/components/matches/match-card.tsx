import { ExternalLink, Star } from "lucide-react";
import type { RankedMatch } from "@/lib/api/types";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { ScoreBars } from "@/components/matches/score-bars";
import { InvestigateButton } from "@/components/matches/investigate-button";

const DIFFICULTY_STYLE: Record<string, string> = {
  easy: "bg-emerald-500/15 text-emerald-500 border-emerald-500/30",
  medium: "bg-amber-500/15 text-amber-500 border-amber-500/30",
  hard: "bg-rose-500/15 text-rose-500 border-rose-500/30",
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
  const finalPct = Math.round(match.final_score * 100);

  return (
    <Card className="border-border/60 transition-colors hover:border-primary/40">
      <CardContent className="p-5">
        {/* Top row: rank + repo + meta */}
        <div className="mb-2 flex items-baseline gap-3">
          <span className="font-mono text-xs text-muted-foreground tabular-nums w-6 shrink-0">
            #{rank}
          </span>
          <a
            href={match.html_url}
            target="_blank"
            rel="noreferrer"
            className="group flex min-w-0 items-baseline gap-1 text-sm font-medium hover:text-primary transition-colors"
          >
            <span className="truncate">{match.repo_full_name}</span>
            <span className="text-muted-foreground group-hover:text-primary/80">
              #{match.issue_number}
            </span>
            <ExternalLink className="size-3 opacity-0 group-hover:opacity-100 transition-opacity" />
          </a>
          <div className="ml-auto flex shrink-0 items-center gap-2 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1 font-mono tabular-nums">
              <Star className="size-3" />
              {formatStars(match.stargazers_count)}
            </span>
            {match.difficulty && (
              <Badge
                variant="outline"
                className={`font-normal capitalize ${
                  DIFFICULTY_STYLE[match.difficulty] ?? ""
                }`}
              >
                {match.difficulty}
              </Badge>
            )}
          </div>
        </div>

        {/* Title */}
        <p className="mb-3 pl-9 text-base leading-snug text-foreground">
          {match.title}
        </p>

        {/* Why-it-fits (optional) */}
        {match.why_it_fits && (
          <blockquote className="mb-4 pl-9 text-sm italic text-muted-foreground border-l-2 border-primary/30 ml-9 -ml-px pl-3">
            {match.why_it_fits}
          </blockquote>
        )}

        {/* Bottom row: score bars + final + action */}
        <div className="flex items-end justify-between gap-4 pl-9 pt-2">
          <div className="flex-1 min-w-0 max-w-2xl">
            <ScoreBars match={match} />
          </div>
          <div className="flex shrink-0 items-end gap-3">
            <div className="flex flex-col items-end">
              <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                Score
              </span>
              <span className="font-mono text-lg font-semibold tabular-nums leading-none">
                {(match.final_score).toFixed(2)}
                <span className="text-xs text-muted-foreground ml-1">
                  / 1
                </span>
              </span>
            </div>
            <InvestigateButton
              repo={match.repo_full_name}
              issueNumber={match.issue_number}
            />
          </div>
        </div>

        {/* Labels (subtle, bottom) */}
        {match.labels.length > 0 && (
          <div className="mt-3 pl-9 flex flex-wrap gap-1">
            {match.labels.slice(0, 6).map((l) => (
              <Badge
                key={l}
                variant="secondary"
                className="font-normal text-[10px] py-0 px-1.5"
              >
                {l}
              </Badge>
            ))}
          </div>
        )}

        {/* Hidden — but used as a tooltip-like data attribute for the final % */}
        <span className="sr-only">
          Final score {finalPct} out of 100.
        </span>
      </CardContent>
    </Card>
  );
}
