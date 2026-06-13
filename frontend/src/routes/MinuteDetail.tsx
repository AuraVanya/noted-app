import { ArrowLeft, ExternalLink, Users } from "lucide-react";
import { Link, useParams } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { useMeeting } from "@/hooks/useMeetings";
import { formatLocalDate, formatLocalTime } from "@/lib/format";

export const MinuteDetail = () => {
  const { id } = useParams<{ id: string }>();
  const meetingId = id ? Number(id) : undefined;
  const meeting = useMeeting(meetingId);

  return (
    <div>
      <Link
        to="/minutes"
        className="mb-6 inline-flex items-center gap-1.5 text-[12.5px] font-medium text-muted-foreground transition-colors hover:text-ink"
      >
        <ArrowLeft size={14} />
        Back to Minutes
      </Link>

      {meeting.isLoading ? (
        <p className="text-sm text-muted-foreground">Loading summary…</p>
      ) : meeting.isError ? (
        <p className="text-sm text-destructive">
          Couldn't load meeting: {meeting.error.message}
        </p>
      ) : meeting.data ? (
        <Loaded meeting={meeting.data} />
      ) : null}
    </div>
  );
};

const Loaded = ({
  meeting,
}: {
  meeting: NonNullable<ReturnType<typeof useMeeting>["data"]>;
}) => {
  const { title, seriesTitle, occurredAt, attendees, summary, transcript } =
    meeting;
  return (
    <>
      <div className="mb-6">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <Badge variant="default">{seriesTitle}</Badge>
          <span className="font-mono text-[11.5px] text-muted-foreground">
            {formatLocalDate(occurredAt)} · {formatLocalTime(occurredAt)}
          </span>
        </div>
        <h2 className="text-2xl font-bold tracking-tight text-ink">{title}</h2>

        {attendees.length > 0 && (
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1.5 text-[12px] text-muted-foreground">
              <Users size={13} />
              {attendees.length} attendees
            </span>
            <div className="flex flex-wrap gap-1.5">
              {attendees.slice(0, 12).map((a) => (
                <Badge key={a.email} variant="muted">
                  {a.displayName}
                </Badge>
              ))}
              {attendees.length > 12 && (
                <Badge variant="muted">+{attendees.length - 12} more</Badge>
              )}
            </div>
          </div>
        )}

        {transcript?.signedUrl && (
          <div className="mt-5">
            <a
              href={transcript.signedUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 text-[12.5px] font-semibold text-primary hover:underline"
            >
              View full transcript
              <ExternalLink size={13} />
            </a>
          </div>
        )}
      </div>

      <Card className="overflow-hidden">
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <span className="font-mono text-[10.5px] font-semibold uppercase tracking-[0.14em] text-muted-foreground-2">
            Summary
          </span>
          {summary?.signedUrl && (
            <a
              href={summary.signedUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-[11.5px] font-semibold text-primary hover:underline"
            >
              Open in new tab
              <ExternalLink size={12} />
            </a>
          )}
        </div>
        {summary?.signedUrl ? (
          <iframe
            src={summary.signedUrl}
            title="Meeting summary PDF"
            className="block h-[78vh] w-full border-0 bg-card"
          />
        ) : (
          <div className="p-7 text-sm text-muted-foreground">
            No summary file is available for this meeting yet.
          </div>
        )}
      </Card>
    </>
  );
};
