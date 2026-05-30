"use client";

import * as React from "react";
import Link from "next/link";
import { LogOut, Menu, Settings, Sparkles, User as UserIcon } from "lucide-react";
import type { Me } from "@/lib/api/types";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { Separator } from "@/components/ui/separator";
import { NavLinksVertical } from "@/components/nav-links";

/**
 * Mobile menu — hamburger that slides in a Sheet containing the same nav
 * links as the desktop bar, plus the user menu actions (profile, settings,
 * sign out). One panel = no decisions for the user about where to look.
 */
export function MobileNav({ me }: { me: Me }) {
  const [open, setOpen] = React.useState(false);

  const display = me.name?.trim() || `@${me.github_login}`;

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger
        render={
          <Button variant="ghost" size="icon" aria-label="Open menu" />
        }
      >
        <Menu className="size-5" />
      </SheetTrigger>
      <SheetContent side="right" className="w-72 p-0">
        <SheetHeader className="px-4 pt-5 pb-3 border-b border-border/40">
          <SheetTitle className="flex items-center gap-2 text-base font-semibold">
            <Sparkles className="h-5 w-5 text-primary" />
            OSS Engine
          </SheetTitle>
          <div className="mt-2 text-sm">
            <div className="font-medium truncate">{display}</div>
            <div className="text-xs text-muted-foreground truncate">
              @{me.github_login}
            </div>
          </div>
        </SheetHeader>

        <nav className="px-3 py-4">
          <NavLinksVertical onNavigate={() => setOpen(false)} />
        </nav>

        <Separator />

        <ul className="px-3 py-3 flex flex-col gap-1">
          <li>
            <Link
              href="/profile"
              onClick={() => setOpen(false)}
              className="flex items-center gap-2 rounded-md px-3 py-2 text-sm text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors"
            >
              <UserIcon className="size-4" />
              Profile
            </Link>
          </li>
          <li>
            <Link
              href="/settings"
              onClick={() => setOpen(false)}
              className="flex items-center gap-2 rounded-md px-3 py-2 text-sm text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors"
            >
              <Settings className="size-4" />
              Settings
            </Link>
          </li>
          <li>
            <form action="/api/auth/logout" method="POST">
              <button
                type="submit"
                className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors text-left"
              >
                <LogOut className="size-4" />
                Sign out
              </button>
            </form>
          </li>
        </ul>
      </SheetContent>
    </Sheet>
  );
}
