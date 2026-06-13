import { useMemo } from "react";
import DOMPurify from "dompurify";

import { cn } from "@/lib/utils";

interface Props {
  html: string;
  className?: string;
}

/**
 * Render trusted-source HTML (currently only Atlassian's rendered Jira
 * fields) after running it through DOMPurify. We apply Tailwind's `prose`
 * (typography plugin) to style the headings/lists/links/code consistently
 * with the rest of the app.
 *
 * DOMPurify removes dangerous tags/attributes (script, on* event handlers,
 * javascript: hrefs). We open the allowlist only for the things Jira
 * actually emits (basic block + inline tags, lists, code, tables, images).
 */
export const RichHtml = ({ html, className }: Props) => {
  const safe = useMemo(
    () =>
      DOMPurify.sanitize(html, {
        ALLOWED_TAGS: [
          "a",
          "b",
          "blockquote",
          "br",
          "code",
          "div",
          "em",
          "h1",
          "h2",
          "h3",
          "h4",
          "h5",
          "h6",
          "hr",
          "i",
          "img",
          "li",
          "ol",
          "p",
          "pre",
          "s",
          "span",
          "strong",
          "sub",
          "sup",
          "table",
          "tbody",
          "td",
          "tfoot",
          "th",
          "thead",
          "tr",
          "u",
          "ul",
        ],
        ALLOWED_ATTR: [
          "href",
          "rel",
          "src",
          "alt",
          "title",
          "class",
          "colspan",
          "rowspan",
          "target",
        ],
        ALLOWED_URI_REGEXP:
          /^(?:(?:https?|mailto):|[^a-z]|[a-z+.-]+(?:[^a-z+.\-:]|$))/i,
      }),
    [html],
  );

  return (
    <div
      className={cn(
        "prose prose-sm max-w-none prose-headings:text-ink prose-headings:font-semibold prose-headings:tracking-tight prose-p:text-ink-2 prose-p:leading-[1.65] prose-a:text-primary prose-a:no-underline hover:prose-a:underline prose-strong:text-ink prose-code:text-ink prose-code:bg-surface-2 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-code:before:content-none prose-code:after:content-none prose-pre:bg-surface-2 prose-pre:text-ink-2 prose-li:text-ink-2 prose-img:rounded-md",
        className,
      )}
      dangerouslySetInnerHTML={{ __html: safe }}
    />
  );
};
