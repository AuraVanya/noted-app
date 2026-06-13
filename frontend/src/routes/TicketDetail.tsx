import { useState } from "react";
import { ArrowLeft, Lightbulb } from "lucide-react";
import { Link, useParams } from "react-router-dom";

import { AddTicketToContextDialog } from "@/components/AddToContextDialogs";
import { RichHtml } from "@/components/RichHtml";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  useTicket,
  type TicketColumn,
  type TicketDetail as TicketDetailData,
} from "@/hooks/useTickets";
import { formatLocalDate, formatLocalTime } from "@/lib/format";

const COLUMN_PILL_COLOR: Record<TicketColumn, string> = {
  todo: "bg-surface-2 text-ink-2",
  in_progress: "bg-accent-tint text-primary",
  in_review: "bg-[hsl(244_60%_92%)] text-primary",
  done: "bg-[hsl(141_36%_93%)] text-[hsl(141_63%_33%)]",
};

export const TicketDetail = () => {
  const { key } = useParams<{ key: string }>();
  const ticket = useTicket(key);

  return (
    <div>
      <Link
        to="/tickets"
        className="mb-6 inline-flex items-center gap-1.5 text-[12.5px] font-medium text-muted-foreground transition-colors hover:text-ink"
      >
        <ArrowLeft size={14} />
        Back to Tickets
      </Link>

      {ticket.isLoading ? (
        <p className="text-sm text-muted-foreground">Loading ticket…</p>
      ) : ticket.isError ? (
        <p className="text-sm text-destructive">
          Couldn't load ticket: {ticket.error.message}
        </p>
      ) : ticket.data ? (
        <Loaded ticket={ticket.data} />
      ) : null}
    </div>
  );
};

const Loaded = ({ ticket }: { ticket: TicketDetailData }) => {
  const [addOpen, setAddOpen] = useState(false);
  return (
  <>
    <div className="mb-5 flex items-start justify-between gap-4">
      <div className="min-w-0 flex-1">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          {ticket.typeIconUrl && (
            <img src={ticket.typeIconUrl} alt={ticket.type} className="h-4 w-4" />
          )}
          <span className="font-mono text-[12px] font-semibold text-muted-foreground">
            {ticket.key}
          </span>
          <Badge variant="muted">{ticket.project.name}</Badge>
          <span
            className={`rounded-full px-2 py-0.5 text-[10.5px] font-semibold ${COLUMN_PILL_COLOR[ticket.column]}`}
          >
            {ticket.status}
          </span>
          {ticket.priorityIconUrl && (
            <img
              src={ticket.priorityIconUrl}
              alt={ticket.priority ?? ""}
              className="h-4 w-4"
              title={ticket.priority ?? undefined}
            />
          )}
          {ticket.assignee && (
            <span className="text-[12px] text-muted-foreground">
              Assigned to{" "}
              <strong className="font-semibold text-ink-2">
                {ticket.assignee.displayName}
              </strong>
            </span>
          )}
        </div>
        <h2 className="text-2xl font-bold tracking-tight text-ink">
          {ticket.summary}
        </h2>
      </div>
      <Button onClick={() => setAddOpen(true)}>
        <Lightbulb size={14} />
        Add to Project Context
      </Button>
    </div>

    <Card className="mb-4 p-6">
      <div className="mb-3 font-mono text-[10.5px] font-semibold uppercase tracking-[0.14em] text-muted-foreground-2">
        Description
      </div>
      {ticket.descriptionHtml ? (
        <RichHtml html={ticket.descriptionHtml} />
      ) : ticket.description ? (
        <div className="whitespace-pre-wrap text-[14px] leading-[1.65] text-ink-2">
          {ticket.description}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">No description.</p>
      )}
    </Card>

    {ticket.comments.length > 0 && (
      <Card className="p-6">
        <div className="mb-3 font-mono text-[10.5px] font-semibold uppercase tracking-[0.14em] text-muted-foreground-2">
          Comments ({ticket.comments.length})
        </div>
        <ul className="flex flex-col gap-4">
          {ticket.comments.map((c) => (
            <li key={c.id} className="border-l-2 border-border pl-3.5">
              <div className="mb-1 flex items-center gap-2 text-[12px]">
                <span className="font-semibold text-ink">
                  {c.author.displayName}
                </span>
                <span className="font-mono text-[11px] text-muted-foreground">
                  {formatLocalDate(c.createdAt)} ·{" "}
                  {formatLocalTime(c.createdAt)}
                </span>
              </div>
              {c.bodyHtml ? (
                <RichHtml html={c.bodyHtml} />
              ) : (
                <div className="whitespace-pre-wrap text-[13.5px] leading-[1.6] text-ink-2">
                  {c.body}
                </div>
              )}
            </li>
          ))}
        </ul>
      </Card>
    )}

    <AddTicketToContextDialog
      open={addOpen}
      onOpenChange={setAddOpen}
      ticketKey={ticket.key}
    />
  </>
  );
};
