import { useEffect, useState } from "react";
import { Check, Copy } from "lucide-react";

import { cn } from "@/lib/utils";

interface Props {
  url: string;
  label?: string;
  className?: string;
}

/**
 * Inline "Copy URL" button with a brief "Copied!" confirmation state.
 * The Doc URLs we file into Drive aren't visible in claude.ai's Drive
 * search; the user adds them by pasting the URL into the Project's Drive
 * picker. This button is how we make that paste fast.
 */
export const CopyUrlButton = ({
  url,
  label = "Copy URL",
  className,
}: Props) => {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const handle = setTimeout(() => setCopied(false), 1600);
    return () => clearTimeout(handle);
  }, [copied]);

  const onClick = async () => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
    } catch {
      // Fallback: select the text in a temporary input. Rare path on
      // permission-denied or insecure-context browsers.
      const ta = document.createElement("textarea");
      ta.value = url;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
        setCopied(true);
      } finally {
        document.body.removeChild(ta);
      }
    }
  };

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1 rounded-md border border-border-strong bg-card px-2.5 py-1.5 text-[12px] font-semibold text-ink-2 transition-colors hover:bg-surface-2",
        copied && "border-[hsl(141_63%_33%)] text-[hsl(141_63%_33%)]",
        className,
      )}
      title="Copy the Doc URL so you can paste it into claude.ai's Drive picker"
    >
      {copied ? (
        <>
          <Check size={12} />
          Copied
        </>
      ) : (
        <>
          <Copy size={12} />
          {label}
        </>
      )}
    </button>
  );
};
