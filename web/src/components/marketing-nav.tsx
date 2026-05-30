import Link from "next/link";
import { Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/theme-toggle";

export function MarketingNav() {
  return (
    <header className="sticky top-0 z-40 border-b border-border/40 bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-6">
        <Link href="/" className="flex items-center gap-2 font-semibold">
          <Sparkles className="h-5 w-5 text-primary" />
          <span>OSS Engine</span>
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
