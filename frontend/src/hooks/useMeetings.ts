import { useQuery } from "@tanstack/react-query";

import { ApiError, api } from "@/lib/api";

export interface Attendee {
  email: string;
  displayName: string;
}

export interface MeetingListItem {
  id: number;
  title: string;
  seriesId: number;
  seriesTitle: string;
  occurredAt: string;
  attendees: Attendee[];
  attendeeCount: number;
  hasSummary: boolean;
  hasTranscript: boolean;
  seriesHasAutoFile: boolean;
}

export interface MeetingDetail {
  id: number;
  title: string;
  seriesId: number;
  seriesTitle: string;
  occurredAt: string;
  attendees: Attendee[];
  summary: {
    signedUrl: string;
  } | null;
  transcript: {
    signedUrl: string;
  } | null;
}

export const useMeetings = () =>
  useQuery<MeetingListItem[], ApiError>({
    queryKey: ["meetings"],
    queryFn: () => api<MeetingListItem[]>("/api/meetings"),
  });

export const useMeeting = (id: number | undefined) =>
  useQuery<MeetingDetail, ApiError>({
    queryKey: ["meeting", id],
    queryFn: () => api<MeetingDetail>(`/api/meetings/${id}`),
    enabled: id !== undefined && id > 0,
  });
