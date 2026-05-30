import { Construction } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

/**
 * Shared scaffold for not-yet-built section pages. The navbar links to all
 * of these, so each needs to render *something* — but we don't want to
 * pretend any of them work.
 */
export function PlaceholderPage({
  title,
  batch,
  description,
}: {
  title: string;
  batch: string;
  description: string;
}) {
  return (
    <div className="mx-auto max-w-3xl px-4 py-16 sm:px-6">
      <Card className="border-border/60">
        <CardHeader className="space-y-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <Construction className="size-5" />
          </div>
          <div className="flex items-center gap-2">
            <CardTitle className="text-2xl">{title}</CardTitle>
            <Badge variant="secondary" className="font-normal">
              {batch}
            </Badge>
          </div>
          <CardDescription className="text-base">{description}</CardDescription>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          This page is part of the Next.js migration roadmap. The Streamlit
          UI on <code className="rounded bg-muted px-1 py-0.5 text-xs">:8501</code>{" "}
          still works in the meantime if you need this flow right now.
        </CardContent>
      </Card>
    </div>
  );
}
