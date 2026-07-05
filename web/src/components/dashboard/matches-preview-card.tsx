import Link from "next/link";
import { Search, Star } from "lucide-react";
import { fapi } from "@/lib/api/server";
import type { RankedMatch } from "@/lib/api/types";

const TOP_N = 4;

export async function MatchesPreviewCard() {
  // 409 from /matches means "no profile yet" — render the empty state
  // rather than crashing.
  const response = await fapi
    .matches({ top: TOP_N, explain: false })
    .catch(() => null);
  const matches = response?.matches ?? [];

  return (
    <section className="flex h-full flex-col rounded-xl border border-border bg-card p-6">
      <div className="flex items-center justify-between">
        <p className="flex items-center gap-2 font-mono text-[0.65rem] uppercase tracking-[0.15em] text-muted-foreground">
          <Search className="size-3.5" />
          Latest matches
        </p>
        <Link
          href="/matches"
          className="text-xs font-medium text-muted-foreground transition-colors hover:text-primary"
        >
          View all →
        </Link>
      </div>

      {matches.length === 0 ? (
        <div className="mt-3 flex flex-1 flex-col justify-center">
          <h2 className="text-xl font-medium">No matches yet</h2>
          <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
            Once you have a profile and the issue pool is populated, your ranked
            matches show up here.
          </p>
        </div>
      ) : (
        <ol className="mt-4 divide-y divide-border">
          {matches.map((m, i) => (
            <MatchRow key={m.issue_id} m={m} rank={i + 1} />
          ))}
        </ol>
      )}
    </section>
  );
}

function MatchRow({ m, rank }: { m: RankedMatch; rank: number }) {
  return (
    <li className="flex items-center gap-4 py-3 first:pt-0 last:pb-0">
      <span className="font-heading text-lg font-medium tabular-nums text-muted-foreground">
        {String(rank).padStart(2, "0")}
      </span>
      <div className="min-w-0 flex-1">
        <a
          href={m.html_url}
          target="_blank"
          rel="noreferrer"
          className="text-sm font-medium transition-colors hover:text-primary"
        >
          {m.repo_full_name}
          <span className="text-muted-foreground">#{m.issue_number}</span>
        </a>
        <p className="mt-0.5 truncate text-xs text-muted-foreground">
          {m.title}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-3">
        <span className="flex items-center gap-1 font-mono text-xs tabular-nums text-muted-foreground">
          <Star className="size-3" />
          {m.stargazers_count >= 1000
            ? `${(m.stargazers_count / 1000).toFixed(1)}k`
            : m.stargazers_count}
        </span>
        <span className="rounded-full bg-primary/10 px-2 py-0.5 font-mono text-xs font-medium text-primary">
          {m.final_score.toFixed(2)}
        </span>
      </div>
    </li>
  );
}
