import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Renders a markdown string inside a Tailwind-typography `prose` container.
 * GFM enabled (tables, task lists, strikethrough, autolinks).
 */
export function ReportMarkdown({ markdown }: { markdown: string }) {
  return (
    <div className="prose prose-sm dark:prose-invert max-w-none prose-headings:font-semibold prose-pre:bg-muted/50 prose-pre:border prose-pre:border-border/60 prose-code:before:content-none prose-code:after:content-none">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
    </div>
  );
}
