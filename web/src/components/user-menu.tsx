"use client";

import Link from "next/link";
import { LogOut, Settings, User as UserIcon } from "lucide-react";
import type { Me } from "@/lib/api/types";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

function initials(me: Me): string {
  const source = me.name?.trim() || me.github_login;
  const parts = source.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return source.slice(0, 2).toUpperCase();
}

export function UserMenu({ me }: { me: Me }) {
  const display = me.name?.trim() || `@${me.github_login}`;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            variant="ghost"
            size="icon"
            aria-label="Open user menu"
            className="rounded-full"
          />
        }
      >
        <Avatar className="size-8">
          <AvatarFallback className="bg-primary/15 text-primary text-xs font-semibold">
            {initials(me)}
          </AvatarFallback>
        </Avatar>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        {/*
          base-ui requires GroupLabel to be inside a Group context (Radix
          was permissive about this; base-ui isn't). Each logical section
          becomes its own Group.
        */}
        <DropdownMenuGroup>
          <DropdownMenuLabel className="font-normal">
            <div className="flex flex-col">
              <span className="text-sm font-medium truncate">{display}</span>
              <span className="text-xs text-muted-foreground truncate">
                @{me.github_login}
              </span>
            </div>
          </DropdownMenuLabel>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuGroup>
          <DropdownMenuItem
            render={
              <Link href="/profile">
                <UserIcon className="mr-2 size-4" />
                Profile
              </Link>
            }
          />
          <DropdownMenuItem
            render={
              <Link href="/settings">
                <Settings className="mr-2 size-4" />
                Settings
              </Link>
            }
          />
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        {/*
          Plain form POST — full navigation so the cookie-clearing Set-Cookie
          response is actually committed. Survives JS being disabled too.
        */}
        <DropdownMenuGroup>
          <form action="/api/auth/logout" method="POST">
            {/*
              `nativeButton` tells base-ui the render target IS a real
              <button>, so it skips the non-native button ARIA shims that
              would otherwise duplicate attributes on the element.
            */}
            <DropdownMenuItem
              nativeButton
              render={
                <button type="submit" className="w-full text-left">
                  <LogOut className="mr-2 size-4" />
                  Sign out
                </button>
              }
            />
          </form>
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
