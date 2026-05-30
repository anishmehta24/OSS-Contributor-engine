import Link from "next/link";
import { ArrowRight, Search, Star } from "lucide-react";
import { fapi } from "@/lib/api/server";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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
    <Card className="border-border/60">
      <CardHeader className="flex flex-row items-start justify-between space-y-0">
        <div className="space-y-1.5">
          <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-muted-foreground">
            <Search className="size-3.5" />
            Latest matches
          </div>
          <CardTitle className="text-lg">
            {matches.length > 0
              ? `${matches.length} fresh fits`
              : "No matches yet"}
          </CardTitle>
        </div>
        <Button
          render={<Link href="/matches" />}
          nativeButton={false}
          variant="ghost"
          size="sm"
        >
          View all <ArrowRight className="ml-1 size-3.5" />
        </Button>
      </CardHeader>
      <CardContent>
        {matches.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Once you have a profile + a hunted issue pool, ranked matches
            appear here. Run{" "}
            <code className="rounded bg-muted px-1 py-0.5 text-xs">
              python -m app.workers hunt
            </code>{" "}
            to populate the pool.
          </p>
        ) : (
          <ul className="divide-y divide-border/60">
            {matches.map((m) => (
              <MatchRow key={m.issue_id} m={m} />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function MatchRow({ m }: { m: RankedMatch }) {
  return (
    <li className="py-2.5 first:pt-0 last:pb-0">
      <div className="flex items-baseline justify-between gap-3">
        <div className="min-w-0">
          <a
            href={m.html_url}
            target="_blank"
            rel="noreferrer"
            className="text-sm font-medium hover:text-primary transition-colors"
          >
            {m.repo_full_name}
            <span className="text-muted-foreground">
              #{m.issue_number}
            </span>
          </a>
          <p className="mt-0.5 text-xs text-muted-foreground truncate">
            {m.title}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2 text-xs text-muted-foreground">
          <span className="flex items-center gap-1 font-mono tabular-nums">
            <Star className="size-3" />
            {m.stargazers_count >= 1000
              ? `${(m.stargazers_count / 1000).toFixed(1)}k`
              : m.stargazers_count}
          </span>
          {m.difficulty && (
            <Badge variant="secondary" className="font-normal capitalize">
              {m.difficulty}
            </Badge>
          )}
        </div>
      </div>
    </li>
  );
}
