import { fapi } from "@/lib/api/server";

/**
 * Bottom-of-page status bar. Pulls live health + cost server-side so the
 * footer always reflects current state without client-side refetches.
 */
export async function AppFooter() {
  const [health, cost] = await Promise.all([
    fapi.health().catch(() => null),
    fapi.globalCost().catch(() => null),
  ]);

  const apiOk = health?.status === "ok";
  const version = health?.version ?? "?";

  return (
    <footer className="border-t border-border/40 mt-auto">
      <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-2 px-4 py-4 text-xs text-muted-foreground sm:flex-row sm:px-6">
        <div className="flex items-center gap-2">
          <span
            className={`inline-block size-2 rounded-full ${
              apiOk ? "bg-emerald-500" : "bg-muted-foreground/40"
            }`}
            aria-hidden
          />
          <span>API {apiOk ? "ok" : "unreachable"}</span>
          <span className="opacity-60">·</span>
          <span>
            v<span className="font-mono">{version}</span>
          </span>
        </div>
        {cost && (
          <div className="flex items-center gap-3 font-mono">
            <span>{cost.total_calls} calls</span>
            <span className="opacity-60">·</span>
            <span>${cost.total_cost_usd.toFixed(4)}</span>
          </div>
        )}
      </div>
    </footer>
  );
}
