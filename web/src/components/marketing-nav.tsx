import Link from "next/link";
import { GitPullRequestArrow } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/theme-toggle";

export function MarketingNav() {
  return (
    <header className="sticky top-0 z-40 border-b border-border/40 bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60">
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
        <nav className="flex items-center gap-2">
          <ThemeToggle />
          <Button render={<Link href="/signin" />} nativeButton={false} size="sm">
            Sign in
          </Button>
        </nav>
      </div>
    </header>
  );
}
