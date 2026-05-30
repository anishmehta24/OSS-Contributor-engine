"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { Button } from "@/components/ui/button";

/**
 * Light/dark cycle button.
 *
 * Icons are swapped via Tailwind's `dark:` variant rather than React state,
 * because next-themes injects the `class="dark"` on <html> via an inline
 * script before hydration. That means CSS already knows the theme and no
 * useEffect-mounted dance is needed (which trips React 19's new
 * `react-hooks/set-state-in-effect` rule).
 */
export function ThemeToggle() {
  const { theme, setTheme, resolvedTheme } = useTheme();

  // Compute the *click target* lazily — avoid baking it into the rendered
  // HTML so SSR (which doesn't know the user's theme) matches client hydration.
  // The aria-label stays theme-agnostic; the visible icon already conveys
  // direction via the `dark:` CSS variant.
  function toggle() {
    const current = theme === "system" ? resolvedTheme : theme;
    setTheme(current === "dark" ? "light" : "dark");
  }

  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label="Toggle theme"
      onClick={toggle}
    >
      <Sun className="h-[1.2rem] w-[1.2rem] hidden dark:block" />
      <Moon className="h-[1.2rem] w-[1.2rem] block dark:hidden" />
    </Button>
  );
}
