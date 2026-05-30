import { Coins } from "lucide-react";
import { fapi } from "@/lib/api/server";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export async function CostCard() {
  const cost = await fapi.globalCost().catch(() => null);

  // Defensive defaults — cost endpoint sometimes returns null/undefined fields
  // when the user has no agent_runs yet.
  const calls = cost?.total_calls ?? 0;
  const tokensIn = cost?.total_tokens_in ?? 0;
  const tokensOut = cost?.total_tokens_out ?? 0;
  const usd = cost?.total_cost_usd ?? 0;

  return (
    <Card className="border-border/60">
      <CardHeader className="space-y-1.5">
        <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-muted-foreground">
          <Coins className="size-3.5" />
          Spend so far
        </div>
        <CardTitle className="font-mono text-2xl tabular-nums">
          ${usd.toFixed(4)}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-3 gap-3 text-xs">
          <Stat label="LLM calls" value={calls.toLocaleString()} />
          <Stat label="Tokens in" value={tokensIn.toLocaleString()} />
          <Stat label="Tokens out" value={tokensOut.toLocaleString()} />
        </dl>
      </CardContent>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 font-mono tabular-nums text-foreground">{value}</dd>
    </div>
  );
}
