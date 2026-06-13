/**
 * Counterpart to AddToProjectContextDialog: this one is "multiple items
 * into ONE context" (the picker from the Project Context detail page),
 * whereas AddToProjectContextDialog is "one item into MULTIPLE contexts"
 * (the button on the minute / ticket detail). Both call the same backend.
 *
 * Items can be a mix of meetings + tickets — the dialog has a tab
 * switcher and a single submit that bundles both kinds.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import {
  CheckCircle2,
  ExternalLink,
  Loader2,
  Search,
  Ticket as TicketIcon,
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
import { useMe } from "@/hooks/useMe";
import { useMeetings, type MeetingListItem } from "@/hooks/useMeetings";
import {
  useFileIntoContexts,
  useFiledDocs,
  type FileItem,
  type FilingResult,
} from "@/hooks/useProjectContexts";
import { useTickets, type TicketListItem } from "@/hooks/useTickets";
import { formatLocalDateShort, formatLocalTime } from "@/lib/format";
import { cn } from "@/lib/utils";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectContextId: number;
  projectContextLabel: string;
}

type Tab = "minutes" | "tickets";

const itemKey = (type: "meeting" | "ticket", ref: string) => `${type}:${ref}`;

export const AddItemsToContextDialog = ({
  open,
  onOpenChange,
  projectContextId,
  projectContextLabel,
}: Props) => {
  const me = useMe();
  const meetings = useMeetings();
  const tickets = useTickets();
  const filedDocs = useFiledDocs(projectContextId);
  const file = useFileIntoContexts();

  const [tab, setTab] = useState<Tab>("minutes");
  const [query, setQuery] = useState("");
  const [selectedMeetings, setSelectedMeetings] = useState<Set<number>>(
    new Set(),
  );
  const [selectedTickets, setSelectedTickets] = useState<Set<string>>(
    new Set(),
  );
  const [resultsByItem, setResultsByItem] = useState<
    Record<string, FilingResult>
  >({});

  const wasOpen = useRef(open);
  useEffect(() => {
    if (wasOpen.current && !open) {
      setSelectedMeetings(new Set());
      setSelectedTickets(new Set());
      setQuery("");
      setResultsByItem({});
      setTab("minutes");
      file.reset();
    }
    wasOpen.current = open;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // "Filed" maps per kind — used both to disable already-filed rows and
  // to short-circuit the toggle handler defensively.
  const filedByMeetingId = useMemo(() => {
    const set = new Set<string>();
    for (const d of filedDocs.data ?? []) {
      if (d.itemType === "meeting" && d.status === "success")
        set.add(d.itemRef);
    }
    return set;
  }, [filedDocs.data]);

  const filedByTicketKey = useMemo(() => {
    const set = new Set<string>();
    for (const d of filedDocs.data ?? []) {
      if (d.itemType === "ticket" && d.status === "success")
        set.add(d.itemRef);
    }
    return set;
  }, [filedDocs.data]);

  // Filter by query — search the active tab
  const filteredMeetings = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!meetings.data) return [];
    if (!q) return meetings.data;
    return meetings.data.filter(
      (m) =>
        m.title.toLowerCase().includes(q) ||
        m.seriesTitle.toLowerCase().includes(q),
    );
  }, [meetings.data, query]);

  const filteredTickets = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!tickets.data) return [];
    if (!q) return tickets.data.tickets;
    return tickets.data.tickets.filter(
      (t) =>
        t.key.toLowerCase().includes(q) ||
        t.summary.toLowerCase().includes(q) ||
        t.project.name.toLowerCase().includes(q),
    );
  }, [tickets.data, query]);

  const toggleMeeting = (id: number) => {
    if (filedByMeetingId.has(String(id))) return;
    setSelectedMeetings((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleTicket = (key: string) => {
    if (filedByTicketKey.has(key)) return;
    setSelectedTickets((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const totalSelected = selectedMeetings.size + selectedTickets.size;
  const showingResults = Object.keys(resultsByItem).length > 0;
  const canSubmit = totalSelected > 0 && !file.isPending && !showingResults;

  const submit = async () => {
    const items: FileItem[] = [
      ...Array.from(selectedMeetings).map((id) => ({
        type: "meeting" as const,
        ref: String(id),
      })),
      ...Array.from(selectedTickets).map((key) => ({
        type: "ticket" as const,
        ref: key,
      })),
    ];
    const collected: Record<string, FilingResult> = {};
    try {
      const r = await file.mutateAsync({ projectContextId, items });
      for (const result of r.results) {
        collected[itemKey(result.type, result.ref)] = result;
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Request failed";
      for (const item of items) {
        collected[itemKey(item.type, item.ref)] = {
          type: item.type,
          ref: item.ref,
          status: "failed",
          driveDocId: null,
          driveDocUrl: null,
          error: msg,
        };
      }
    }
    setResultsByItem(collected);
  };

  const atlassianConnected = me.data?.connections.atlassian === true;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-[560px]">
        <DialogHeader>
          <DialogTitle>Add items to {projectContextLabel}</DialogTitle>
          <DialogDescription>
            File one or more meeting summaries and / or Jira tickets into
            this Project Context's Drive folder. The final admit step in
            claude.ai is manual.
          </DialogDescription>
        </DialogHeader>

        <div className="px-6 pb-2">
          {showingResults ? (
            <>
              <ResultsBanner />
              <ResultsList
                meetings={meetings.data ?? []}
                tickets={tickets.data?.tickets ?? []}
                resultsByItem={resultsByItem}
              />
            </>
          ) : (
            <>
              <div className="mb-3 flex gap-1.5 rounded-md bg-surface-2 p-1">
                <TabButton
                  active={tab === "minutes"}
                  onClick={() => setTab("minutes")}
                  count={selectedMeetings.size}
                >
                  Minutes
                </TabButton>
                <TabButton
                  active={tab === "tickets"}
                  onClick={() => setTab("tickets")}
                  count={selectedTickets.size}
                >
                  Tickets
                </TabButton>
              </div>

              <div className="relative mb-3">
                <Search
                  size={14}
                  className="absolute left-2.5 top-2.5 text-muted-foreground"
                />
                <input
                  type="text"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder={
                    tab === "minutes"
                      ? "Search minutes by title or series…"
                      : "Search tickets by key, summary, or project…"
                  }
                  className="w-full rounded-md border border-border-strong bg-card py-2 pl-8 pr-3 text-sm focus:border-primary focus:outline-none focus:ring-[3px] focus:ring-accent-tint"
                />
              </div>

              {tab === "minutes" ? (
                <MinutesList
                  loading={meetings.isLoading}
                  items={filteredMeetings}
                  selected={selectedMeetings}
                  filed={filedByMeetingId}
                  onToggle={toggleMeeting}
                />
              ) : !atlassianConnected ? (
                <NotConnectedAtlassian />
              ) : (
                <TicketsList
                  loading={tickets.isLoading}
                  items={filteredTickets}
                  selected={selectedTickets}
                  filed={filedByTicketKey}
                  onToggle={toggleTicket}
                />
              )}
            </>
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
                  `Add ${totalSelected || ""}${totalSelected ? " " : ""}item${totalSelected === 1 ? "" : "s"}`
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

const TabButton = ({
  active,
  onClick,
  count,
  children,
}: {
  active: boolean;
  onClick: () => void;
  count: number;
  children: React.ReactNode;
}) => (
  <button
    type="button"
    onClick={onClick}
    className={cn(
      "flex-1 rounded-md px-3 py-1.5 text-[12.5px] font-semibold transition-colors",
      active ? "bg-card text-ink shadow-sm" : "text-muted-foreground hover:text-ink",
    )}
  >
    {children}
    {count > 0 && (
      <span
        className={cn(
          "ml-1.5 inline-flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[10px]",
          active ? "bg-primary text-primary-foreground" : "bg-border-strong text-ink-2",
        )}
      >
        {count}
      </span>
    )}
  </button>
);

const ResultsBanner = () => (
  <div className="mb-3 rounded-md border border-border bg-surface-2 px-3 py-2.5 text-[12px] text-ink-2">
    <div className="font-semibold text-ink">Next: admit each Doc in claude.ai</div>
    <div className="mt-0.5 text-muted-foreground">
      Either re-connect your Drive integration in claude.ai to re-index, or
      paste each Doc URL below into your Project's <em>+ Add files → Drive</em>{" "}
      picker.
    </div>
  </div>
);

const NotConnectedAtlassian = () => (
  <div className="flex flex-col items-center justify-center px-4 py-8 text-center">
    <div className="mb-3 grid h-10 w-10 place-items-center rounded-[10px] bg-accent-tint text-primary">
      <TicketIcon size={18} />
    </div>
    <p className="text-sm font-semibold text-ink">Atlassian not connected</p>
    <p className="mt-1 text-[12.5px] text-muted-foreground">
      Connect Atlassian from your Profile to file Jira tickets into Project
      Contexts.
    </p>
  </div>
);

// --- Minutes list -----------------------------------------------------------

const MinutesList = ({
  loading,
  items,
  selected,
  filed,
  onToggle,
}: {
  loading: boolean;
  items: MeetingListItem[];
  selected: Set<number>;
  filed: Set<string>;
  onToggle: (id: number) => void;
}) => {
  if (loading) {
    return <p className="py-4 text-sm text-muted-foreground">Loading…</p>;
  }
  if (items.length === 0) {
    return <p className="py-4 text-sm text-muted-foreground">No matching minutes.</p>;
  }
  return (
    <ul className="max-h-[320px] overflow-auto rounded-md border border-border">
      {items.slice(0, 100).map((m) => (
        <li key={m.id}>
          <MinuteRow
            meeting={m}
            isSelected={selected.has(m.id)}
            filed={filed.has(String(m.id))}
            onToggle={() => onToggle(m.id)}
          />
        </li>
      ))}
    </ul>
  );
};

const MinuteRow = ({
  meeting,
  isSelected,
  filed,
  onToggle,
}: {
  meeting: MeetingListItem;
  isSelected: boolean;
  filed: boolean;
  onToggle: () => void;
}) => (
  <button
    type="button"
    onClick={onToggle}
    disabled={filed}
    title={filed ? "Already filed into this Project Context" : undefined}
    className={cn(
      "flex w-full items-center gap-3 border-b border-border px-3 py-2.5 text-left last:border-b-0",
      filed
        ? "cursor-not-allowed opacity-60"
        : isSelected
          ? "bg-accent-tint"
          : "hover:bg-surface-2",
    )}
  >
    <Checkbox checked={isSelected} disabled={filed} />
    <span className="font-mono text-[11px] text-muted-foreground-2 w-[64px] flex-none">
      {formatLocalDateShort(meeting.occurredAt)}
      <br />
      {formatLocalTime(meeting.occurredAt)}
    </span>
    <span className="min-w-0 flex-1">
      <span className="block truncate text-[13px] font-semibold text-ink">
        {meeting.title}
      </span>
      <span className="text-[11px] text-muted-foreground">
        {meeting.seriesTitle}
      </span>
    </span>
    {filed && <Badge variant="muted">Filed</Badge>}
  </button>
);

// --- Tickets list -----------------------------------------------------------

const TicketsList = ({
  loading,
  items,
  selected,
  filed,
  onToggle,
}: {
  loading: boolean;
  items: TicketListItem[];
  selected: Set<string>;
  filed: Set<string>;
  onToggle: (key: string) => void;
}) => {
  if (loading) {
    return <p className="py-4 text-sm text-muted-foreground">Loading…</p>;
  }
  if (items.length === 0) {
    return (
      <p className="py-4 text-sm text-muted-foreground">No matching tickets.</p>
    );
  }
  return (
    <ul className="max-h-[320px] overflow-auto rounded-md border border-border">
      {items.slice(0, 100).map((t) => (
        <li key={t.key}>
          <TicketRow
            ticket={t}
            isSelected={selected.has(t.key)}
            filed={filed.has(t.key)}
            onToggle={() => onToggle(t.key)}
          />
        </li>
      ))}
    </ul>
  );
};

const TicketRow = ({
  ticket,
  isSelected,
  filed,
  onToggle,
}: {
  ticket: TicketListItem;
  isSelected: boolean;
  filed: boolean;
  onToggle: () => void;
}) => (
  <button
    type="button"
    onClick={onToggle}
    disabled={filed}
    title={filed ? "Already filed into this Project Context" : undefined}
    className={cn(
      "flex w-full items-center gap-3 border-b border-border px-3 py-2.5 text-left last:border-b-0",
      filed
        ? "cursor-not-allowed opacity-60"
        : isSelected
          ? "bg-accent-tint"
          : "hover:bg-surface-2",
    )}
  >
    <Checkbox checked={isSelected} disabled={filed} />
    <span className="font-mono text-[11px] font-semibold text-muted-foreground w-[64px] flex-none">
      {ticket.key}
    </span>
    <span className="min-w-0 flex-1">
      <span className="block truncate text-[13px] font-semibold text-ink">
        {ticket.summary}
      </span>
      <span className="text-[11px] text-muted-foreground">
        {ticket.project.name} · {ticket.status}
      </span>
    </span>
    {filed && <Badge variant="muted">Filed</Badge>}
  </button>
);

const Checkbox = ({
  checked,
  disabled,
}: {
  checked: boolean;
  disabled: boolean;
}) => (
  <span
    className={cn(
      "grid h-4 w-4 flex-none place-items-center rounded border",
      disabled
        ? "border-border bg-surface-2"
        : checked
          ? "border-primary bg-primary"
          : "border-border-strong bg-card",
    )}
  >
    {checked && !disabled && (
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
);

// --- Results list (mixed) ---------------------------------------------------

const ResultsList = ({
  meetings,
  tickets,
  resultsByItem,
}: {
  meetings: MeetingListItem[];
  tickets: TicketListItem[];
  resultsByItem: Record<string, FilingResult>;
}) => {
  // Build a stable display order: keep results in the order they came back,
  // but enrich each with a human-readable title.
  const rows = Object.entries(resultsByItem).map(([key, result]) => {
    let title = result.ref;
    if (result.type === "meeting") {
      const m = meetings.find((mm) => String(mm.id) === result.ref);
      title = m?.title ?? `Meeting #${result.ref}`;
    } else {
      const t = tickets.find((tt) => tt.key === result.ref);
      title = t ? `${t.key} · ${t.summary}` : `Ticket ${result.ref}`;
    }
    return { key, result, title };
  });

  return (
    <ul className="rounded-md border border-border">
      {rows.map(({ key, result, title }) => {
        const ok = result.status === "success" || result.status === "skipped";
        return (
          <li
            key={key}
            className="flex items-start gap-3 border-b border-border px-3 py-3 last:border-b-0"
          >
            <span className="mt-0.5 flex-none">
              {ok ? (
                <CheckCircle2
                  size={16}
                  className="text-[hsl(141_63%_33%)]"
                />
              ) : (
                <XCircle size={16} className="text-destructive" />
              )}
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 text-[13.5px] font-semibold text-ink">
                <Badge variant="muted">
                  {result.type === "ticket" ? "Ticket" : "Minute"}
                </Badge>
                <span className="truncate">{title}</span>
              </div>
              <div className="mt-0.5 text-[12px] text-muted-foreground">
                {result.status === "success" && "Filed."}
                {result.status === "skipped" &&
                  "Already filed — Doc reused, no duplicate."}
                {result.status === "failed" && (result.error ?? "Failed.")}
              </div>
              {ok && result.driveDocUrl && (
                <div className="mt-1.5 flex flex-wrap items-center gap-2">
                  <CopyUrlButton url={result.driveDocUrl} label="Copy Doc URL" />
                  <a
                    href={result.driveDocUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-[12px] font-semibold text-primary hover:underline"
                  >
                    Open Doc
                    <ExternalLink size={11} />
                  </a>
                </div>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
};
