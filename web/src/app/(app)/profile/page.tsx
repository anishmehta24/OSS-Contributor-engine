import { Brain, Code2, Compass, Layers, Quote } from "lucide-react";
import type { Metadata } from "next";
import { fapi } from "@/lib/api/server";
import { GitHubIcon } from "@/components/icons";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { ReProfileButton } from "@/components/profile/re-profile-button";

export const metadata: Metadata = { title: "Profile" };

const EXPERIENCE_STYLE = {
  junior: "bg-sky-500/15 text-sky-500 border-sky-500/30",
  mid: "bg-primary/15 text-primary border-primary/30",
  senior: "bg-amber-500/15 text-amber-500 border-amber-500/30",
} as const;

function formatProfiled(iso: string): string {
  // Server-safe ISO -> short relative-ish label. We deliberately avoid
  // `Intl.RelativeTimeFormat` here because it'd hydrate-mismatch in a
  // server component if we computed "X minutes ago" — render the absolute
  // date instead.
  try {
    return new Date(iso).toUTCString().replace(" GMT", "");
  } catch {
    return iso;
  }
}

export default async function ProfilePage() {
  const profile = await fapi.profile();
  const me = await fapi.me();

  if (!profile) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-16 sm:px-6">
        <Card className="border-border/60">
          <CardHeader className="space-y-3 text-center">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <Brain className="size-6" />
            </div>
            <CardTitle className="text-2xl">No profile yet</CardTitle>
            <CardDescription className="text-balance text-base">
              We&apos;ll scan your top active GitHub repos to figure out what you
              actually build — languages, frameworks, domains, experience level.
              Takes 30-90 seconds.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex justify-center pb-8">
            <ReProfileButton hasProfile={false} size="lg" />
          </CardContent>
        </Card>
      </div>
    );
  }

  const expClass = profile.experience_signal
    ? EXPERIENCE_STYLE[profile.experience_signal]
    : "";

  return (
    <div className="mx-auto max-w-5xl px-4 py-8 sm:px-6 sm:py-10">
      {/* Header */}
      <header className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-2">
          <p className="flex items-center gap-2 text-xs uppercase tracking-wide text-muted-foreground">
            <Brain className="size-3.5" />
            Skill profile
          </p>
          <h1 className="text-3xl font-semibold tracking-tight">
            {profile.name?.trim() || `@${profile.github_login}`}
          </h1>
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            <a
              href={`https://github.com/${profile.github_login}`}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 hover:text-foreground transition-colors"
            >
              <GitHubIcon className="size-3.5" />@{profile.github_login}
            </a>
            {profile.experience_signal && (
              <>
                <span aria-hidden>·</span>
                <Badge
                  variant="outline"
                  className={`capitalize font-normal ${expClass}`}
                >
                  {profile.experience_signal}
                </Badge>
              </>
            )}
            <span aria-hidden>·</span>
            <span className="font-mono text-xs">
              profiled {formatProfiled(profile.profiled_at)}
            </span>
          </div>
        </div>
        <ReProfileButton hasProfile />
      </header>

      {/* Summary */}
      {profile.summary && (
        <Card className="mb-6 border-border/60 bg-gradient-to-br from-primary/5 via-background to-background">
          <CardContent className="flex gap-4 py-6">
            <Quote
              className="size-5 shrink-0 text-primary/60 mt-0.5"
              aria-hidden
            />
            <p className="text-base leading-relaxed text-foreground/90">
              {profile.summary}
            </p>
          </CardContent>
        </Card>
      )}

      {/* Skills grid */}
      <section aria-labelledby="skills-heading" className="space-y-4">
        <div className="flex items-center justify-between">
          <h2
            id="skills-heading"
            className="text-sm font-semibold uppercase tracking-wide text-muted-foreground"
          >
            Skills
          </h2>
          <span className="text-xs text-muted-foreground font-mono">
            {profile.languages.length} languages · {profile.frameworks.length}{" "}
            frameworks · {profile.domains.length} domains
          </span>
        </div>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <SkillCard
            icon={Code2}
            label="Languages"
            items={profile.languages}
            empty="No languages detected. Try re-profiling after adding code to your repos."
          />
          <SkillCard
            icon={Layers}
            label="Frameworks"
            items={profile.frameworks}
            empty="No frameworks detected from your manifests yet."
          />
          <SkillCard
            icon={Compass}
            label="Domains"
            items={profile.domains}
            empty="The agent didn't infer specific domains — broad generalist."
          />
        </div>
      </section>

      <Separator className="my-10" />

      {/* Footnote */}
      <p className="text-xs text-muted-foreground leading-relaxed">
        Profiles are generated by the <span className="font-medium">Skill Profiler</span> agent —
        it reads up to {Math.max(profile.repos_analyzed, 12)} of your most
        recently pushed repos, extracts languages and frameworks from manifests,
        and asks an LLM to infer domains, experience level, and a prose summary.
        Re-profile after a big push or when you start a new project — the data
        feeds directly into ranked matches and pitch drafts. {me?.github_login && (
          <>Signed in as <code className="rounded bg-muted px-1 py-0.5">@{me.github_login}</code>.</>
        )}
      </p>
    </div>
  );
}

function SkillCard({
  icon: Icon,
  label,
  items,
  empty,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  items: string[];
  empty: string;
}) {
  return (
    <Card className="border-border/60">
      <CardHeader className="space-y-1.5">
        <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-muted-foreground">
          <Icon className="size-3.5" />
          {label}
        </div>
        <CardTitle className="text-base font-medium">
          {items.length > 0 ? `${items.length} found` : "—"}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {items.length > 0 ? (
          <div className="flex flex-wrap gap-1.5">
            {items.map((item) => (
              <Badge
                key={item}
                variant="secondary"
                className="font-normal"
              >
                {item}
              </Badge>
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">{empty}</p>
        )}
      </CardContent>
    </Card>
  );
}
