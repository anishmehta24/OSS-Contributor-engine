"use client";

import * as React from "react";
import { AlertTriangle, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";

/**
 * Root error boundary. Catches any uncaught error thrown during render,
 * data fetching, or event handlers in client components beneath it.
 *
 * Must be a Client Component per Next.js convention — the reset callback
 * is interactive and the digest is only available client-side.
 */
export default function RootError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  React.useEffect(() => {
    // Surface to the browser console for dev; production should pipe through
    // a real error sink (Sentry etc.) once one exists.
    console.error(error);
  }, [error]);

  return (
    <div className="flex min-h-screen items-center justify-center px-6 py-16">
      <div className="max-w-lg space-y-5 text-center">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-rose-500/15 text-rose-500">
          <AlertTriangle className="size-6" />
        </div>
        <h1 className="text-3xl font-semibold tracking-tight">
          Something broke
        </h1>
        <p className="text-muted-foreground">
          The page hit an unexpected error. Try again, or head back to the
          dashboard.
        </p>
        {error.message && (
          <pre className="mx-auto max-w-md overflow-auto rounded-md bg-muted px-3 py-2 text-left text-xs font-mono whitespace-pre-wrap">
            {error.message.slice(0, 500)}
          </pre>
        )}
        {error.digest && (
          <p className="text-xs text-muted-foreground font-mono">
            digest: {error.digest}
          </p>
        )}
        <div className="flex justify-center gap-2 pt-2">
          <Button onClick={reset}>
            <RotateCcw className="mr-2 size-4" />
            Try again
          </Button>
        </div>
      </div>
    </div>
  );
}
