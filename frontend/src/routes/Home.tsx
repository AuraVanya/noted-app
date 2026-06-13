import { useMemo } from "react";
import { ChevronRight, Lightbulb } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { Card } from "@/components/ui/card";
import { useCalendarToday, type CalendarEvent } from "@/hooks/useCalendar";
import { useMe } from "@/hooks/useMe";
import { useMeetings } from "@/hooks/useMeetings";
import { formatLocalDateShort, formatLocalTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const greetingFor = (hour: number): string => {
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
};

const firstNameOf = (displayName: string): string =>
  (displayName || "").trim().split(/\s+/)[0] || displayName;

export const Home = () => {
  const me = useMe();
  const today = useCalendarToday();
  const meetings = useMeetings();

  const now = new Date();
  const greeting = greetingFor(now.getHours());
  const firstName = me.data ? firstNameOf(me.data.displayName) : "";

  const todayCount = today.data?.events.length ?? 0;

  // "New summaries this week" — past 7 days, has a summary file.
  const summariesThisWeek = useMemo(() => {
    if (!meetings.data) return 0;
    const weekAgo = new Date();
    weekAgo.setDate(weekAgo.getDate() - 7);
    return meetings.data.filter(
      (m) => m.hasSummary && new Date(m.occurredAt) >= weekAgo,
    ).length;
  }, [meetings.data]);

  return (
    <div>
      <Greeting
        greeting={greeting}
        firstName={firstName}
        chips={[
          {
            label: pluralize(todayCount, "meeting", "meetings") + " today",
          },
          {
            label:
              pluralize(summariesThisWeek, "new summary", "new summaries") +
              " this week",
          },
          { label: "Projects shipping in Phase 4" },
        ]}
      />

      <div className="grid grid-cols-1 gap-[18px] lg:grid-cols-[1.35fr_1fr]">
        <TodayCard
          date={today.data?.date}
          events={today.data?.events ?? []}
          loading={today.isLoading}
          error={today.error?.message}
        />
        <RecentProjectsEmpty />
      </div>
    </div>
  );
};

// --- Greeting ------------------------------------------------------------

interface Chip {
  label: string;
}

const Greeting = ({
  greeting,
  firstName,
  chips,
}: {
  greeting: string;
  firstName: string;
  chips: Chip[];
}) => (
  <div
    className="mb-5 rounded-[16px] px-[30px] py-7 text-primary-foreground shadow-md"
    style={{
      background:
        "linear-gradient(115deg, #4B45C6 0%, #6B5DDA 60%, #7E6BE6 100%)",
    }}
  >
    <h2 className="mb-1.5 text-[26px] font-bold tracking-tight">
      {firstName ? `${greeting}, ${firstName}` : greeting}
    </h2>
    <p className="text-sm opacity-90">
      Here's what's happening across your team today.
    </p>
    <div className="mt-4 flex flex-wrap gap-2">
      {chips.map((c) => (
        <span
          key={c.label}
          className="rounded-full border border-white/20 bg-white/15 px-2.5 py-1 text-[12px] font-medium backdrop-blur-[2px]"
        >
          {c.label}
        </span>
      ))}
    </div>
  </div>
);

const pluralize = (n: number, one: string, many: string): string =>
  `${n} ${n === 1 ? one : many}`;

// --- Today's meetings ----------------------------------------------------

const TodayCard = ({
  date,
  events,
  loading,
  error,
}: {
  date: string | undefined;
  events: CalendarEvent[];
  loading: boolean;
  error: string | undefined;
}) => (
  <Card className="p-[22px]">
    <div className="mb-3.5 flex items-center justify-between">
      <span className="font-mono text-[10.5px] font-semibold uppercase tracking-[0.14em] text-muted-foreground-2">
        Today's meetings
      </span>
      {date && (
        <span className="font-mono text-[11px] text-muted-foreground-2">
          {formatLocalDateShort(`${date}T00:00:00`)}
        </span>
      )}
    </div>
    {loading ? (
      <p className="py-4 text-sm text-muted-foreground">Loading…</p>
    ) : error ? (
      <p className="py-4 text-sm text-destructive">{error}</p>
    ) : events.length === 0 ? (
      <p className="py-4 text-sm text-muted-foreground">
        Nothing on the calendar today.
      </p>
    ) : (
      <ul>
        {events.map((e) => (
          <li key={e.id}>
            <TodayRow event={e} />
          </li>
        ))}
      </ul>
    )}
  </Card>
);

const TodayRow = ({ event }: { event: CalendarEvent }) => {
  const navigate = useNavigate();
  const clickable = event.isPast && event.meetingId !== null;

  const content = (
    <div className="flex items-center gap-3 border-t border-border py-3 first:border-t-0">
      <span className="w-[58px] flex-none text-right font-mono text-[12px] text-muted-foreground">
        {formatLocalTime(event.start)}
      </span>
      <span
        className={cn(
          "h-2 w-2 flex-none rounded-full",
          event.isPast
            ? "bg-[hsl(141_63%_33%)]"
            : "border-[1.5px] border-primary bg-transparent",
        )}
      />
      <div className="min-w-0 flex-1">
        <div className="truncate text-[13.5px] font-semibold text-ink">
          {event.title}
        </div>
        <div className="text-[11.5px] text-muted-foreground">
          {event.attendeeCount > 0 &&
            `${event.attendeeCount} ${event.attendeeCount === 1 ? "attendee" : "attendees"}`}
        </div>
      </div>
      {event.isPast ? (
        event.meetingId !== null ? (
          <span className="rounded-full bg-[hsl(141_36%_93%)] px-2 py-0.5 text-[10.5px] font-semibold text-[hsl(141_63%_33%)]">
            Summary ready
          </span>
        ) : (
          <span className="rounded-full bg-surface-2 px-2 py-0.5 text-[10.5px] font-semibold text-muted-foreground">
            No summary
          </span>
        )
      ) : (
        <span className="rounded-full bg-accent-tint px-2 py-0.5 text-[10.5px] font-semibold text-primary">
          Upcoming
        </span>
      )}
      {clickable && <ChevronRight size={14} className="text-muted-foreground-2" />}
    </div>
  );

  if (!clickable) return content;
  return (
    <button
      type="button"
      onClick={() => navigate(`/minutes/${event.meetingId}`)}
      className="block w-full text-left transition-colors hover:bg-surface-2"
    >
      {content}
    </button>
  );
};

// --- Recent projects (empty) ---------------------------------------------

const RecentProjectsEmpty = () => (
  <Card className="p-[22px]">
    <div className="mb-3.5">
      <span className="font-mono text-[10.5px] font-semibold uppercase tracking-[0.14em] text-muted-foreground-2">
        Recent projects
      </span>
    </div>
    <div className="flex flex-col items-center justify-center px-4 py-10 text-center">
      <div className="mb-3 grid h-10 w-10 place-items-center rounded-[10px] bg-accent-tint text-primary">
        <Lightbulb size={18} />
      </div>
      <p className="text-sm font-semibold text-ink">No projects yet</p>
      <p className="mt-1 text-[12.5px] text-muted-foreground">
        Projects ship in Phase 4. You'll be able to chat with Claude over
        project-scoped context — meetings, tickets, and files.
      </p>
    </div>
  </Card>
);
