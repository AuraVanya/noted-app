import { useEffect, useMemo, useRef, useState } from "react";
import { Pin, PinOff, Ticket as TicketIcon } from "lucide-react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useJiraPins, useUpdateJiraPins } from "@/hooks/useJiraPins";
import { useMe } from "@/hooks/useMe";
import {
  useTickets,
  type TicketColumn,
  type TicketListItem,
  type TicketProject,
} from "@/hooks/useTickets";
import { cn } from "@/lib/utils";

const COLUMN_DEFS: { key: TicketColumn; label: string }[] = [
  { key: "todo", label: "To Do" },
  { key: "in_progress", label: "In Progress" },
  { key: "in_review", label: "In Review" },
  { key: "done", label: "Done" },
];

export const Tickets = () => {
  const me = useMe();

  if (!me.data) {
    return <p className="text-sm text-muted-foreground">Loading…</p>;
  }

  return (
    <div>
      <div className="mb-6">
        <h2 className="mb-1 text-2xl font-bold tracking-tight text-ink">
          Tickets
        </h2>
        <p className="text-sm text-muted-foreground">
          Jira issues assigned to you, by status.
        </p>
      </div>

      {me.data.connections.atlassian ? <Kanban /> : <ConnectAtlassianCTA />}
    </div>
  );
};

const Kanban = () => {
  const tickets = useTickets();
  const pins = useJiraPins();
  const updatePins = useUpdateJiraPins();
  const [projectFilter, setProjectFilter] = useState<string | null>("");

  // Default the filter to the first pinned project on first mount. We do
  // it once per session in this Kanban — if the user navigates away and
  // back, they re-anchor to their pin. They can still pick "All projects"
  // or another chip and we don't fight them after that.
  const didInitFilter = useRef(false);
  useEffect(() => {
    if (didInitFilter.current) return;
    if (!pins.data || !tickets.data) return;
    const firstPin = pins.data.projectKeys.find((k) =>
      tickets.data!.projects.some((p) => p.key === k),
    );
    if (firstPin) setProjectFilter(firstPin);
    didInitFilter.current = true;
  }, [pins.data, tickets.data]);

  // Sort projects: pinned ones first (in pin order), then the rest by name.
  const orderedProjects = useMemo<TicketProject[]>(() => {
    if (!tickets.data) return [];
    const pinSet = new Set(pins.data?.projectKeys ?? []);
    const pinOrder: Record<string, number> = {};
    (pins.data?.projectKeys ?? []).forEach((k, i) => (pinOrder[k] = i));

    return [...tickets.data.projects].sort((a, b) => {
      const aPinned = pinSet.has(a.key);
      const bPinned = pinSet.has(b.key);
      if (aPinned && !bPinned) return -1;
      if (!aPinned && bPinned) return 1;
      if (aPinned && bPinned) return pinOrder[a.key] - pinOrder[b.key];
      return a.name.localeCompare(b.name);
    });
  }, [tickets.data, pins.data]);

  const filtered = useMemo(() => {
    if (!tickets.data) return [];
    if (!projectFilter) return tickets.data.tickets;
    return tickets.data.tickets.filter((t) => t.project.key === projectFilter);
  }, [tickets.data, projectFilter]);

  const byColumn = useMemo(() => {
    const buckets: Record<TicketColumn, TicketListItem[]> = {
      todo: [],
      in_progress: [],
      in_review: [],
      done: [],
    };
    for (const t of filtered) buckets[t.column].push(t);
    return buckets;
  }, [filtered]);

  const togglePin = (key: string) => {
    const current = pins.data?.projectKeys ?? [];
    const next = current.includes(key)
      ? current.filter((k) => k !== key)
      : [...current, key];
    updatePins.mutate(next);
  };

  if (tickets.isLoading) {
    return <p className="text-sm text-muted-foreground">Loading tickets…</p>;
  }
  if (tickets.isError) {
    return (
      <p className="text-sm text-destructive">
        Couldn't load tickets: {tickets.error.message}
      </p>
    );
  }
  if (!tickets.data || tickets.data.tickets.length === 0) {
    return <EmptyTickets />;
  }

  const pinSet = new Set(pins.data?.projectKeys ?? []);

  return (
    <>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        {orderedProjects.map((p) => (
          <FilterChip
            key={p.key}
            active={projectFilter === p.key}
            label={p.name}
            pinned={pinSet.has(p.key)}
            onClick={() => setProjectFilter(p.key)}
            onTogglePin={() => togglePin(p.key)}
          />
        ))}
        <FilterChip
          active={projectFilter === null}
          label="All projects"
          onClick={() => setProjectFilter(null)}
        />
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
        {COLUMN_DEFS.map((col) => (
          <KanbanColumn
            key={col.key}
            label={col.label}
            count={byColumn[col.key].length}
            tickets={byColumn[col.key]}
          />
        ))}
      </div>
    </>
  );
};

