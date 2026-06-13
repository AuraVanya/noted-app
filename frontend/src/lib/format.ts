/**
 * Local TZ formatters used across Minutes, Calendar, and Home.
 * Source of truth: backend hands out UTC ISO strings; the browser does
 * the conversion using its own resolved timezone.
 */

const _date = new Intl.DateTimeFormat(undefined, {
  month: "short",
  day: "numeric",
  year: "numeric",
});

const _dateNoYear = new Intl.DateTimeFormat(undefined, {
  weekday: "short",
  month: "short",
  day: "numeric",
});

const _time = new Intl.DateTimeFormat(undefined, {
  hour: "numeric",
  minute: "2-digit",
  hour12: false,
});

const _dayOfWeek = new Intl.DateTimeFormat(undefined, { weekday: "short" });

export const formatLocalDate = (isoUtc: string): string =>
  _date.format(new Date(isoUtc));

export const formatLocalDateShort = (isoUtc: string): string =>
  _dateNoYear.format(new Date(isoUtc));

export const formatLocalTime = (isoUtc: string): string =>
  _time.format(new Date(isoUtc));

export const formatLocalDateTime = (isoUtc: string): string =>
  `${formatLocalDate(isoUtc)} · ${formatLocalTime(isoUtc)}`;

export const formatDayOfWeek = (isoUtc: string): string =>
  _dayOfWeek.format(new Date(isoUtc));

export const browserTimeZone = (): string =>
  Intl.DateTimeFormat().resolvedOptions().timeZone;
