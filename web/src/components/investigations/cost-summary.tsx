import { fapi } from "@/lib/api/server";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export async function InvestigationCostCard({ id }: { id: string }) {
  const cost = await fapi.investigationCost(id).catch(() => null);
  if (!cost) {
    return null;
  }

  return (
    <Card className="border-border/60">
      <CardHeader>
        <CardTitle className="text-base">Cost breakdown</CardTitle>
        <CardDescription>
          Token + latency rollup across every agent + LLM call in this run.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Metric label="LLM calls" value={cost.total_calls.toLocaleString()} />
          <Metric
            label="Tokens in"
            value={cost.total_tokens_in.toLocaleString()}
          />
          <Metric
            label="Tokens out"
            value={cost.total_tokens_out.toLocaleString()}
          />
          <Metric
            label="Cost (USD)"
            value={`$${cost.total_cost_usd.toFixed(4)}`}
            primary
          />
        </dl>

        {cost.per_agent.length > 0 && (
          <div className="overflow-x-auto rounded-md border border-border/60">
            <table className="w-full text-xs">
              <thead className="bg-muted/30">
                <tr className="text-left text-muted-foreground">
                  <th className="px-3 py-1.5 font-medium">Agent</th>
                  <th className="px-3 py-1.5 text-right font-medium">Calls</th>
                  <th className="px-3 py-1.5 text-right font-medium">In</th>
                  <th className="px-3 py-1.5 text-right font-medium">Out</th>
                  <th className="px-3 py-1.5 text-right font-medium">USD</th>
                  <th className="px-3 py-1.5 text-right font-medium">ms</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60 font-mono tabular-nums">
                {cost.per_agent.map((a) => (
                  <tr key={a.agent_name}>
                    <td className="px-3 py-1.5 font-sans">{a.agent_name}</td>
                    <td className="px-3 py-1.5 text-right">{a.calls}</td>
                    <td className="px-3 py-1.5 text-right">
                      {a.tokens_in.toLocaleString()}
                    </td>
                    <td className="px-3 py-1.5 text-right">
                      {a.tokens_out.toLocaleString()}
                    </td>
                    <td className="px-3 py-1.5 text-right">
                      ${a.cost_usd.toFixed(4)}
                    </td>
                    <td className="px-3 py-1.5 text-right text-muted-foreground">
                      {a.latency_ms.toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Metric({
  label,
  value,
  primary = false,
}: {
  label: string;
  value: string;
  primary?: boolean;
}) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd
        className={`mt-0.5 font-mono tabular-nums ${
          primary ? "text-lg font-semibold text-primary" : "text-foreground"
        }`}
      >
        {value}
      </dd>
    </div>
  );
}
