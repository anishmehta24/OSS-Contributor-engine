import Link from "next/link";
import { Sparkles } from "lucide-react";
import type { Me } from "@/lib/api/types";
import { NavLinks } from "@/components/nav-links";
import { ThemeToggle } from "@/components/theme-toggle";
import { UserMenu } from "@/components/user-menu";
import { MobileNav } from "@/components/mobile-nav";

/**
 * Top navigation for authenticated pages.
 *
 * Server component — the user data is fetched in the parent layout and
 * passed in. The interactive bits (active link, dropdown, sheet) live in
 * client child components.
 */
export function AppNav({ me }: { me: Me }) {
  return (
    <header className="sticky top-0 z-40 border-b border-border/40 bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="mx-auto flex h-14 max-w-7xl items-center justify-between gap-4 px-4 sm:px-6">
        {/* Brand */}
        <div className="flex items-center gap-6">
          <Link href="/dashboard" className="flex items-center gap-2 font-semibold">
            <Sparkles className="h-5 w-5 text-primary" />
            <span>OSS Engine</span>
          </Link>
          {/* Desktop nav */}
          <NavLinks className="hidden md:flex" />
        </div>

        {/* Right side */}
        <div className="flex items-center gap-1">
          <ThemeToggle />
          <div className="hidden md:block">
            <UserMenu me={me} />
          </div>
          <div className="md:hidden">
            <MobileNav me={me} />
          </div>
        </div>
      </div>
    </header>
  );
}
