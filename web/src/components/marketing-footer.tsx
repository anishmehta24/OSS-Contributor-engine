import Link from "next/link";
import { GitPullRequestArrow } from "lucide-react";
import { GitHubIcon } from "@/components/icons";

const GITHUB_URL = "https://github.com/anishmehta24/OSS-Contributor-engine";

export function MarketingFooter() {
  return (
    <footer className="border-t border-border">
      <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-4 px-6 py-8 text-sm text-muted-foreground sm:flex-row">
        <div className="flex items-center gap-2 font-heading font-semibold tracking-tight text-foreground">
          <span className="grid h-6 w-6 place-items-center rounded-md bg-primary text-primary-foreground">
            <GitPullRequestArrow className="h-3.5 w-3.5" />
          </span>
          OSS Engine
        </div>
        <div className="flex items-center gap-5">
          <a
            href={GITHUB_URL}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1.5 transition-colors hover:text-foreground"
          >
            <GitHubIcon className="h-4 w-4" />
            Open source on GitHub
          </a>
          <Link href="/signin" className="transition-colors hover:text-foreground">
            Sign in
          </Link>
        </div>
      </div>
    </footer>
  );
}
