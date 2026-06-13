/**
 * "Always add to Project Context" panel — series-level setting on the
 * minute detail page. Toggling a row auto-saves the change via the series
 * context-links endpoint, and the sync job picks up the new state on its
 * next pass (or immediately via POST /api/sync/run).
 */
import { useMemo, useState } from "react";
import { Lightbulb, Loader2 } from "lucide-react";

import { Card } from "@/components/ui/card";
import {
  useSeriesContextLinks,
  useUpdateSeriesContextLinks,
  type SeriesContextLink,
} from "@/hooks/useSeriesContextLinks";
import { cn } from "@/lib/utils";

interface Props {
  seriesId: number;
  seriesTitle: string;
}

export const AlwaysAddPanel = ({ seriesId, seriesTitle }: Props) => {
  const links = useSeriesContextLinks(seriesId);
  const update = useUpdateSeriesContextLinks(seriesId);

  // Track which row is mid-save so we can show a per-row spinner without
  // greying out the others.
  const [savingId, setSavingId] = useState<number | null>(null);

  const enabledCount = useMemo(
    () => (links.data ?? []).filter((l) => l.enabled).length,
    [links.data],
  );

  const toggle = async (link: SeriesContextLink) => {
    setSavingId(link.projectContextId);
    try {
      await update.mutateAsync({
        links: [
          { projectContextId: link.projectContextId, enabled: !link.enabled },
        ],
      });
    } finally {
      setSavingId(null);
    }
  };

  return (
    <Card className="mt-6 p-[22px]">
      <div className="mb-1 flex items-center gap-2">
        <Lightbulb size={14} className="text-primary" />
        <span className="font-mono text-[10.5px] font-semibold uppercase tracking-[0.14em] text-muted-foreground-2">
          Always add to Project Context
        </span>
      </div>
      <p className="mb-4 text-[13px] text-muted-foreground">
        When a new {seriesTitle} occurrence is synced, Noted will auto-file its
        summary as a Google Doc into each enabled Project Context, skipping
        already-filed occurrences.
      </p>

      {links.isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : links.isError ? (
        <p className="text-sm text-destructive">
          Couldn't load Project Contexts: {links.error.message}
        </p>
      ) : (links.data ?? []).length === 0 ? (
        <p className="rounded-md border border-border bg-surface-2 px-3 py-3 text-[13px] text-muted-foreground">
          No Project Contexts registered yet. Create one on the Project Context
          tab and it'll appear here.
        </p>
      ) : (
        <ul className="rounded-md border border-border">
          {(links.data ?? []).map((link) => (
            <li key={link.projectContextId}>
              <ContextToggleRow
                link={link}
                saving={savingId === link.projectContextId}
                onToggle={() => toggle(link)}
              />
            </li>
          ))}
        </ul>
      )}

      {enabledCount > 0 && (
        <p className="mt-3 text-[11.5px] text-muted-foreground">
          {enabledCount} {enabledCount === 1 ? "context" : "contexts"} enabled.
          Meeting summaries will be auto-filed into these on the next sync.
        </p>
      )}
    </Card>
  );
};

const ContextToggleRow = ({
  link,
  saving,
  onToggle,
}: {
  link: SeriesContextLink;
  saving: boolean;
  onToggle: () => void;
}) => (
  <button
    type="button"
    onClick={onToggle}
    disabled={saving}
    className={cn(
      "flex w-full items-center gap-3 border-b border-border px-3 py-2.5 text-left last:border-b-0",
      link.enabled ? "bg-accent-tint" : "hover:bg-surface-2",
      saving && "opacity-60",
    )}
  >
    {/* iOS-style toggle */}
    <span
      className={cn(
        "relative h-[18px] w-[32px] flex-none rounded-full transition-colors",
        link.enabled ? "bg-primary" : "bg-border-strong",
      )}
    >
      <span
        className={cn(
          "absolute top-0.5 h-[14px] w-[14px] rounded-full bg-card transition-transform",
          link.enabled ? "translate-x-[16px]" : "translate-x-[2px]",
        )}
      />
    </span>
    <span className="min-w-0 flex-1 text-[13.5px] font-semibold text-ink">
      {link.label}
    </span>
    {saving && (
      <Loader2 size={13} className="animate-spin text-muted-foreground" />
    )}
  </button>
);
