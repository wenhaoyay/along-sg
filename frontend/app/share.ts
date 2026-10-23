import type { ResolvedLocation } from "./components/LocationField";

/* A plan as a link: where from, where to, what for, and how to weigh it.
 *
 * Coordinates, not place names, are what the planner sends, so they are what
 * the link carries; the names ride along so the fields read the same when the
 * link is opened. Nothing else - no result, no times - so a shared link always
 * plans afresh rather than replaying a stale answer. */

export type TripStyle = "balanced" | "faster" | "walking";

export type SharedTrip = {
  origin: ResolvedLocation;
  destination: ResolvedLocation;
  need: string;
  style: TripStyle;
};

const STYLES: TripStyle[] = ["balanced", "faster", "walking"];

function point(location: ResolvedLocation) {
  const { latitude, longitude } = location.coordinate;
  return `${latitude.toFixed(6)},${longitude.toFixed(6)}`;
}

export function tripQuery(trip: SharedTrip): string {
  const params = new URLSearchParams({
    from: point(trip.origin),
    fromName: trip.origin.label,
    to: point(trip.destination),
    toName: trip.destination.label,
    need: trip.need,
  });
  if (trip.style !== "balanced") params.set("style", trip.style);
  return `?${params.toString()}`;
}

function location(value: string | null, name: string | null): ResolvedLocation | null {
  if (!value) return null;
  const [latitude, longitude] = value.split(",").map(Number);
  // Singapore's bounding box, so a mangled link cannot plan from the sea.
  if (!(latitude > 1.1 && latitude < 1.5 && longitude > 103.5 && longitude < 104.1)) return null;
  const label = (name ?? "").trim().slice(0, 120) || "Shared place";
  return {
    label,
    coordinate: { latitude, longitude },
    entity_type: "shared",
    confirmed: true,
  };
}

export function readTrip(search: string): SharedTrip | null {
  const params = new URLSearchParams(search);
  const origin = location(params.get("from"), params.get("fromName"));
  const destination = location(params.get("to"), params.get("toName"));
  const need = (params.get("need") ?? "").trim().slice(0, 300);
  if (!origin || !destination || !need) return null;
  const style = params.get("style") as TripStyle | null;
  return {
    origin,
    destination,
    need,
    style: style && STYLES.includes(style) ? style : "balanced",
  };
}
