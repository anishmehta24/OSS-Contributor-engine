import Link from "next/link";
import { Brain } from "lucide-react";
import { fapi } from "@/lib/api/server";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

const TOP_N = 5;

export async function ProfileCard() {
  const profile = await fapi.profile();

  return (
    <Card className="border-border/60">
      <CardHeader className="flex flex-row items-start justify-between space-y-0">
        <div className="space-y-1.5">
          <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-muted-foreground">
            <Brain className="size-3.5" />
            Your profile
          </div>
          <CardTitle className="text-lg">
            {profile ? (
              <span className="capitalize">
                {profile.experience_signal ?? "Developer"}
              </span>
            ) : (
              "Get profiled"
            )}
          </CardTitle>
        </div>
        <Button
          render={<Link href="/profile" />}
          nativeButton={false}
          variant="ghost"
          size="sm"
        >
          {profile ? "Manage" : "Start"} →
        </Button>
      </CardHeader>
      <CardContent>
        {profile ? (
          <div className="space-y-3 text-sm">
            <div>
              <div className="mb-1 text-xs text-muted-foreground">Languages</div>
              {profile.languages.length > 0 ? (
                <div className="flex flex-wrap gap-1.5">
                  {profile.languages.slice(0, TOP_N).map((l) => (
                    <Badge key={l} variant="secondary" className="font-normal">
                      {l}
                    </Badge>
                  ))}
                </div>
              ) : (
                <span className="text-muted-foreground">—</span>
              )}
            </div>
            {profile.frameworks.length > 0 && (
              <div>
                <div className="mb-1 text-xs text-muted-foreground">
                  Frameworks
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {profile.frameworks.slice(0, TOP_N).map((f) => (
                    <Badge key={f} variant="secondary" className="font-normal">
                      {f}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : (
          <CardDescription className="text-sm">
            We&apos;ll scan your top active repos to figure out what you build —
            languages, frameworks, domains, experience level.
          </CardDescription>
        )}
      </CardContent>
    </Card>
  );
}
