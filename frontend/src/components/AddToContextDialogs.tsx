import { useEffect, useMemo, useRef, useState } from "react";
import {
  CheckCircle2,
  ExternalLink,
  FolderOpen,
  Lightbulb,
  Loader2,
  XCircle,
} from "lucide-react";

import { CopyUrlButton } from "@/components/CopyUrlButton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  useFileIntoContexts,
  useProjectContexts,
  type FiledDoc,
  type FilingResult,
} from "@/hooks/useProjectContexts";
import { cn } from "@/lib/utils";

/**
 * "One item → many Project Contexts" filing dialog. Two thin public
 * wrappers below (`AddMeetingToContextDialog`, `AddTicketToContextDialog`)
 * pre-fill `itemType` so callers don't have to think about the polymorphic
 * shape. The shared impl lives in this file because the diff between the
 * two flavors is small (a few labels + the ref type) and duplicating 200+
 * lines would be worse than one disambiguating prop.
 */
interface InnerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  itemType: "meeting" | "ticket";
  /** Meeting id (number) or Jira issue key (string). */
  itemRef: string | number;
  alreadyFiledByContextId?: Record<number, FiledDoc>;
}

const ITEM_NOUN_TITLE: Record<InnerProps["itemType"], string> = {
  meeting: "meeting's summary",
  ticket: "ticket",
};

