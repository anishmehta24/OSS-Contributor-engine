import Link from "next/link";
import { GitPullRequestArrow } from "lucide-react";
import { GitHubIcon } from "@/components/icons";
import { ThemeToggle } from "@/components/theme-toggle";

const GITHUB_URL = "https://github.com/anishmehta24/OSS-Contributor-engine";

export function MarketingNav() {
  return (
    <header className="sticky top-0 z-40 border-b border-border/60 bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-6">
        <Link
          href="/"
          className="flex items-center gap-2.5 font-heading text-[15px] font-semibold tracking-tight"
        >
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-primary text-primary-foreground">
            <GitPullRequestArrow className="h-[18px] w-[18px]" />
          </span>
          OSS Engine
        </Link>
        <nav className="flex items-center gap-1 sm:gap-2">
          <a
            href={GITHUB_URL}
            target="_blank"
            rel="noreferrer"
            title="View source on GitHub"
            className="hidden items-center gap-1.5 rounded-full px-3 py-1.5 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground sm:inline-flex"
          >
            <GitHubIcon className="h-4 w-4" />
            GitHub
          </a>
          <ThemeToggle />
          <Link
            href="/signin"
            className="ml-1 inline-flex items-center gap-1.5 rounded-full bg-primary px-4 py-1.5 text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/90"
          >
            Sign in
          </Link>
        </nav>
      </div>
    </header>
  );
}
