import Link from "next/link";
import {
  ArrowRight,
  Brain,
  Check,
  GitPullRequestArrow,
  Search,
  Sparkles,
  Wand2,
} from "lucide-react";
import { fapi } from "@/lib/api/server";
import { GitHubIcon } from "@/components/icons";

const GITHUB_URL = "https://github.com/anishmehta24/OSS-Contributor-engine";

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
    <>
      {/* Hero */}
      <section className="mx-auto max-w-6xl px-6 pt-16 pb-20 sm:pt-24 sm:pb-24">
        <div className="max-w-3xl">
          <span className="inline-flex items-center gap-2 rounded-full border border-border bg-accent/50 px-3 py-1 text-xs font-medium uppercase tracking-[0.18em] text-primary">
            <GitHubIcon className="h-3.5 w-3.5" />
            Open source · Multi-agent
          </span>
          <h1 className="mt-6 text-balance text-5xl font-medium leading-[1.03] sm:text-7xl">
            Open-source issues
            <br />
            that <span className="italic text-primary">fit your skills</span>.
          </h1>
          <p className="mt-6 max-w-xl text-lg leading-relaxed text-muted-foreground sm:text-xl">
            Five agents profile your GitHub history, hunt matching issues,
            investigate one end-to-end, and draft a comment you&apos;d feel
            comfortable posting.
          </p>
          <div className="mt-9 flex flex-col items-start gap-3 sm:flex-row sm:items-center">
            <Link
              href="/signin"
              className="inline-flex w-full items-center justify-center gap-2 rounded-full bg-primary px-7 py-3.5 font-semibold text-primary-foreground shadow-sm transition-colors hover:bg-primary/90 sm:w-auto"
            >
              <GitHubIcon className="h-4 w-4" />
              Sign in with GitHub
            </Link>
            <a
              href={GITHUB_URL}
              target="_blank"
              rel="noreferrer"
              className="inline-flex w-full items-center justify-center gap-2 rounded-full bg-foreground px-7 py-3.5 font-semibold text-background transition-opacity hover:opacity-90 sm:w-auto"
            >
              <GitHubIcon className="h-4 w-4" />
              Star on GitHub
            </a>
          </div>
          <Link
            href="#how-it-works"
            className="mt-4 inline-flex items-center gap-1 text-sm font-medium text-muted-foreground transition-colors hover:text-primary"
          >
            See how it works <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        </div>

        {/* Product peek — a mock ranked match, the way it appears in-app. */}
        <div className="mt-16 overflow-hidden rounded-2xl border border-border bg-card shadow-[0_24px_70px_-32px_oklch(0.2_0.06_330/0.4)] sm:mt-20">
          <div className="flex items-center gap-2 border-b border-border bg-muted/40 px-4 py-3">
            <span className="h-3 w-3 rounded-full bg-primary/30" />
            <span className="h-3 w-3 rounded-full bg-border" />
            <span className="h-3 w-3 rounded-full bg-border" />
            <span className="ml-3 font-mono text-xs text-muted-foreground">
              /matches — OSS Engine
            </span>
          </div>
          <div className="p-5 sm:p-7">
            <div className="rounded-xl border border-border p-5">
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-baseline gap-3">
                  <span className="font-mono text-sm text-muted-foreground">
                    01
                  </span>
                  <div>
                    <p className="font-mono text-xs text-muted-foreground">
                      pandas-dev/pandas · good first issue
                    </p>
                    <h3 className="mt-1 text-lg font-medium">
                      Improve error message for invalid frequency strings
                    </h3>
                  </div>
                </div>
                <span className="shrink-0 rounded-full bg-primary/10 px-2.5 py-1 font-mono text-xs font-medium text-primary">
                  0.92 fit
                </span>
              </div>
              {/* Score breakdown bars */}
              <div className="mt-5 grid grid-cols-5 gap-3">
                {[
                  ["skill", 0.94],
                  ["health", 0.88],
                  ["fresh", 0.7],
                  ["difficulty", 0.9],
                  ["impact", 0.6],
                ].map(([label, v]) => (
                  <div key={label as string}>
                    <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                      <div
                        className="h-full rounded-full bg-primary"
                        style={{ width: `${(v as number) * 100}%` }}
                      />
                    </div>
                    <p className="mt-1.5 font-mono text-[0.62rem] uppercase tracking-wide text-muted-foreground">
                      {label as string}
                    </p>
                  </div>
                ))}
              </div>
              <p className="mt-5 border-l-2 border-primary/40 pl-3 text-sm italic text-muted-foreground">
                Matches your Python + pandas work; a small, well-scoped
                error-handling fix rated beginner-friendly.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* USP — the multi-agent investigation */}
      <section
        id="how-it-works"
        className="border-t border-border bg-secondary/40"
      >
        <div className="mx-auto grid max-w-6xl items-center gap-12 px-6 py-20 sm:py-24 md:grid-cols-2 lg:gap-16">
          <div>
            <span className="inline-flex items-center gap-2 rounded-full border border-border bg-accent/50 px-3 py-1 text-xs font-medium uppercase tracking-[0.18em] text-primary">
              <Sparkles className="h-3.5 w-3.5" />
              The core
            </span>
            <h2 className="mt-6 text-balance text-4xl font-medium leading-[1.05] sm:text-5xl">
              A team of agents,
              <br />
              working the issue.
            </h2>
            <p className="mt-5 max-w-md text-lg leading-relaxed text-muted-foreground">
              Send any match to the investigator and four specialists collaborate
              — reading the issue, mapping the repo, scanning history, and
              synthesizing a concrete approach in about fifteen seconds.
            </p>
            <ul className="mt-7 space-y-3">
              {[
                "Ranked matches with a transparent score breakdown",
                "End-to-end investigation report per issue",
                "A drafted comment that doesn't sound AI-generated",
              ].map((item) => (
                <li key={item} className="flex items-center gap-3">
                  <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-primary/10 text-primary">
                    <Check className="h-3 w-3" strokeWidth={3} />
                  </span>
                  <span className="text-muted-foreground">{item}</span>
                </li>
              ))}
            </ul>
            <Link
              href="/signin"
              className="mt-8 inline-flex items-center gap-2 rounded-full bg-primary px-7 py-3.5 font-semibold text-primary-foreground shadow-sm transition-colors hover:bg-primary/90"
            >
              Try it with your GitHub
            </Link>
          </div>

          {/* Dark agent-run preview */}
          <div className="overflow-hidden rounded-2xl border border-white/10 bg-[oklch(0.17_0.008_320)] shadow-[0_28px_80px_-28px_oklch(0.2_0.06_330/0.55)]">
            <div className="flex items-center gap-2 border-b border-white/10 px-4 py-3">
              <span className="relative flex h-2.5 w-2.5">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-75" />
                <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-primary" />
              </span>
              <span className="font-heading text-sm font-semibold text-white">
                Investigating
              </span>
              <span className="ml-auto font-mono text-xs text-white/40">
                ~15s
              </span>
            </div>
            <div className="space-y-3 p-5 font-mono text-[0.8rem]">
              {[
                ["Code Explorer", "mapped 18 files · entrypoint found", true],
                ["History Scanner", "3 related commits · 1 prior PR", true],
                ["Approach Synth", "drafted 4-step plan", true],
                ["Pitch Writer", "composing comment…", false],
              ].map(([agent, note, done]) => (
                <div key={agent as string} className="flex items-center gap-3">
                  <span
                    className={`grid h-5 w-5 shrink-0 place-items-center rounded-full ${
                      done
                        ? "bg-primary/20 text-primary"
                        : "bg-white/10 text-white/50"
                    }`}
                  >
                    {done ? (
                      <Check className="h-3 w-3" strokeWidth={3} />
                    ) : (
                      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" />
                    )}
                  </span>
                  <span className="text-white/90">{agent as string}</span>
                  <span className="ml-auto truncate text-white/40">
                    {note as string}
                  </span>
                </div>
              ))}
              <div className="mt-4 rounded-lg border border-white/10 bg-white/[0.03] p-3 text-white/60">
                <span className="text-primary">›</span> report ready — pitch
                drafted, tone-checked, yours to edit.
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Live stats strip */}
      {hasStats && (
        <section className="border-t border-border">
          <dl className="mx-auto grid max-w-6xl grid-cols-2 divide-x divide-y divide-border px-0 sm:grid-cols-4 sm:divide-y-0">
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
        </section>
      )}

      {/* Features */}
      <section className="border-t border-border">
        <div className="mx-auto max-w-6xl px-6 py-20 sm:py-24">
          <div className="mx-auto mb-14 max-w-2xl text-center">
            <p className="font-mono text-xs uppercase tracking-[0.22em] text-muted-foreground">
              How it works
            </p>
            <h2 className="mt-4 text-3xl font-medium sm:text-4xl">
              Built like a small engineering team.
            </h2>
          </div>
          <div className="grid grid-cols-1 gap-px overflow-hidden rounded-2xl border border-border bg-border sm:grid-cols-2 lg:grid-cols-4">
            {features.map(({ icon: Icon, title, body }, i) => (
              <div
                key={title}
                className="group bg-card p-6 transition-colors hover:bg-accent/40"
              >
                <div className="flex items-center justify-between">
                  <span className="grid h-10 w-10 place-items-center rounded-xl bg-primary/10 text-primary">
                    <Icon className="h-5 w-5" />
                  </span>
                  <span className="font-mono text-xs text-muted-foreground">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                </div>
                <h3 className="mt-5 text-lg font-medium">{title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                  {body}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Dark CTA band */}
      <section className="bg-foreground text-background">
        <div className="mx-auto max-w-6xl px-6 py-20 text-center sm:py-24">
          <GitPullRequestArrow className="mx-auto h-8 w-8 text-background/70" />
          <h2 className="mt-6 text-balance text-4xl font-medium sm:text-5xl">
            Find your next contribution.
          </h2>
          <p className="mx-auto mt-4 max-w-md text-background/70">
            Authorize once with your GitHub account — we only ever read public
            data.
          </p>
          <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <Link
              href="/signin"
              className="inline-flex w-full items-center justify-center gap-2 rounded-full bg-background px-8 py-3.5 font-semibold text-foreground transition-opacity hover:opacity-90 sm:w-auto"
            >
              <GitHubIcon className="h-4 w-4" />
              Get started
            </Link>
            <a
              href={GITHUB_URL}
              target="_blank"
              rel="noreferrer"
              className="inline-flex w-full items-center justify-center gap-2 rounded-full border border-background/25 px-8 py-3.5 font-semibold text-background transition-colors hover:bg-background/10 sm:w-auto"
            >
              <GitHubIcon className="h-4 w-4" />
              View source
            </a>
          </div>
        </div>
      </section>
    </>
  );
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div className="flex flex-col items-center px-4 py-8 text-center">
      <dt className="font-heading text-4xl font-medium tabular-nums">
        {value}
      </dt>
      <dd className="mt-1.5 font-mono text-[0.68rem] uppercase tracking-wide text-muted-foreground">
        {label}
      </dd>
    </div>
  );
}
