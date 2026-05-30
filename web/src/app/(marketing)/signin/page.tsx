import Link from "next/link";
import type { Metadata } from "next";
import { Sparkles } from "lucide-react";
import { GitHubIcon } from "@/components/icons";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export const metadata: Metadata = { title: "Sign in" };

export default function SignInPage() {
  return (
    <div className="mx-auto flex min-h-[calc(100vh-7rem)] max-w-md flex-col items-center justify-center px-6 py-12">
      <Card className="w-full border-border/60 shadow-xl shadow-primary/5">
        <CardHeader className="space-y-3 text-center">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <Sparkles className="h-6 w-6" />
          </div>
          <CardTitle className="text-2xl tracking-tight">
            Sign in to OSS Engine
          </CardTitle>
          <CardDescription className="text-balance">
            Authorize once with your GitHub account. We only read your public
            profile and repos.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/*
            Plain <a> (not next/link) — we need a full browser navigation so
            the FastAPI Set-Cookie on the OAuth callback applies. App Router
            navigation would skip that for prefetched links.
          */}
          <Button
            render={<a href="/api/auth/login" />}
            nativeButton={false}
            size="lg"
            className="w-full"
          >
            <GitHubIcon className="mr-2 h-4 w-4" />
            Continue with GitHub
          </Button>
          <p className="text-center text-xs text-muted-foreground">
            By signing in you agree to our{" "}
            <Link href="/" className="underline underline-offset-2">
              terms
            </Link>
            . No marketing emails, ever.
          </p>
        </CardContent>
      </Card>
      <Link
        href="/"
        className="mt-6 text-sm text-muted-foreground hover:text-foreground transition-colors"
      >
        ← back to home
      </Link>
    </div>
  );
}
