import Link from "next/link";
import { Compass } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <div className="flex min-h-screen items-center justify-center px-6 py-16">
      <div className="max-w-md text-center space-y-5">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10 text-primary">
          <Compass className="size-6" />
        </div>
        <h1 className="text-3xl font-semibold tracking-tight">
          Lost the trail
        </h1>
        <p className="text-muted-foreground">
          We couldn&apos;t find that page. Maybe the URL drifted, or maybe the
          investigation belonged to a different user.
        </p>
        <div className="flex flex-wrap justify-center gap-2 pt-2">
          <Button render={<Link href="/" />} nativeButton={false}>
            Home
          </Button>
          <Button
            render={<Link href="/dashboard" />}
            nativeButton={false}
            variant="ghost"
          >
            Dashboard
          </Button>
        </div>
      </div>
    </div>
  );
}
