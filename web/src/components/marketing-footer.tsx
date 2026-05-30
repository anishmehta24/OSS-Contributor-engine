import Link from "next/link";

export function MarketingFooter() {
  return (
    <footer className="border-t border-border/40">
      <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-3 px-6 py-6 text-sm text-muted-foreground sm:flex-row">
        <div>
          OSS Contributor Engine &middot; multi-agent issue finder
        </div>
        <div className="flex items-center gap-4">
          <Link
            href="https://github.com"
            target="_blank"
            rel="noreferrer"
            className="hover:text-foreground transition-colors"
          >
            GitHub
          </Link>
          <Link href="/signin" className="hover:text-foreground transition-colors">
            Sign in
          </Link>
        </div>
      </div>
    </footer>
  );
}
