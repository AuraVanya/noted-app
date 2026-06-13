import { FileText, Lightbulb, Mic, Users, Video } from "lucide-react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { useMeetings, type MeetingListItem } from "@/hooks/useMeetings";
import { formatLocalDateShort, formatLocalTime } from "@/lib/format";

export const Minutes = () => {
  const meetings = useMeetings();

  return (
    <div>
      <div className="mb-6">
        <h2 className="mb-1 text-2xl font-bold tracking-tight text-ink">
          Minutes
        </h2>
        <p className="text-sm text-muted-foreground">
          Past meeting minutes from Fireflies. Newest first.
        </p>
      </div>

      {meetings.isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : meetings.isError ? (
        <p className="text-sm text-destructive">
          Couldn't load meetings: {meetings.error.message}
        </p>
      ) : meetings.data && meetings.data.length === 0 ? (
        <EmptyState />
      ) : (
        <ul className="flex flex-col gap-2.5">
          {meetings.data?.map((m) => (
            <li key={m.id}>
              <MeetingCard meeting={m} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

const MeetingCard = ({ meeting }: { meeting: MeetingListItem }) => (
  <Link to={`/minutes/${meeting.id}`} className="block">
    <Card className="flex items-center gap-4 px-[18px] py-4 transition-all hover:-translate-y-px hover:border-border-strong hover:shadow-md">
      <div className="flex w-[90px] flex-none flex-col items-end leading-tight">
        <span className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground-2">
          {formatLocalDateShort(meeting.occurredAt)}
        </span>
        <span className="font-mono text-[13px] font-semibold text-ink">
          {formatLocalTime(meeting.occurredAt)}
        </span>
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="truncate text-[14.5px] font-semibold text-ink">
            {meeting.title}
          </span>
          <Badge variant="default">{meeting.seriesTitle}</Badge>
          {meeting.seriesHasAutoFile && (
            <span
              title="This series auto-files to a Project Context"
              className="inline-flex items-center gap-1 rounded-full bg-accent-tint-2 px-2 py-0.5 text-[10.5px] font-semibold text-primary"
            >
              <Lightbulb size={10} />
              Auto-file
            </span>
          )}
        </div>
        <div className="mt-1 flex items-center gap-3 text-[12px] text-muted-foreground">
          {meeting.attendeeCount > 0 && (
            <span className="inline-flex items-center gap-1">
              <Users size={12} />
              {meeting.attendeeCount}{" "}
              {meeting.attendeeCount === 1 ? "attendee" : "attendees"}
            </span>
          )}
        </div>
      </div>

      <div className="flex flex-none items-center gap-3 text-muted-foreground">
        {meeting.hasSummary && (
          <>
            <span className="inline-flex items-center gap-1 text-[11px]">
              <FileText size={14} />
              Summary
            </span>
            <span className="inline-flex items-center gap-1 text-[11px]">
              <Video size={14} />
              Recording
            </span>
          </>
        )}
        {meeting.hasTranscript && (
          <span className="inline-flex items-center gap-1 text-[11px]">
            <Mic size={14} />
            Transcript
          </span>
        )}
      </div>
    </Card>
  </Link>
);

const EmptyState = () => (
  <Card className="p-8 text-center">
    <FileText size={28} className="mx-auto mb-3 text-muted-foreground-2" />
    <p className="text-sm font-medium text-ink">No meetings yet</p>
    <p className="mt-1 text-xs text-muted-foreground">
      Once Fireflies drops a summary into your Drive folder and the sync runs,
      your past meetings will appear here.
    </p>
  </Card>
);
