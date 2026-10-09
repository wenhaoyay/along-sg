import { type Leg, type Recommendation, type Stop } from "./types";
import { WALKING_MODES } from "./RideLegs";

/* One journey as the traveller lives it: leave, walk, ride, change, shop,
 * ride, arrive - with a clock time wherever the router gave one.
 *
 * The old panel printed "A · 4:06", one stop's arrival and the final arrival,
 * and left the reader to work out where the other hour went. Every figure the
 * timeline shows is now one of the router's own times or the gap between two
 * of them, so the arithmetic on screen always closes. */

export type TimelinePlace = {
  kind: "place";
  role: "origin" | "stop" | "destination";
  name: string;
  time: string | null;
  stop?: Stop;
  stopIndex?: number;
  /** Time at the stop, from arrival to the next leg's departure. */
  dwellMinutes?: number | null;
  leaveTime?: string | null;
};

export type TimelineWalk = {
  kind: "walk";
  minutes: number;
  metres: number;
  time: string | null;
};

export type TimelineRide = {
  kind: "ride";
  leg: Leg;
  /** Where you changed onto this ride, when it follows another one. */
  changeAt: string | null;
  time: string | null;
};

export type TimelineItem = TimelinePlace | TimelineWalk | TimelineRide;

// Below this a walk is crossing a concourse, not a step of the plan.
const MIN_WALK_MINUTES = 0.5;

export function isWalk(leg: Leg) {
  return WALKING_MODES.has(leg.mode.toUpperCase());
}

/** "Punggol MRT Station" reads as "Punggol" in a list that already says it is
 *  on the NE line. */
export function shortStation(name: string | null | undefined) {
  return (name ?? "")
    .replace(/\s+(MRT|LRT)(\s+Station)?$/i, "")
    .replace(/\s+Station$/i, "")
    .trim();
}

export function minutesBetween(start?: string | null, end?: string | null): number | null {
  if (!start || !end) return null;
  const value = (Date.parse(end) - Date.parse(start)) / 60_000;
  return Number.isFinite(value) ? value : null;
}

/** The legs of one routed segment: 0 is the start to the first stop, and the
 *  last runs from the last stop to the destination. */
export function segmentLegs(legs: Leg[] | undefined, segment: number) {
  return (legs ?? []).filter((leg) => leg.segment_index === segment);
}

export function buildTimeline(
  recommendation: Recommendation,
  originName: string,
  destinationName: string,
): TimelineItem[] {
  const items: TimelineItem[] = [
    {
      kind: "place",
      role: "origin",
      name: originName,
      time: recommendation.departure_time ?? null,
    },
  ];
  const stops = recommendation.stops;
  for (let segment = 0; segment <= stops.length; segment += 1) {
    let previousRide: Leg | null = null;
    for (const leg of segmentLegs(recommendation.legs, segment)) {
      if (isWalk(leg)) {
        const last = items[items.length - 1];
        // The router can split one walk at a building entrance; it is one walk.
        if (last.kind === "walk") {
          last.minutes += leg.duration_minutes;
          last.metres += leg.distance_m;
        } else {
          items.push({
            kind: "walk",
            minutes: leg.duration_minutes,
            metres: leg.distance_m,
            time: leg.departure_time ?? null,
          });
        }
        continue;
      }
      items.push({
        kind: "ride",
        leg,
        changeAt: previousRide ? shortStation(leg.from_name ?? previousRide.to_name) : null,
        time: leg.departure_time ?? null,
      });
      previousRide = leg;
    }

    if (segment < stops.length) {
      const stop = stops[segment];
      const arrived = stop.arrival_time ?? lastArrival(recommendation.legs, segment);
      const leave = segmentLegs(recommendation.legs, segment + 1)[0]?.departure_time ?? null;
      items.push({
        kind: "place",
        role: "stop",
        name: stop.display_name,
        time: arrived,
        stop,
        stopIndex: segment,
        // Without timestamps, trust this stop's allowance from the optimiser.
        // Older/stubbed responses without it should not invent an even split.
        dwellMinutes: minutesBetween(arrived, leave) ?? (stop.dwell_minutes ?? null),
        leaveTime: leave,
      });
    }
  }

  items.push({
    kind: "place",
    role: "destination",
    name: destinationName,
    time: recommendation.arrival_time ?? null,
  });
  return items.filter((item) => item.kind !== "walk" || item.minutes >= MIN_WALK_MINUTES);
}

function lastArrival(legs: Leg[] | undefined, segment: number) {
  const inSegment = segmentLegs(legs, segment);
  return inSegment[inSegment.length - 1]?.arrival_time ?? null;
}
