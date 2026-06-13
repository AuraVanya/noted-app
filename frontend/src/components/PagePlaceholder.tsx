import { Card, CardContent } from "@/components/ui/card";

interface PagePlaceholderProps {
  title: string;
  description: string;
  phase: string;
}

export const PagePlaceholder = ({
  title,
  description,
  phase,
}: PagePlaceholderProps) => {
  return (
    <div>
      <div className="mb-6">
        <h2 className="mb-1 text-2xl font-bold tracking-tight text-ink">
          {title}
        </h2>
        <p className="text-sm text-muted-foreground">{description}</p>
      </div>

      <Card>
        <CardContent className="flex flex-col items-start gap-3 p-6 pt-6">
          <span className="font-mono text-[10.5px] font-semibold uppercase tracking-[0.14em] text-muted-foreground-2">
            {phase}
          </span>
          <p className="text-sm text-ink-2">
            Coming in a later phase. The route, sidebar entry, and active-state
            styling are wired up — the content lands when this phase ships.
          </p>
        </CardContent>
      </Card>
    </div>
  );
};
