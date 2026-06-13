import { useQuery } from "@tanstack/react-query";

import { ApiError, api } from "@/lib/api";
import { browserTimeZone } from "@/lib/format";

export interface CalendarEvent {
  id: string;
  title: string;
  start: string; // ISO UTC
  end: string | null; // ISO UTC
  isPast: boolean;
  meetingId: number | null; // present only if a synced meeting with a summary
  attendeeCount: number;
}

export interface WeekResponse {
  start: string;
  end: string;
  events: CalendarEvent[];
}

export interface TodayResponse {
  date: string;
  events: CalendarEvent[];
}

/** start = YYYY-MM-DD, the Monday of the week to fetch (in user's TZ). */
export const useCalendarWeek = (start: string) =>
  useQuery<WeekResponse, ApiError>({
    queryKey: ["calendar", "week", start],
    queryFn: () =>
      api<WeekResponse>(
        `/api/calendar/week?start=${start}&tz=${encodeURIComponent(browserTimeZone())}`,
      ),
  });

export const useCalendarToday = () =>
  useQuery<TodayResponse, ApiError>({
    queryKey: ["calendar", "today"],
    queryFn: () =>
      api<TodayResponse>(
        `/api/calendar/today?tz=${encodeURIComponent(browserTimeZone())}`,
      ),
  });
