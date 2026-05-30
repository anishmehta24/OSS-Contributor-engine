"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Loader2, RefreshCw, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";

type Props = {
  /** First-time profile vs refresh changes copy + intent (CTA vs maintenance). */
  hasProfile: boolean;
  /** Hint for the visual treatment — first run gets the primary CTA look. */
  size?: "default" | "lg";
  className?: string;
};

/**
 * Kicks off a Skill Profile run on the FastAPI side. The endpoint blocks for
 * 30-90 seconds while the agent fetches the user's top repos and synthesizes
 * a profile. We keep the existing UI visible during the run so the user has
 * context, and refresh the Server Component tree on completion.
 */
export function ReProfileButton({ hasProfile, size = "default", className }: Props) {
  const router = useRouter();
  const [pending, setPending] = React.useState(false);

  async function run() {
    if (pending) return;
    setPending(true);

    const toastId = toast.loading(
      hasProfile ? "Re-profiling…" : "Scanning your GitHub history…",
      { description: "This usually takes 30-90s. Hang tight." },
    );

    try {
      const res = await fetch("/api/users/me/profile", {
        method: "POST",
        cache: "no-store",
      });
      if (!res.ok) {
        const body = await res.text();
        throw new Error(body || `HTTP ${res.status}`);
      }
      toast.success(
        hasProfile ? "Profile refreshed." : "Profile created.",
        { id: toastId },
      );
      // Re-fetch the Server Component tree so the page picks up the new data.
      router.refresh();
    } catch (err) {
      toast.error(hasProfile ? "Re-profile failed." : "Profiling failed.", {
        id: toastId,
        description: err instanceof Error ? err.message.slice(0, 200) : "",
      });
    } finally {
      setPending(false);
    }
  }

  const Icon = hasProfile ? RefreshCw : Sparkles;

  return (
    <Button
      size={size}
      variant={hasProfile ? "outline" : "default"}
      onClick={run}
      disabled={pending}
      className={className}
    >
      {pending ? (
        <Loader2 className="mr-2 size-4 animate-spin" />
      ) : (
        <Icon className="mr-2 size-4" />
      )}
      {pending
        ? hasProfile
          ? "Re-profiling…"
          : "Profiling…"
        : hasProfile
          ? "Re-profile"
          : "Profile me"}
    </Button>
  );
}
