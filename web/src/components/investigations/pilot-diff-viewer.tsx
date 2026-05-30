import { cn } from "@/lib/utils";

/**
 * Inline diff viewer — no external library, just Tailwind classes on
 * each line driven by its first character. Handles standard `git diff`
 * output: `diff --git`, `--- a/`, `+++ b/`, `@@ … @@` hunk headers,
 * `+` adds, `-` removes, ` ` context, `\` no-newline notes.
 *
 * Big diffs get a vertical scroll cap so the page stays usable.
 */
const ROW_CLASSES: Record<string, string> = {
  "+": "bg-emerald-500/10 text-emerald-300",
  "-": "bg-rose-500/10 text-rose-300",
  "@": "bg-primary/10 text-primary/80 font-semibold",
  "diff": "text-muted-foreground font-semibold",
  "---": "text-muted-foreground/80",
  "+++": "text-muted-foreground/80",
  "index": "text-muted-foreground/60",
};

function classFor(line: string): string {
  if (line.startsWith("diff --git")) return ROW_CLASSES.diff;
  if (line.startsWith("---")) return ROW_CLASSES["---"];
  if (line.startsWith("+++")) return ROW_CLASSES["+++"];
  if (line.startsWith("index ")) return ROW_CLASSES.index;
  if (line.startsWith("@@")) return ROW_CLASSES["@"];
  if (line.startsWith("+")) return ROW_CLASSES["+"];
  if (line.startsWith("-")) return ROW_CLASSES["-"];
  return "text-foreground/80";
}

export function PilotDiffViewer({
  diff,
  className,
}: {
  diff: string;
  className?: string;
}) {
  const lines = diff.split("\n");
  // Count adds/removes for the header.
  let adds = 0;
  let dels = 0;
  for (const l of lines) {
    if (l.startsWith("+") && !l.startsWith("+++")) adds++;
    else if (l.startsWith("-") && !l.startsWith("---")) dels++;
  }

  return (
    <div
      className={cn(
        "rounded-md border border-border/60 bg-background/50",
        className,
      )}
    >
      <div className="flex items-center justify-between border-b border-border/60 px-3 py-2 text-xs text-muted-foreground font-mono">
        <span>unified diff</span>
        <span>
          <span className="text-emerald-500">+{adds}</span>{" "}
          <span className="text-rose-500">-{dels}</span>
        </span>
      </div>
      <pre className="max-h-[32rem] overflow-auto text-[12px] leading-snug font-mono">
        {lines.map((line, i) => (
          <div
            key={i}
            className={cn("px-3 whitespace-pre", classFor(line))}
          >
            {line || " "}
          </div>
        ))}
      </pre>
    </div>
  );
}
