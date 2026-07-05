import Link from "next/link";
import { Brain, Search, Sparkles, Wand2 } from "lucide-react";
import { fapi } from "@/lib/api/server";
import { Button } from "@/components/ui/button";

const features = [
  {
    icon: Brain,
    title: "Profile from real work",
    body: "Reads your top GitHub repos to figure out what you actually build — languages, frameworks, domains, and experience level.",
  },
  {
    icon: Search,
    title: "Ranked, explainable matches",
    body: "Every issue is scored on skill match, repo health, freshness, difficulty, and impact — each with a one-line 'why this fits you'.",
  },
  {
    icon: Sparkles,
    title: "Multi-agent investigation",
    body: "Four specialist agents read the issue, map the repo, scan commit history, and synthesize an approach in about fifteen seconds.",
  },
  {
    icon: Wand2,
    title: "Draft a real comment",
    body: "A tone-guarded pitch writer produces a comment that doesn't read as AI-generated. Copy, edit, and post it yourself.",
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
    <div className="mx-auto max-w-5xl px-6">
      {/* Hero */}
      <section className="pt-24 pb-20 sm:pt-32 sm:pb-24">
        <div className="mx-auto max-w-3xl text-center">
          <p className="font-mono text-xs uppercase tracking-[0.22em] text-muted-foreground">
            Multi-agent system · GSoC-aware
          </p>
          <h1 className="mt-6 text-balance text-[2.6rem] font-medium leading-[1.05] sm:text-6xl">
            Open-source issues that{" "}
            <span className="italic text-primary">actually fit your skills</span>
            .
          </h1>
          <p className="mx-auto mt-6 max-w-xl text-balance text-lg leading-relaxed text-muted-foreground">
            Five agents profile your GitHub history, hunt matching issues,
            investigate one end-to-end, and draft a comment you&apos;d feel
            comfortable posting.
          </p>
          <div className="mt-9 flex flex-wrap items-center justify-center gap-3">
            <Button render={<Link href="/signin" />} nativeButton={false} size="lg">
              Sign in with GitHub
            </Button>
            <Button
              render={<Link href="#how-it-works" />}
              nativeButton={false}
              size="lg"
              variant="ghost"
            >
              How it works →
            </Button>
          </div>
        </div>

        {/* Live stats — credibility signal. Hidden until the system has
            actually done some work, so a freshly-cloned repo doesn't show
            embarrassing zeroes. */}
        {hasStats && (
          <dl className="mx-auto mt-20 grid max-w-3xl grid-cols-2 divide-x divide-y divide-border border-y border-border sm:grid-cols-4 sm:divide-y-0">
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
      </section>

      {/* Features */}
      <section id="how-it-works" className="border-t border-border py-20">
        <div className="mx-auto mb-14 max-w-2xl text-center">
          <p className="font-mono text-xs uppercase tracking-[0.22em] text-muted-foreground">
            How it works
          </p>
          <h2 className="mt-4 text-3xl font-medium sm:text-4xl">
            Built like a small engineering team.
          </h2>
          <p className="mt-4 text-muted-foreground">
            Specialist agents collaborate end-to-end. You stay in the loop and
            ship the final comment.
          </p>
        </div>
        <div className="grid grid-cols-1 gap-px overflow-hidden rounded-xl border border-border bg-border sm:grid-cols-2">
          {features.map(({ icon: Icon, title, body }, i) => (
            <div
              key={title}
              className="group bg-card p-7 transition-colors hover:bg-accent/40"
            >
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs text-muted-foreground">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <Icon className="h-4 w-4 text-muted-foreground transition-colors group-hover:text-primary" />
              </div>
              <h3 className="mt-4 text-xl font-medium">{title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                {body}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* Closing CTA */}
      <section className="border-t border-border py-20" id="cta">
        <div className="mx-auto max-w-2xl text-center">
          <h3 className="text-3xl font-medium sm:text-4xl">
            Ready to find your next contribution?
          </h3>
          <p className="mx-auto mt-4 max-w-md text-muted-foreground">
            Authorize once with your GitHub account — we only ever read public
            data.
          </p>
          <Button
            render={<Link href="/signin" />}
            nativeButton={false}
            size="lg"
            className="mt-8"
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
    <div className="flex flex-col items-center px-4 py-6 text-center">
      <dt className="font-heading text-3xl font-medium tabular-nums sm:text-4xl">
        {value}
      </dt>
      <dd className="mt-1.5 font-mono text-[0.68rem] uppercase tracking-wide text-muted-foreground">
        {label}
      </dd>
    </div>
  );
}
