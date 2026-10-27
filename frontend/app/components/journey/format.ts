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

export function transferCopy(value: number) {
  if (!value) return "No extra changes";
  return `+${value} extra change${value === 1 ? "" : "s"}`;
}
