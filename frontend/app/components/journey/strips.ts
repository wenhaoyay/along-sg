import { lineColor } from "../../lineColors";
import { type Leg, type Recommendation, type Result } from "./types";
import { isWalk, minutesBetween, shortStation } from "./steps";
import { serviceName } from "./RideLegs";

/* A journey as a bar on a time axis: each ride in its line's colour, walks
 * and waits in between, the time in shops as its own block.
 *
 * This is the comparison the app makes, drawn instead of described. The direct
 * trip is one bar; every option is another on the same scale, and how far it
 * runs past the direct trip's end is the added time the headline quotes - so
 * the reader can see why +2 min of travel still means +32 min later. */

export type PieceKind = "ride" | "walk" | "wait" | "stop";

export type Piece = {
  kind: PieceKind;
  start: number;
  end: number;
  color: string | null;
  code: string | null;
  title: string;
};

export type Strip = { pieces: Piece[]; total: number };

const MIN_PIECE = 0.25;

function piece(kind: PieceKind, start: number, end: number, title: string, leg?: Leg): Piece {
  return {
    kind,
    start,
    end,
    color: leg ? lineColor(leg.route_short_name, leg.route_long_name) : null,
    code: leg?.route_short_name?.trim() || null,
    title,
  };
}

function legTitle(leg: Leg) {
  const minutes = Math.max(1, Math.round(leg.duration_minutes));
  if (isWalk(leg)) return `Walk ${minutes} min`;
  const from = shortStation(leg.from_name);
  const to = shortStation(leg.to_name);
  return `${serviceName(leg)}${from && to ? ` · ${from} to ${to}` : ""} · ${minutes} min`;
}

/** Offsets from the journey's own departure when the router gave clock times;
 *  otherwise the durations laid end to end, with the stop allowance between
 *  segments. Either way the pieces add up to the journey's length. */
export function stripFromLegs(
  legs: Leg[],
  departure: string | null | undefined,
  dwellPerStop: number,
): Strip {
  const pieces: Piece[] = [];
  const timed = Boolean(departure) && legs.every((leg) => leg.departure_time && leg.arrival_time);
  let cursor = 0;
  let previous: Leg | null = null;

  for (const leg of legs) {
    const boundary = previous !== null && leg.segment_index !== previous.segment_index;
    let start: number;
    let end: number;
    if (timed) {
      start = minutesBetween(departure, leg.departure_time) ?? cursor;
      end = minutesBetween(departure, leg.arrival_time) ?? start + leg.duration_minutes;
    } else {
      start = cursor + (boundary ? dwellPerStop : 0);
      end = start + leg.duration_minutes;
    }
    if (start - cursor >= MIN_PIECE) {
      const gap = Math.round(start - cursor);
      pieces.push(
        boundary
          ? piece("stop", cursor, start, `About ${gap} min at the stop`)
          : piece("wait", cursor, start, `Waiting or changing, ${gap} min`),
      );
    }
    if (end - start >= MIN_PIECE)
      pieces.push(piece(isWalk(leg) ? "walk" : "ride", start, end, legTitle(leg), leg));
    cursor = Math.max(cursor, end);
    previous = leg;
  }
  return { pieces, total: cursor };
}

export function recommendationStrip(item: Recommendation): Strip {
  const dwellPerStop = item.stops.length
    ? item.detour_breakdown.dwell_minutes / item.stops.length
    : 0;
  if (item.legs?.length) {
    const strip = stripFromLegs(item.legs, item.departure_time, dwellPerStop);
    // A journey ending in a stop's dwell has no leg after it to close the gap.
    const total = Math.max(strip.total, item.total_duration_minutes);
    return { pieces: strip.pieces, total };
  }
  const travel = Math.max(0, item.total_duration_minutes - item.detour_breakdown.dwell_minutes);
  return {
    pieces: [
      piece("ride", 0, travel, `Travel ${Math.round(travel)} min`),
      piece("stop", travel, item.total_duration_minutes, "Time at your stops"),
    ],
    total: item.total_duration_minutes,
  };
}

export function directStrip(result: Result): Strip {
  const legs = result.baseline.legs ?? [];
  if (legs.length) {
    const strip = stripFromLegs(legs, result.baseline.departure_time, 0);
    return { pieces: strip.pieces, total: Math.max(strip.total, result.baseline.duration_minutes) };
  }
  const total = result.baseline.duration_minutes;
  return { pieces: [piece("ride", 0, total, `Direct ${Math.round(total)} min`)], total };
}
