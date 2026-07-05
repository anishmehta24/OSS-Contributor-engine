import Link from "next/link";
import { Brain } from "lucide-react";
import { fapi } from "@/lib/api/server";

const TOP_N = 6;

export async function ProfileCard() {
  const profile = await fapi.profile();

  return (
    <section className="flex h-full flex-col rounded-xl border border-border bg-card p-6">
      <div className="flex items-center justify-between">
        <p className="flex items-center gap-2 font-mono text-[0.65rem] uppercase tracking-[0.15em] text-muted-foreground">
          <Brain className="size-3.5" />
          Your profile
        </p>
        <Link
          href="/profile"
          className="text-xs font-medium text-muted-foreground transition-colors hover:text-primary"
        >
          {profile ? "Manage" : "Start"} →
        </Link>
      </div>

      <h2 className="mt-3 text-2xl font-medium capitalize">
        {profile ? (profile.experience_signal ?? "Developer") : "Get profiled"}
      </h2>

      {profile ? (
        <div className="mt-5 space-y-4">
          <ChipRow label="Languages" items={profile.languages} />
          {profile.frameworks.length > 0 && (
            <ChipRow label="Frameworks" items={profile.frameworks} />
          )}
        </div>
      ) : (
        <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
          We&apos;ll scan your top active repos to figure out what you build —
          languages, frameworks, domains, and experience level.
        </p>
      )}
    </section>
  );
}

function ChipRow({ label, items }: { label: string; items: string[] }) {
  return (
    <div>
      <p className="mb-2 font-mono text-[0.6rem] uppercase tracking-[0.12em] text-muted-foreground">
        {label}
      </p>
      {items.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {items.slice(0, TOP_N).map((i) => (
            <span
              key={i}
              className="rounded-md border border-border bg-secondary px-2 py-0.5 text-xs font-medium text-secondary-foreground"
            >
              {i}
            </span>
          ))}
        </div>
      ) : (
        <span className="text-sm text-muted-foreground">—</span>
      )}
    </div>
  );
}
