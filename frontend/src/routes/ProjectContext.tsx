import { useState } from "react";
import {
  ChevronRight,
  ExternalLink,
  FolderOpen,
  Lightbulb,
  Plus,
  Trash2,
} from "lucide-react";
import { Link } from "react-router-dom";

import { CreateProjectContextDialog } from "@/components/CreateProjectContextDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  useDeleteProjectContext,
  useProjectContexts,
  type ProjectContext as ProjectContextRow,
} from "@/hooks/useProjectContexts";
import { formatLocalDate } from "@/lib/format";

export const ProjectContext = () => {
  const contexts = useProjectContexts();
  const [createOpen, setCreateOpen] = useState(false);

  return (
    <div>
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h2 className="mb-1 text-2xl font-bold tracking-tight text-ink">
            Project Context
          </h2>
          <p className="text-sm text-muted-foreground">
            Each Project Context maps to one folder. Noted files Docs of your
            meetings and tickets into that folder. Add the folder to your AI
            Project once and it auto-syncs after.
          </p>
          <a
            href="https://claude.ai/projects"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 text-[12.5px] font-semibold text-primary hover:underline"
          >
            Open claude.ai Projects ↗
          </a>
        </div>
        <div className="mt-5">
          <Button onClick={() => setCreateOpen(true)}>
            <Plus size={14} />
            New Project Context
          </Button>
        </div>
      </div>

      {contexts.isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : contexts.isError ? (
        <p className="text-sm text-destructive">
          Couldn't load Project Contexts: {contexts.error.message}
        </p>
      ) : contexts.data && contexts.data.length === 0 ? (
        <EmptyState onCreate={() => setCreateOpen(true)} />
      ) : (
        <ul className="flex flex-col gap-2.5">
          {contexts.data?.map((ctx) => (
            <li key={ctx.id}>
              <ProjectContextRowView ctx={ctx} />
            </li>
          ))}
        </ul>
      )}

      <CreateProjectContextDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
      />
    </div>
  );
};

const ProjectContextRowView = ({ ctx }: { ctx: ProjectContextRow }) => {
  const del = useDeleteProjectContext();
  const onDelete = async () => {
    const ok = confirm(
      `Delete "${ctx.label}"?\n\n` +
        `This will:\n` +
        `  • Remove the Project Context from Noted\n` +
        `  • Move the linked Drive folder (and the Docs filed inside it) to Drive Trash\n\n` +
        `You can restore the folder from Drive Trash within ~30 days. ` +
        `This action does not affect anything in claude.ai.`,
    );
    if (!ok) return;
    try {
      const result = await del.mutateAsync({
        id: ctx.id,
        deleteDriveFolder: true,
      });
      if (!result.driveFolderTrashed && result.driveFolderError) {
        // Registry row is gone, but the Drive folder couldn't be trashed.
        // Be honest about it.
        alert(
          `Removed "${ctx.label}" from Noted, but the Drive folder couldn't ` +
            `be trashed:\n\n${result.driveFolderError}\n\n` +
            `You can delete the folder manually in Drive if needed.`,
        );
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Delete failed";
      alert(msg);
    }
  };

  return (
    <Card className="flex items-center gap-4 px-[18px] py-4 transition-all hover:-translate-y-px hover:border-border-strong hover:shadow-md">
      <Link
        to={`/project-context/${ctx.id}`}
        className="grid h-10 w-10 flex-none place-items-center rounded-[10px] bg-accent-tint text-primary transition-colors hover:bg-accent"
      >
        <Lightbulb size={18} />
      </Link>
      <Link to={`/project-context/${ctx.id}`} className="min-w-0 flex-1 group">
        <div className="flex flex-wrap items-center gap-2">
          <span className="truncate text-[14.5px] font-semibold text-ink group-hover:text-primary">
            {ctx.label}
          </span>
          <Badge variant="muted">
            {ctx.docCount} {ctx.docCount === 1 ? "Doc filed" : "Docs filed"}
          </Badge>
        </div>
        <div className="mt-1 flex items-center gap-3 text-[11.5px] text-muted-foreground">
          <span className="font-mono">
            Created {formatLocalDate(ctx.createdAt)}
          </span>
        </div>
      </Link>
      <div className="flex flex-none items-center gap-2">
        {ctx.driveFolderUrl && (
          <a
            href={ctx.driveFolderUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 rounded-md border border-border-strong bg-card px-2.5 py-1.5 text-[12px] font-semibold text-ink-2 transition-colors hover:bg-surface-2"
          >
            <FolderOpen size={13} />
            Open folder
            <ExternalLink size={11} />
          </a>
        )}
        <Link
          to={`/project-context/${ctx.id}`}
          aria-label="Open Project Context"
          className="grid h-8 w-8 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-surface-2 hover:text-primary"
        >
          <ChevronRight size={16} />
        </Link>
        <button
          type="button"
          onClick={onDelete}
          disabled={del.isPending}
          aria-label="Remove this Project Context from Noted"
          title="Remove this Project Context from Noted"
          className="grid h-8 w-8 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-surface-2 hover:text-destructive"
        >
          <Trash2 size={14} />
        </button>
      </div>
    </Card>
  );
};

const EmptyState = ({ onCreate }: { onCreate: () => void }) => (
  <Card className="flex flex-col items-center justify-center px-4 py-12 text-center">
    <div className="mb-3 grid h-12 w-12 place-items-center rounded-[12px] bg-accent-tint text-primary">
      <Lightbulb size={20} />
    </div>
    <p className="text-base font-semibold text-ink">No Project Contexts yet</p>
    <p className="mt-1 max-w-[440px] text-[13px] text-muted-foreground">
      Create one to start filing meeting and ticket Docs into a Drive folder
      your claude.ai Project can sync from.
    </p>
    <Button className="mt-5" onClick={onCreate}>
      <Plus size={14} />
      Create your first Project Context
    </Button>
  </Card>
);
