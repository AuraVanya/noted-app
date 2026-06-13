import { useEffect, useRef, useState } from "react";
import { ExternalLink, Folder, Loader2 } from "lucide-react";

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
  searchDriveFolders,
  useCreateProjectContext,
  type DriveFolderResult,
} from "@/hooks/useProjectContexts";
import { cn } from "@/lib/utils";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export const CreateProjectContextDialog = ({ open, onOpenChange }: Props) => {
  const [mode, setMode] = useState<"create" | "existing">("create");
  const [label, setLabel] = useState("");
  const [selectedFolder, setSelectedFolder] = useState<DriveFolderResult | null>(
    null,
  );

  const create = useCreateProjectContext();

  // Reset internal form + mutation state only on the close *transition*.
  // (Earlier this lived in a useEffect with `create` in the deps. That
  // mutation object is a new reference every render, so the effect fired
  // on every render where open=false and starved the Outlet's re-render
  // during route changes — URL would update but the page wouldn't.)
  const wasOpen = useRef(open);
  useEffect(() => {
    if (wasOpen.current && !open) {
      setMode("create");
      setLabel("");
      setSelectedFolder(null);
      create.reset();
    }
    wasOpen.current = open;
    // create.reset is referentially unstable; intentionally excluded
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const canSubmit =
    label.trim().length > 0 &&
    (mode === "create" || selectedFolder !== null) &&
    !create.isPending;

  const submit = async () => {
    try {
      await create.mutateAsync({
        label: label.trim(),
        mode,
        folderId: mode === "existing" ? selectedFolder?.id : undefined,
      });
      onOpenChange(false);
    } catch {
      // Mutation error surfaces below via create.error
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-[480px]">
        <DialogHeader>
          <DialogTitle>New Project Context</DialogTitle>
          <DialogDescription>
            A Project Context is a Drive folder Noted files Doc copies of your
            meetings and tickets into. You then add it to your claude.ai
            Project once — it auto-syncs after.
          </DialogDescription>
        </DialogHeader>

        <div className="px-6 pb-2">
          <div className="mb-4 flex gap-1.5 rounded-md bg-surface-2 p-1">
            <ModeTab active={mode === "create"} onClick={() => setMode("create")}>
              Create new folder
            </ModeTab>
            <ModeTab
              active={mode === "existing"}
              onClick={() => setMode("existing")}
            >
              Use existing folder
            </ModeTab>
          </div>

          <label className="mb-1.5 block text-[12px] font-medium text-ink-2">
            Label
          </label>
          <input
            type="text"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="e.g. Team Best"
            className="mb-4 w-full rounded-md border border-border-strong bg-card px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-[3px] focus:ring-accent-tint"
          />

          {mode === "create" ? (
            <p className="text-[12.5px] text-muted-foreground">
              We'll create a new Drive folder named <strong>{label || "—"}</strong>{" "}
              in your Drive. You'll point your claude.ai Project at this folder
              once.
            </p>
          ) : (
            <ExistingFolderPicker
              selected={selectedFolder}
              onSelect={setSelectedFolder}
            />
          )}

          {create.isError && (
            <p className="mt-3 text-[12.5px] text-destructive">
              {create.error.message}
            </p>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={!canSubmit}>
            {create.isPending ? (
              <>
                <Loader2 size={14} className="animate-spin" />
                Creating…
              </>
            ) : (
              "Create"
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

const ModeTab = ({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
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
  </button>
);

const ExistingFolderPicker = ({
  selected,
  onSelect,
}: {
  selected: DriveFolderResult | null;
  onSelect: (f: DriveFolderResult | null) => void;
}) => {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<DriveFolderResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Debounce the search by 250ms
  useEffect(() => {
    const term = query.trim();
    if (term.length === 0) {
      setResults([]);
      setError(null);
      return;
    }
    setLoading(true);
    const handle = setTimeout(async () => {
      try {
        const r = await searchDriveFolders(term);
        setResults(r);
        setError(null);
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : "Search failed";
        setError(msg);
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, 250);
    return () => clearTimeout(handle);
  }, [query]);

  return (
    <div>
      <label className="mb-1.5 block text-[12px] font-medium text-ink-2">
        Search Drive folders
      </label>
      <input
        type="text"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Type part of a folder name…"
        className="w-full rounded-md border border-border-strong bg-card px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-[3px] focus:ring-accent-tint"
      />
      <div className="mt-2 max-h-[200px] overflow-auto rounded-md border border-border">
        {loading ? (
          <div className="px-3 py-2 text-[12.5px] text-muted-foreground">
            Searching…
          </div>
        ) : error ? (
          <div className="px-3 py-2 text-[12.5px] text-destructive">{error}</div>
        ) : results.length === 0 && query.trim().length > 0 ? (
          <div className="px-3 py-2 text-[12.5px] text-muted-foreground">
            No folders match. Try a different name.
          </div>
        ) : (
          results.map((f) => (
            <button
              key={f.id}
              type="button"
              onClick={() => onSelect(f)}
              className={cn(
                "flex w-full items-center gap-2 border-b border-border px-3 py-2 text-left text-[13px] last:border-b-0",
                selected?.id === f.id
                  ? "bg-accent-tint text-primary"
                  : "hover:bg-surface-2",
              )}
            >
              <Folder size={14} className="flex-none" />
              <span className="flex-1 truncate">{f.name}</span>
              {f.url && (
                <a
                  href={f.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={(e) => e.stopPropagation()}
                  className="text-muted-foreground hover:text-primary"
                  aria-label="Open folder in Drive"
                >
                  <ExternalLink size={12} />
                </a>
              )}
            </button>
          ))
        )}
      </div>
      {selected && (
        <p className="mt-2 text-[12px] text-muted-foreground">
          Selected: <strong className="text-ink-2">{selected.name}</strong>
        </p>
      )}
    </div>
  );
};
