import {
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
} from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { type CalendarEvent, useCalendarWeek } from "@/hooks/useCalendar";
import { formatLocalDate, formatLocalTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const HOUR_START = 6;            // 06:00 local
const HOUR_END = 22;             // 22:00 local
const HOUR_HEIGHT = 52;          // px, matches mockup .cal-hour height
const DAYS_IN_WEEK = 7;

// --- date helpers in local TZ --------------------------------------------

const startOfWeekMonday = (d: Date): Date => {
  const out = new Date(d);
  const dow = out.getDay(); // 0=Sun..6=Sat
  const diff = (dow + 6) % 7; // distance back to Mon
  out.setHours(0, 0, 0, 0);
  out.setDate(out.getDate() - diff);
  return out;
};

const addDays = (d: Date, n: number): Date => {
  const out = new Date(d);
  out.setDate(out.getDate() + n);
  return out;
};

const isSameLocalDay = (a: Date, b: Date): boolean =>
  a.getFullYear() === b.getFullYear() &&
  a.getMonth() === b.getMonth() &&
  a.getDate() === b.getDate();

const toYMD = (d: Date): string => {
  // YYYY-MM-DD in local time, what the API expects
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
};

const dayOfWeekShort = new Intl.DateTimeFormat(undefined, { weekday: "short" });
const monthShort = new Intl.DateTimeFormat(undefined, { month: "short" });

const rangeLabel = (start: Date, end: Date): string => {
  const sM = monthShort.format(start);
  const eM = monthShort.format(end);
  const sD = start.getDate();
  const eD = end.getDate();
  const y = end.getFullYear();
  return sM === eM
    ? `${sM} ${sD} – ${eD}, ${y}`
    : `${sM} ${sD} – ${eM} ${eD}, ${y}`;
};

// --- event positioning ---------------------------------------------------

interface Positioned {
  event: CalendarEvent;
  topPx: number;
  heightPx: number;
}

const positionEvent = (event: CalendarEvent): Positioned => {
  const start = new Date(event.start);
  const end = event.end
    ? new Date(event.end)
    : new Date(start.getTime() + 60 * 60 * 1000); // default 1h

  const startMin = start.getHours() * 60 + start.getMinutes();
  const endMin = end.getHours() * 60 + end.getMinutes();
  const visibleStart = Math.max(startMin, HOUR_START * 60);
  const visibleEnd = Math.min(endMin, HOUR_END * 60);

  const topPx = ((visibleStart - HOUR_START * 60) / 60) * HOUR_HEIGHT;
  const heightPx = Math.max(
    18,
    ((visibleEnd - visibleStart) / 60) * HOUR_HEIGHT,
  );
  return { event, topPx, heightPx };
};

// --- component -----------------------------------------------------------

export const Calendar = () => {
  const [weekStart, setWeekStart] = useState(() => startOfWeekMonday(new Date()));
  const [selected, setSelected] = useState<CalendarEvent | null>(null);

  const days = useMemo(
    () => Array.from({ length: DAYS_IN_WEEK }, (_, i) => addDays(weekStart, i)),
    [weekStart],
  );
  const weekEnd = days[DAYS_IN_WEEK - 1];
  const today = new Date();

  const week = useCalendarWeek(toYMD(weekStart));

  const eventsByDay = useMemo(() => {
    const buckets: Positioned[][] = days.map(() => []);
    for (const ev of week.data?.events ?? []) {
      const start = new Date(ev.start);
      for (let i = 0; i < days.length; i++) {
        if (isSameLocalDay(start, days[i])) {
          buckets[i].push(positionEvent(ev));
          break;
        }
      }
    }
    return buckets;
  }, [week.data, days]);

  return (
    <div>
      <div className="mb-6">
        <h2 className="mb-1 text-2xl font-bold tracking-tight text-ink">
          Calendar
        </h2>
        <p className="text-sm text-muted-foreground">
          Your week, synced from Google Calendar. Click a meeting for details.
        </p>
      </div>

      <Toolbar
        rangeText={rangeLabel(weekStart, weekEnd)}
        onPrev={() => setWeekStart(addDays(weekStart, -7))}
        onNext={() => setWeekStart(addDays(weekStart, 7))}
        onToday={() => setWeekStart(startOfWeekMonday(new Date()))}
      />

      {week.isError ? (
        <p className="mt-4 text-sm text-destructive">
          Couldn't load calendar: {week.error.message}
        </p>
      ) : (
        <div className="overflow-hidden rounded-[12px] border border-border bg-card shadow-sm">
          <HeaderRow days={days} today={today} />
          <div className="grid grid-cols-[54px_repeat(7,1fr)]">
            <TimeGutter />
            {days.map((day, i) => (
              <DayColumn
                key={day.toISOString()}
                day={day}
                isToday={isSameLocalDay(day, today)}
                positioned={eventsByDay[i]}
                onSelect={setSelected}
              />
            ))}
          </div>
        </div>
      )}

      <EventDialog
        event={selected}
        onOpenChange={(open) => !open && setSelected(null)}
      />
    </div>
  );
};

// --- subcomponents -------------------------------------------------------

const Toolbar = ({
  rangeText,
  onPrev,
  onNext,
  onToday,
}: {
  rangeText: string;
  onPrev: () => void;
  onNext: () => void;
  onToday: () => void;
}) => (
  <div className="mb-4 flex items-center gap-3.5">
    <div className="flex gap-1">
      <IconBtn aria="Previous week" onClick={onPrev}>
        <ChevronLeft size={16} />
      </IconBtn>
      <IconBtn aria="Next week" onClick={onNext}>
        <ChevronRight size={16} />
      </IconBtn>
    </div>
    <button
      onClick={onToday}
      className="rounded-md border border-border-strong bg-card px-2.5 py-1 text-[12px] font-semibold text-ink-2 hover:bg-surface-2"
    >
      Today
    </button>
    <span className="text-[15px] font-semibold tracking-tight text-ink">
      {rangeText}
    </span>
    <div className="ml-auto flex items-center gap-4 text-[11.5px] text-muted-foreground">
      <Legend swatch="bg-primary border-primary-hover" label="Past · summary ready" />
      <Legend
        swatch="bg-[hsl(244_60%_78%)] border-[hsl(244_50%_65%)]"
        label="Past · no summary"
      />
      <Legend
        swatch="border-primary border-[1.5px] border-dashed bg-accent-tint-2"
        label="Upcoming"
      />
    </div>
  </div>
);

const IconBtn = ({
  aria,
  children,
  onClick,
}: {
  aria: string;
  children: React.ReactNode;
  onClick: () => void;
}) => (
  <button
    type="button"
    aria-label={aria}
    title={aria}
    onClick={onClick}
    className="grid h-8 w-8 place-items-center rounded-md border border-border-strong bg-card text-ink-2 transition-colors hover:bg-surface-2"
  >
    {children}
  </button>
);

const Legend = ({ swatch, label }: { swatch: string; label: string }) => (
  <span className="inline-flex items-center gap-1.5">
    <span className={cn("h-2.5 w-2.5 rounded-[3px]", swatch)} />
    {label}
  </span>
);

const HeaderRow = ({ days, today }: { days: Date[]; today: Date }) => (
  <div className="grid grid-cols-[54px_repeat(7,1fr)] border-b border-border">
    <div className="border-r border-border" />
    {days.map((day) => {
      const isToday = isSameLocalDay(day, today);
      return (
        <div
          key={day.toISOString()}
          className="border-r border-border px-2 py-2.5 text-center last:border-r-0"
        >
          <div className="font-mono text-[10.5px] uppercase tracking-[0.1em] text-muted-foreground-2">
            {dayOfWeekShort.format(day)}
          </div>
          {isToday ? (
            <div className="mx-auto mt-[2px] inline-flex h-[30px] w-[30px] items-center justify-center rounded-full bg-primary text-[14px] font-semibold text-primary-foreground">
              {day.getDate()}
            </div>
          ) : (
            <div className="mt-0.5 text-[17px] font-semibold tracking-tight text-ink">
              {day.getDate()}
            </div>
          )}
        </div>
      );
    })}
  </div>
);

const TimeGutter = () => {
  const hours: number[] = [];
  for (let h = HOUR_START; h < HOUR_END; h++) hours.push(h);
  return (
    <div className="border-r border-border">
      {hours.map((h) => (
        <div
          key={h}
          className="h-[52px] border-b border-border px-1.5 pt-0.5 text-right font-mono text-[10px] text-muted-foreground-2 last:border-b-0"
        >
          {String(h).padStart(2, "0")}:00
        </div>
      ))}
    </div>
  );
};

const DayColumn = ({
  day,
  isToday,
  positioned,
  onSelect,
}: {
  day: Date;
  isToday: boolean;
  positioned: Positioned[];
  onSelect: (e: CalendarEvent) => void;
}) => {
  const hourCount = HOUR_END - HOUR_START;
  return (
    <div
      className={cn(
        "relative border-r border-border last:border-r-0",
        isToday && "bg-accent-tint-2",
      )}
    >
      {Array.from({ length: hourCount }).map((_, i) => (
        <div
          key={`${day.toISOString()}-${i}`}
          className="h-[52px] border-b border-border last:border-b-0"
        />
      ))}
      {positioned.map(({ event, topPx, heightPx }) => (
        <EventBlock
          key={event.id}
          event={event}
          topPx={topPx}
          heightPx={heightPx}
          onClick={() => onSelect(event)}
        />
      ))}
    </div>
  );
};

const EventBlock = ({
  event,
  topPx,
  heightPx,
  onClick,
}: {
  event: CalendarEvent;
  topPx: number;
  heightPx: number;
  onClick: () => void;
}) => {
  // Three visual states: past+summary (solid primary), past without summary
  // (lighter purple solid), upcoming (dashed outline).
  const variant: "ready" | "noSummary" | "upcoming" = event.isPast
    ? event.meetingId !== null
      ? "ready"
      : "noSummary"
    : "upcoming";

  const block = {
    ready: "border border-primary-hover bg-primary text-primary-foreground",
    noSummary:
      "border border-[hsl(244_50%_65%)] bg-[hsl(244_60%_78%)] text-white",
    upcoming:
      "border-[1.5px] border-dashed border-primary bg-accent-tint-2 text-primary",
  }[variant];

  const timeText = {
    ready: "text-white/80",
    noSummary: "text-white/85",
    upcoming: "text-primary/80",
  }[variant];

  return (
    <button
      type="button"
      onClick={onClick}
      style={{ top: topPx, height: heightPx }}
      className={cn(
        "absolute left-[5px] right-[5px] overflow-hidden rounded-[7px] px-2 py-1 text-left text-[11.5px] leading-tight transition-all hover:z-[5] hover:shadow-md",
        block,
      )}
    >
      <div className="truncate font-semibold">{event.title}</div>
      <div className={cn("font-mono text-[10px]", timeText)}>
        {formatLocalTime(event.start)}
      </div>
    </button>
  );
};

// --- dialog --------------------------------------------------------------

const EventDialog = ({
  event,
  onOpenChange,
}: {
  event: CalendarEvent | null;
  onOpenChange: (open: boolean) => void;
}) => {
  const navigate = useNavigate();
  if (!event) return null;

  const summaryReady = event.isPast && event.meetingId !== null;

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {summaryReady && (
              <CheckCircle2
                size={18}
                className="flex-none text-[hsl(141_63%_33%)]"
                aria-label="Summary ready"
              />
            )}
            <span>{event.title}</span>
          </DialogTitle>
          <DialogDescription className="font-mono text-[11.5px]">
            {formatLocalDate(event.start)} · {formatLocalTime(event.start)}
            {event.end && <> – {formatLocalTime(event.end)}</>}
          </DialogDescription>
        </DialogHeader>
        <div className="px-6 pb-6 text-[13.5px] text-ink-2">
          {event.attendeeCount > 0 && (
            <p className="mb-3 text-muted-foreground">
              {event.attendeeCount} attendees
            </p>
          )}
          {event.isPast ? (
            summaryReady ? (
              <>
                <p className="font-semibold text-ink">
                  The summary for this meeting is ready.
                </p>
                <p className="mt-1 text-muted-foreground">
                  Open the full view to read it.
                </p>
              </>
            ) : (
              <p className="text-muted-foreground">
                No summary is available for this meeting yet. Fireflies may
                still be processing it, or it wasn't recorded.
              </p>
            )
          ) : (
            <p className="text-muted-foreground">
              This meeting hasn't happened yet. Check back after it ends to read
              the summary.
            </p>
          )}
        </div>
        <DialogFooter>
          {summaryReady ? (
            <Button
              onClick={() => {
                onOpenChange(false);
                navigate(`/minutes/${event.meetingId}`);
              }}
            >
              Full view
              <ExternalLink size={13} />
            </Button>
          ) : (
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              Close
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