const FilterChip = ({
  active,
  label,
  pinned,
  onClick,
  onTogglePin,
}: {
  active: boolean;
  label: string;
  pinned?: boolean;
  onClick: () => void;
  onTogglePin?: () => void;
}) => (
  <span
    className={cn(
      "inline-flex items-center gap-1 rounded-full border text-[12px] font-semibold transition-colors",
      active
        ? "border-primary bg-accent-tint text-primary"
        : "border-border-strong bg-card text-ink-2 hover:bg-surface-2",
    )}
  >
    <button type="button" onClick={onClick} className="px-3 py-1">
      {label}
    </button>
    {onTogglePin && (
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onTogglePin();
        }}
        aria-label={pinned ? "Unpin project" : "Pin project"}
        title={
          pinned
            ? "Unpin project"
            : "Pin project — pinned projects appear first and become the default filter"
        }
        className={cn(
          "mr-1.5 grid h-5 w-5 place-items-center rounded-full",
          pinned ? "text-primary" : "text-muted-foreground-2 hover:text-ink-2",
        )}
      >
        {pinned ? <Pin size={11} fill="currentColor" /> : <PinOff size={11} />}
      </button>
    )}
  </span>
);

const KanbanColumn = ({
  label,
  count,
  tickets,
}: {
  label: string;
  count: number;
  tickets: TicketListItem[];
}) => (
  <Card className="flex flex-col gap-2.5 p-3">
    <div className="flex items-center justify-between px-1">
      <span className="font-mono text-[10.5px] font-semibold uppercase tracking-[0.14em] text-muted-foreground-2">
        {label}
      </span>
      <span className="font-mono text-[11px] text-muted-foreground-2">
        {count}
      </span>
    </div>
    {tickets.length === 0 ? (
      <p className="px-1 py-3 text-[12px] text-muted-foreground-2">—</p>
    ) : (
      tickets.map((t) => <TicketCard key={t.key} ticket={t} />)
    )}
  </Card>
);

const TicketCard = ({ ticket }: { ticket: TicketListItem }) => (
  <Link
    to={`/tickets/${ticket.key}`}
    className="block rounded-md border border-border bg-card px-3 py-2.5 shadow-sm transition-all hover:-translate-y-px hover:border-border-strong hover:shadow-md"
  >
    <div className="mb-1 flex items-center gap-2">
      {ticket.typeIconUrl && (
        <img
          src={ticket.typeIconUrl}
          alt={ticket.type}
          className="h-3.5 w-3.5"
        />
      )}
      <span className="font-mono text-[11px] font-semibold text-muted-foreground">
        {ticket.key}
      </span>
      {ticket.priorityIconUrl && (
        <img
          src={ticket.priorityIconUrl}
          alt={ticket.priority ?? ""}
          className="ml-auto h-3.5 w-3.5"
          title={ticket.priority ?? undefined}
        />
      )}
    </div>
    <div className="line-clamp-2 text-[13px] font-semibold text-ink">
      {ticket.summary}
    </div>
    <div className="mt-1.5 flex items-center justify-between gap-2">
      <Badge variant="muted">{ticket.project.key}</Badge>
      <span className="font-mono text-[10.5px] text-muted-foreground-2">
        {ticket.status}
      </span>
    </div>
    {ticket.assignee && (
      <div
        className="mt-2 flex items-center gap-1.5 border-t border-border pt-1.5 text-[11px] text-muted-foreground"
        title={ticket.assignee.email}
      >
        {ticket.assignee.avatarUrl ? (
          <img
            src={ticket.assignee.avatarUrl}
            alt=""
            className="h-3.5 w-3.5 rounded-full"
          />
        ) : (
          <span className="grid h-3.5 w-3.5 place-items-center rounded-full bg-surface-2 text-[8px] font-semibold text-ink-2">
            {(ticket.assignee.displayName || "?")
              .split(" ")
              .map((p) => p[0])
              .join("")
              .slice(0, 2)
              .toUpperCase()}
          </span>
        )}
        <span className="truncate">{ticket.assignee.displayName}</span>
      </div>
    )}
  </Link>
);

const ConnectAtlassianCTA = () => (
  <Card className="flex flex-col items-center justify-center px-4 py-12 text-center">
    <div className="mb-3 grid h-12 w-12 place-items-center rounded-[12px] bg-accent-tint text-primary">
      <TicketIcon size={20} />
    </div>
    <p className="text-base font-semibold text-ink">Connect Atlassian</p>
    <p className="mt-1 max-w-[440px] text-[13px] text-muted-foreground">
      Connect your Atlassian account to see your assigned Jira tickets here and
      file them into Project Contexts. Noted requests read access only.
    </p>
    <Button
      className="mt-5"
      onClick={() => {
        window.location.href = "/api/auth/atlassian/login";
      }}
    >
      Connect Atlassian
    </Button>
  </Card>
);

const EmptyTickets = () => (
  <Card className="flex flex-col items-center justify-center px-4 py-12 text-center">
    <div className="mb-3 grid h-12 w-12 place-items-center rounded-[12px] bg-accent-tint text-primary">
      <TicketIcon size={20} />
    </div>
    <p className="text-base font-semibold text-ink">Nothing assigned</p>
    <p className="mt-1 max-w-[440px] text-[13px] text-muted-foreground">
      No tickets are currently assigned to you. New assignments will show up
      here automatically (Jira reads are live, not cached).
    </p>
  </Card>
);
