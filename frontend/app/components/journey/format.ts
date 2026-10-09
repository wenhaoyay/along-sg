import { type Business, type Stop, type Result } from "./types";

export function capitalise(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

export function businessLine(stop: Stop) {
  return stop.businesses.map((business) => business.display_name).join(" · ") || stop.display_name;
}

export function titleCase(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1).toLowerCase().replace(/_/g, " ");
}

export const HOURS_COPY: Record<string, string> = {
  open: "Listed open at arrival · hours may change",
  closed: "Listed closed at arrival · check before travelling",
  closing_soon: "May close before you finish",
  unknown: "Hours not confirmed · check before travelling",
};

export const HOURS_COPY_SHARED: Record<string, (subject: string) => string> = {
  open: (subject) => `Listed open at arrival for ${subject} · hours may change`,
  closed: (subject) => `Listed closed at arrival for ${subject} · check before travelling`,
  closing_soon: (subject) => `${capitalise(subject)} may close before you finish`,
  unknown: (subject) => `Hours not confirmed for ${subject} · check before travelling`,
};

/** One line per distinct hours state, not one per shop.
 *
 * Roughly four in five outlets publish no hours, so a two-errand mall stop
 * printed the same twenty-word caveat twice in a row. When every shop at a
 * stop shares a state, say it once - the shop names are already listed
 * directly above. Only a genuinely mixed stop needs them named. */
export function hoursNotes(
  businesses: Business[],
): Array<{ key: string; status: string; text: string }> {
  if (!businesses.length) return [];
  const statuses = businesses.map((business) => business.opening_status ?? "unknown");
  const distinct = new Set(statuses);

  if (distinct.size > 1) {
    return businesses.map((business, index) => ({
      key: `${business.display_name}-${index}`,
      status: statuses[index],
      text: `${business.display_name}: ${HOURS_COPY[statuses[index]] ?? HOURS_COPY.unknown}`,
    }));
  }

  const status = statuses[0];
  if (businesses.length === 1) {
    return [{ key: status, status, text: HOURS_COPY[status] ?? HOURS_COPY.unknown }];
  }
  const subject = businesses.length === 2 ? "both" : `all ${businesses.length}`;
  const shared = HOURS_COPY_SHARED[status] ?? HOURS_COPY_SHARED.unknown;
  return [{ key: status, status, text: shared(subject) }];
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

export function sgTime(value: string) {
  return new Intl.DateTimeFormat("en-SG", {
    timeZone: "Asia/Singapore",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

export function transferCopy(value: number) {
  if (!value) return "No extra transfers";
  return `+${value} extra transfer${value === 1 ? "" : "s"}`;
}
