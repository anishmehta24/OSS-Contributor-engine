import type { Metadata } from "next";
import { LogOut, Settings as SettingsIcon } from "lucide-react";
import { fapi } from "@/lib/api/server";
import { GitHubIcon } from "@/components/icons";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { DeleteAccountButton } from "@/components/settings/delete-account-button";

export const metadata: Metadata = { title: "Settings" };

export default async function SettingsPage() {
  const me = await fapi.me();
  // Layout already redirects if me is null, but TypeScript doesn't know that.
  if (!me) return null;

  return (
    <div className="mx-auto max-w-3xl px-4 py-8 sm:px-6 sm:py-10">
      <header className="mb-8">
        <p className="flex items-center gap-2 text-xs uppercase tracking-wide text-muted-foreground">
          <SettingsIcon className="size-3.5" />
          Settings
        </p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight">Account</h1>
      </header>

      <div className="space-y-6">
        {/* Account info */}
        <Card className="border-border/60">
          <CardHeader>
            <CardTitle className="text-base">Signed in</CardTitle>
            <CardDescription>Identity is sourced from GitHub OAuth.</CardDescription>
          </CardHeader>
          <CardContent>
            <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
              <Row label="Name" value={me.name?.trim() || "—"} />
              <Row label="GitHub login" value={`@${me.github_login}`} mono>
                <a
                  href={`https://github.com/${me.github_login}`}
                  target="_blank"
                  rel="noreferrer"
                  className="ml-2 inline-flex text-muted-foreground hover:text-foreground"
                  aria-label="Open GitHub profile"
                >
                  <GitHubIcon className="size-3.5" />
                </a>
              </Row>
              <Row label="GitHub user id" value={String(me.github_id)} mono />
              <Row
                label="OAuth token"
                value={me.has_oauth_token ? "stored (encrypted)" : "missing"}
              />
            </dl>
          </CardContent>
        </Card>

        {/* Sessions */}
        <Card className="border-border/60">
          <CardHeader>
            <CardTitle className="text-base">Session</CardTitle>
            <CardDescription>
              Sign out clears the session cookie on this device. It does not
              revoke the GitHub OAuth grant — do that from{" "}
              <a
                href="https://github.com/settings/applications"
                target="_blank"
                rel="noreferrer"
                className="underline underline-offset-2"
              >
                GitHub → Authorized OAuth Apps
              </a>
              .
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form action="/api/auth/logout" method="POST">
              <Button type="submit" variant="outline" size="sm">
                <LogOut className="mr-2 size-3.5" />
                Sign out
              </Button>
            </form>
          </CardContent>
        </Card>

        <Separator />

        {/* Danger zone */}
        <Card className="border-rose-500/30">
          <CardHeader>
            <CardTitle className="text-base text-rose-500">
              Danger zone
            </CardTitle>
            <CardDescription>
              Permanent and irreversible. Removes your profile, investigations,
              pitches, agent run telemetry, and stored OAuth token.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <DeleteAccountButton login={me.github_login} />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function Row({
  label,
  value,
  mono = false,
  children,
}: {
  label: string;
  value: string;
  mono?: boolean;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd
        className={`text-sm flex items-center ${mono ? "font-mono" : ""}`}
      >
        {value}
        {children}
      </dd>
    </div>
  );
}