const ItemToContextDialog = ({
  open,
  onOpenChange,
  itemType,
  itemRef,
  alreadyFiledByContextId,
}: InnerProps) => {
  const contexts = useProjectContexts();
  const file = useFileIntoContexts();

  const [selected, setSelected] = useState<Set<number>>(new Set());
  // Once the mutation succeeds we flip to a "results view" so the user can
  // grab the Doc links + open-in-Claude helper.
  const [resultsByContext, setResultsByContext] = useState<
    Record<number, FilingResult>
  >({});

  const wasOpen = useRef(open);
  useEffect(() => {
    if (wasOpen.current && !open) {
      setSelected(new Set());
      setResultsByContext({});
      file.reset();
    }
    wasOpen.current = open;
    // file.reset is referentially unstable
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const showingResults = Object.keys(resultsByContext).length > 0;
  const canSubmit = selected.size > 0 && !file.isPending && !showingResults;

  const toggle = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const refStr = String(itemRef);

  const submit = async () => {
    const ids = Array.from(selected);
    const collected: Record<number, FilingResult> = {};
    // We call the endpoint once per Project Context. Server-side it's still
    // batch-capable, but the response is per-context — looping client-side
    // keeps the dialog's per-row results trivial to render.
    for (const ctxId of ids) {
      try {
        const r = await file.mutateAsync({
          projectContextId: ctxId,
          items: [{ type: itemType, ref: refStr }],
        });
        if (r.results[0]) collected[ctxId] = r.results[0];
      } catch (e: unknown) {
        collected[ctxId] = {
          type: itemType,
          ref: refStr,
          status: "failed",
          driveDocId: null,
          driveDocUrl: null,
          error: e instanceof Error ? e.message : "Request failed",
        };
      }
    }
    setResultsByContext(collected);
  };

  const ctxRows = useMemo(() => contexts.data ?? [], [contexts.data]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-[520px]">
        <DialogHeader>
          <DialogTitle>Add to Project Context</DialogTitle>
          <DialogDescription>
            File this {ITEM_NOUN_TITLE[itemType]} as a Google Doc into one or
            more Project Contexts. You'll add the resulting Doc to your
            claude.ai Project as context.
          </DialogDescription>
        </DialogHeader>

        <div className="px-6 pb-2">
          {contexts.isLoading ? (
            <p className="py-6 text-sm text-muted-foreground">Loading…</p>
          ) : ctxRows.length === 0 ? (
            <EmptyContexts />
          ) : showingResults ? (
            <>
              <ResultsBanner />
              <ResultsList rows={ctxRows} resultsByContext={resultsByContext} />
            </>
          ) : (
            <ContextChecklist
              rows={ctxRows}
              selected={selected}
              onToggle={toggle}
              alreadyFiledByContextId={alreadyFiledByContextId ?? {}}
            />
          )}
        </div>

        <DialogFooter>
          {showingResults ? (
            <>
              <a
                href="https://claude.ai/projects"
                target="_blank"
                rel="noopener noreferrer"
                className="mr-auto text-[12px] font-semibold text-muted-foreground hover:text-primary"
              >
                Open claude.ai Projects ↗
              </a>
              <Button onClick={() => onOpenChange(false)}>Done</Button>
            </>
          ) : (
            <>
              <Button variant="outline" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button onClick={submit} disabled={!canSubmit}>
                {file.isPending ? (
                  <>
                    <Loader2 size={14} className="animate-spin" />
                    Filing…
                  </>
                ) : (
                  `Add to ${selected.size || ""}${selected.size ? " " : ""}Project Context${selected.size === 1 ? "" : "s"}`
                )}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

// --- subcomponents -----------------------------------------------------------

const ResultsBanner = () => (
  <div className="mb-3 rounded-md border border-border bg-surface-2 px-3 py-2.5 text-[12px] text-ink-2">
    <div className="font-semibold text-ink">
      Next: admit each Doc in claude.ai
    </div>
    <div className="mt-0.5 text-muted-foreground">
      Either re-connect your Drive integration in claude.ai to re-index, or
      paste each Doc URL below into your Project's <em>+ Add files → Drive</em>{" "}
      picker.
    </div>
  </div>
);

const EmptyContexts = () => (
  <div className="flex flex-col items-center justify-center px-4 py-8 text-center">
    <div className="mb-3 grid h-10 w-10 place-items-center rounded-[10px] bg-accent-tint text-primary">
      <Lightbulb size={18} />
    </div>
    <p className="text-sm font-semibold text-ink">No Project Contexts yet</p>
    <p className="mt-1 text-[12.5px] text-muted-foreground">
      Create one on the Project Context tab first.
    </p>
  </div>
);

const ContextChecklist = ({
  rows,
  selected,
  onToggle,
  alreadyFiledByContextId,
}: {
  rows: Array<{
    id: number;
    label: string;
    docCount: number;
    driveFolderUrl: string | null;
  }>;
  selected: Set<number>;
  onToggle: (id: number) => void;
  alreadyFiledByContextId: Record<number, FiledDoc>;
}) => (
  <ul className="max-h-[280px] overflow-auto rounded-md border border-border">
    {rows.map((row) => {
      const filed = alreadyFiledByContextId[row.id];
      const isSelected = selected.has(row.id);
      return (
        <li key={row.id}>
          <button
            type="button"
            onClick={() => onToggle(row.id)}
            className={cn(
              "flex w-full items-center gap-3 border-b border-border px-3 py-2.5 text-left last:border-b-0",
              isSelected ? "bg-accent-tint" : "hover:bg-surface-2",
            )}
          >
            <span
              className={cn(
                "grid h-4 w-4 flex-none place-items-center rounded border",
                isSelected
                  ? "border-primary bg-primary"
                  : "border-border-strong bg-card",
              )}
            >
              {isSelected && (
                <svg
                  viewBox="0 0 12 12"
                  className="h-3 w-3 text-primary-foreground"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                >
                  <path d="M2 6.5l2.5 2.5L10 3.5" />
                </svg>
              )}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[13.5px] font-semibold text-ink">
                {row.label}
              </span>
              <span className="text-[11.5px] text-muted-foreground">
                {row.docCount} {row.docCount === 1 ? "Doc filed" : "Docs filed"}
              </span>
            </span>
            {filed && filed.status === "success" && (
              <Badge variant="muted">Filed</Badge>
            )}
          </button>
        </li>
      );
    })}
  </ul>
);

const ResultsList = ({
  rows,
  resultsByContext,
}: {
  rows: Array<{
    id: number;
    label: string;
    driveFolderUrl: string | null;
  }>;
  resultsByContext: Record<number, FilingResult>;
}) => (
  <ul className="rounded-md border border-border">
    {rows
      .filter((row) => resultsByContext[row.id] !== undefined)
      .map((row) => {
        const result = resultsByContext[row.id];
        const ok = result.status === "success" || result.status === "skipped";
        return (
          <li
            key={row.id}
            className="flex items-start gap-3 border-b border-border px-3 py-3 last:border-b-0"
          >
            <span className="mt-0.5 flex-none">
              {ok ? (
                <CheckCircle2 size={16} className="text-[hsl(141_63%_33%)]" />
              ) : (
                <XCircle size={16} className="text-destructive" />
              )}
            </span>
            <div className="min-w-0 flex-1">
              <div className="text-[13.5px] font-semibold text-ink">
                {row.label}
              </div>
              <div className="mt-0.5 text-[12px] text-muted-foreground">
                {result.status === "success" && "Filed as a new Google Doc."}
                {result.status === "skipped" &&
                  "Already filed — Doc reused, no duplicate."}
                {result.status === "failed" && (result.error ?? "Failed.")}
              </div>
              {ok && result.driveDocUrl && (
                <div className="mt-1.5 flex flex-wrap items-center gap-2">
                  <CopyUrlButton
                    url={result.driveDocUrl}
                    label="Copy Doc URL"
                  />
                  <a
                    href={result.driveDocUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-[12px] font-semibold text-primary hover:underline"
                  >
                    Open Doc
                    <ExternalLink size={11} />
                  </a>
                  {row.driveFolderUrl && (
                    <a
                      href={row.driveFolderUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-[12px] font-semibold text-muted-foreground hover:text-primary"
                    >
                      <FolderOpen size={11} />
                      Folder
                    </a>
                  )}
                </div>
              )}
            </div>
          </li>
        );
      })}
  </ul>
);

// --- Public wrappers — one per item kind for explicit call sites -----------

interface MeetingProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  meetingId: number;
  alreadyFiledByContextId?: Record<number, FiledDoc>;
}

export const AddMeetingToContextDialog = ({
  meetingId,
  ...rest
}: MeetingProps) => (
  <ItemToContextDialog {...rest} itemType="meeting" itemRef={meetingId} />
);

interface TicketProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  ticketKey: string;
  alreadyFiledByContextId?: Record<number, FiledDoc>;
}

export const AddTicketToContextDialog = ({
  ticketKey,
  ...rest
}: TicketProps) => (
  <ItemToContextDialog {...rest} itemType="ticket" itemRef={ticketKey} />
);
