import { useMemo, useState } from "react";
import {
  ArrowLeft,
  CheckCircle2,
  ExternalLink,
  FolderOpen,
  Plus,
  Trash2,
  XCircle,
} from "lucide-react";
import { Link, useParams } from "react-router-dom";

import { AddItemsToContextDialog } from "@/components/AddItemsToContextDialog";
import { CopyUrlButton } from "@/components/CopyUrlButton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useMeetings, type MeetingListItem } from "@/hooks/useMeetings";
import {
  useDeleteFiledDoc,
  useFiledDocs,
  useProjectContexts,
  type FiledDoc,
} from "@/hooks/useProjectContexts";
import { formatLocalDateShort, formatLocalTime } from "@/lib/format";
import { cn } from "@/lib/utils";

export const ProjectContextDetail = () => {
  const { id } = useParams<{ id: string }>();
  const contextId = id ? Number(id) : undefined;

  const contexts = useProjectContexts();
  const docs = useFiledDocs(contextId);
  const meetings = useMeetings();
  const [pickerOpen, setPickerOpen] = useState(false);

  const ctx = useMemo(() => {
    if (!contextId || !contexts.data) return undefined;
    return contexts.data.find((c) => c.id === contextId);
  }, [contextId, contexts.data]);

  const meetingById = useMemo(() => {
    const map = new Map<string, MeetingListItem>();
    for (const m of meetings.data ?? []) map.set(String(m.id), m);
    return map;
  }, [meetings.data]);

  return (
    <div>
      <Link
        to="/project-context"
        className="mb-6 inline-flex items-center gap-1.5 text-[12.5px] font-medium text-muted-foreground transition-colors hover:text-ink"
      >
        <ArrowLeft size={14} />
        Back to Project Contexts
      </Link>

      {contexts.isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : !ctx ? (
        <p className="text-sm text-muted-foreground">
          Project Context not found.
        </p>
      ) : (
        <>
          <div className="mb-6 flex items-start justify-between gap-4">
            <div>
              <h2 className="mb-1 text-2xl font-bold tracking-tight text-ink">
                {ctx.label}
              </h2>
              <p className="text-sm text-muted-foreground">
                {ctx.docCount} {ctx.docCount === 1 ? "Doc filed" : "Docs filed"}{" "}
                into the mapped Drive folder.
              </p>
            </div>
            <div className="flex items-center gap-2">
              {ctx.driveFolderUrl && (
                <a
                  href={ctx.driveFolderUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 rounded-md border border-border-strong bg-card px-2.5 py-2 text-[12.5px] font-semibold text-ink-2 transition-colors hover:bg-surface-2"
                >
                  <FolderOpen size={13} />
                  Open folder
                  <ExternalLink size={11} />
                </a>
              )}
              <Button onClick={() => setPickerOpen(true)}>
                <Plus size={14} />
                Add context to project
              </Button>
            </div>
          </div>

          {docs.isLoading ? (
            <p className="text-sm text-muted-foreground">Loading filed Docs…</p>
          ) : (docs.data ?? []).length === 0 ? (
            <EmptyDocs onAdd={() => setPickerOpen(true)} />
          ) : (
            <ul className="flex flex-col gap-2.5">
              {(docs.data ?? []).map((d) => {
                if (d.itemType === "ticket") {
                  return (
                    <li key={d.id}>
                      <FiledDocRow
                        doc={d}
                        projectContextId={ctx.id}
                        title={d.itemRef}
                        subtitle="Jira ticket"
                        detailLink={`/tickets/${d.itemRef}`}
                        detailLabel="View ticket"
                      />
                    </li>
                  );
                }
                const m = meetingById.get(d.itemRef);
                return (
                  <li key={d.id}>
                    <FiledDocRow
                      doc={d}
                      projectContextId={ctx.id}
                      title={m?.title ?? `Meeting #${d.itemRef}`}
                      subtitle={
                        m?.occurredAt
                          ? `${formatLocalDateShort(m.occurredAt)} · ${formatLocalTime(m.occurredAt)}`
                          : undefined
                      }
                      detailLink={`/minutes/${d.itemRef}`}
                      detailLabel="View minute"
                    />
                  </li>
                );
              })}
            </ul>
          )}
        </>
      )}

      {ctx && (
        <AddItemsToContextDialog
          open={pickerOpen}
          onOpenChange={setPickerOpen}
          projectContextId={ctx.id}
          projectContextLabel={ctx.label}
        />
      )}
    </div>
  );
};

const FiledDocRow = ({
  doc,
  projectContextId,
  title,
  subtitle,
  detailLink,
  detailLabel,
}: {
  doc: FiledDoc;
  projectContextId: number;
  title: string;
  subtitle?: string;
  detailLink: string;
  detailLabel: string;
}) => {
  const del = useDeleteFiledDoc();
  const onDelete = async () => {
    const ok = confirm(
      `Remove the filed Doc for "${title}"?\n\n` +
        `This will:\n` +
        `  • Remove the row from Noted\n` +
        `  • Move the Google Doc to Drive Trash\n\n` +
        `You can re-file the same item later if you change your mind.`,
    );
    if (!ok) return;
    try {
      const result = await del.mutateAsync({
        projectContextId,
        docId: doc.id,
        deleteDriveFile: true,
      });
      if (!result.driveTrashed && result.driveError) {
        alert(
          `Removed the row from Noted, but the Google Doc couldn't be trashed:\n\n` +
            `${result.driveError}\n\n` +
            `You can delete the Doc manually in Drive if needed.`,
        );
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Delete failed";
      alert(msg);
    }
  };

  return (
    <Card className="flex items-center gap-4 px-[18px] py-3">
    <span className="mt-0.5 flex-none">
      {doc.status === "success" ? (
        <CheckCircle2 size={16} className="text-[hsl(141_63%_33%)]" />
      ) : (
        <XCircle size={16} className="text-destructive" />
      )}
    </span>
    <div className="min-w-0 flex-1">
      <div className="flex flex-wrap items-center gap-2">
        <span className="truncate text-[13.5px] font-semibold text-ink">
          {title}
        </span>
        {subtitle && (
          <span className="font-mono text-[11.5px] text-muted-foreground">
            {subtitle}
          </span>
        )}
        <Badge variant="muted">
          {doc.itemType === "ticket" ? "Ticket" : "Minute"}
        </Badge>
        <Badge variant={doc.trigger === "auto" ? "default" : "muted"}>
          {doc.trigger === "auto" ? "Auto" : "Manual"}
        </Badge>
      </div>
      <div className="mt-0.5 flex items-center gap-3 text-[11.5px] text-muted-foreground">
        <span className="font-mono">
          Filed {formatLocalDateShort(doc.createdAt)} ·{" "}
          {formatLocalTime(doc.createdAt)}
        </span>
        {doc.status === "failed" && (
          <span className={cn("text-destructive")}>{doc.error}</span>
        )}
      </div>
    </div>
    {doc.driveDocUrl && <CopyUrlButton url={doc.driveDocUrl} />}
    {doc.driveDocUrl && (
      <a
        href={doc.driveDocUrl}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-1 rounded-md border border-border-strong bg-card px-2.5 py-1.5 text-[12px] font-semibold text-ink-2 transition-colors hover:bg-surface-2"
      >
        Open Doc
        <ExternalLink size={11} />
      </a>
    )}
    <Link
      to={detailLink}
      className="inline-flex items-center gap-1 rounded-md border border-border-strong bg-card px-2.5 py-1.5 text-[12px] font-semibold text-ink-2 transition-colors hover:bg-surface-2"
    >
      {detailLabel}
    </Link>
    <button
      type="button"
      onClick={onDelete}
      disabled={del.isPending}
      aria-label="Remove this filed Doc"
      title="Remove this filed Doc (and trash it in Drive)"
      className="grid h-8 w-8 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-surface-2 hover:text-destructive disabled:opacity-50"
    >
      <Trash2 size={14} />
    </button>
  </Card>
  );
};

const EmptyDocs = ({ onAdd }: { onAdd: () => void }) => (
  <Card className="flex flex-col items-center justify-center px-4 py-10 text-center">
    <p className="text-sm font-semibold text-ink">No Docs filed yet</p>
    <p className="mt-1 max-w-[440px] text-[13px] text-muted-foreground">
      Add minutes to this Project Context — Noted will file each one as a Google
      Doc in the mapped Drive folder.
    </p>
    <Button className="mt-5" onClick={onAdd}>
      <Plus size={14} />
      Add context to project
    </Button>
  </Card>
);
