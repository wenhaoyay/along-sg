import { type Result } from "./types";

export function capitalise(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

export function titleCase(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1).toLowerCase().replace(/_/g, " ");
}

export function metres(value: number) {
  return value >= 1000 ? `${(value / 1000).toFixed(1)} km` : `${Math.round(value)} m`;
}

export function clockTime(value: string) {
  return new Intl.DateTimeFormat("en-SG", {
    timeZone: "Asia/Singapore",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

/** "Sat 3 Oct" when the time is not today in Singapore, otherwise null. Every
 *  row used to carry "2 Oct" on a trip leaving in five minutes; a date only
 *  says something when it is not today. */
export function dayIfNotToday(value: string, now = new Date()) {
  const day = (date: Date) =>
    new Intl.DateTimeFormat("en-SG", {
      timeZone: "Asia/Singapore",
      weekday: "short",
      day: "numeric",
      month: "short",
    }).format(date);
  const label = day(new Date(value));
  return label === day(now) ? null : label;
}

/* Start and finish within a short walk of each other: "from home and back"
 * is a real trip, so it is labelled rather than refused. */
export function isRoundTrip(result: Result) {
  const a = result.origin.coordinate;
  const b = result.destination.coordinate;
  if (!a || !b) return false;
  const kmPerDegree = 111.32;
  const dx = (a.longitude - b.longitude) * kmPerDegree * Math.cos((a.latitude * Math.PI) / 180);
  const dy = (a.latitude - b.latitude) * kmPerDegree;
  return Math.hypot(dx, dy) < 0.3;
}

export function transferCopy(value: number) {
  if (!value) return "No extra transfers";
  return `+${value} extra transfer${value === 1 ? "" : "s"}`;
}
