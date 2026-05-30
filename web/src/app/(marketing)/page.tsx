import Link from "next/link";
import {
  Brain,
  GitPullRequestArrow,
  Search,
  Sparkles,
  Wand2,
} from "lucide-react";
import { fapi } from "@/lib/api/server";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const features = [
  {
    icon: Brain,
    title: "Profile from real work",
    body: "Reads your top GitHub repos to figure out what you actually build — languages, frameworks, domains, experience level.",
  },
  {
    icon: Search,
    title: "Ranked, explainable matches",
    body: "Each issue is scored on skill match, repo health, freshness, difficulty, and impact — with a one-line 'why this fits you'.",
  },
  {
    icon: Sparkles,
    title: "Multi-agent investigation",
    body: "Four specialist agents read the issue, map the repo, scan commit history, and synthesize an approach in ~15 seconds.",
  },
  {
    icon: Wand2,
    title: "Draft a real comment",
    body: "Tone-guarded pitch writer produces a comment that doesn't sound AI-generated. Copy, edit, post.",
  },
];

export default async function LandingPage() {
  // Pull in live numbers — best-effort, swallow errors so a broken backend
  // doesn't break the marketing page.
  const [stats, cost] = await Promise.all([
    fapi.dbStats().catch(() => null),
    fapi.globalCost().catch(() => null),
  ]);
  const hasStats = (stats?.users ?? 0) > 0 || (cost?.total_calls ?? 0) > 0;

  return (
    <div className="mx-auto max-w-6xl px-6">
      {/* Hero */}
      <section className="relative pt-20 pb-24 sm:pt-28 sm:pb-32">
        <div className="absolute inset-x-0 top-10 -z-10 mx-auto h-72 max-w-3xl rounded-full bg-primary/10 blur-3xl" />
        <div className="mx-auto max-w-3xl text-center">
          <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-border/50 bg-background/50 px-3 py-1 text-xs text-muted-foreground">
            <GitPullRequestArrow className="h-3.5 w-3.5 text-primary" />
            Multi-agent system &middot; GSoC-aware
          </div>
          <h1 className="text-balance text-4xl font-semibold leading-tight tracking-tight sm:text-6xl">
            Open-source issues that{" "}
            <span className="text-primary">actually fit your skills</span>.
          </h1>
          <p className="mt-6 text-balance text-lg leading-relaxed text-muted-foreground sm:text-xl">
            Five agents profile your GitHub history, hunt matching issues,
            investigate one end-to-end, and draft a comment you&apos;d feel
            comfortable posting.
          </p>
          <div className="mt-10 flex flex-wrap items-center justify-center gap-3">
            <Button render={<Link href="/signin" />} nativeButton={false} size="lg">
              Sign in with GitHub
            </Button>
            <Button
              render={<Link href="#how-it-works" />}
              nativeButton={false}
              size="lg"
              variant="ghost"
            >
              How it works
            </Button>
          </div>

          {/* Live stats — credibility signal. Hidden until the system has
              actually done some work, so a freshly-cloned repo doesn't show
              embarrassing zeroes. */}
          {hasStats && (
            <dl className="mx-auto mt-14 grid max-w-2xl grid-cols-2 gap-y-6 sm:grid-cols-4">
              <Stat
                value={(stats?.users ?? 0).toLocaleString()}
                label="developers profiled"
              />
              <Stat
                value={(stats?.investigations ?? 0).toLocaleString()}
                label="investigations run"
              />
              <Stat
                value={(stats?.issues ?? 0).toLocaleString()}
                label="issues tracked"
              />
              <Stat
                value={`$${(cost?.total_cost_usd ?? 0).toFixed(2)}`}
                label="spent on LLMs"
              />
            </dl>
          )}
        </div>
      </section>

      {/* Features */}
      <section id="how-it-works" className="pb-24">
        <div className="mx-auto mb-12 max-w-2xl text-center">
          <h2 className="text-3xl font-semibold tracking-tight">
            Built like a small engineering team.
          </h2>
          <p className="mt-3 text-muted-foreground">
            Specialist agents collaborate end-to-end. You stay in the loop and
            ship the final comment.
          </p>
        </div>
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
          {features.map(({ icon: Icon, title, body }) => (
            <Card
              key={title}
              className="border-border/60 transition-colors hover:border-primary/40"
            >
              <CardHeader>
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <Icon className="h-5 w-5" />
                </div>
                <CardTitle className="mt-3 text-lg">{title}</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm leading-relaxed text-muted-foreground">
                  {body}
                </p>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      {/* Closing CTA */}
      <section className="pb-24" id="cta">
        <div className="rounded-2xl border border-border/60 bg-gradient-to-br from-primary/10 via-background to-background p-8 text-center sm:p-12">
          <h3 className="text-2xl font-semibold tracking-tight">
            Ready to find your next contribution?
          </h3>
          <p className="mt-2 text-muted-foreground">
            Authorize once with your GitHub account — we only read public data.
          </p>
          <Button
            render={<Link href="/signin" />}
            nativeButton={false}
            size="lg"
            className="mt-6"
          >
            Get started
          </Button>
        </div>
      </section>
    </div>
  );
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div className="flex flex-col items-center text-center">
      <dt className="text-3xl font-semibold tabular-nums sm:text-4xl">
        {value}
      </dt>
      <dd className="mt-1 text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </dd>
    </div>
  );
}
