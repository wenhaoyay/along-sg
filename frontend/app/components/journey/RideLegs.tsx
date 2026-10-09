"use client";

import { Bus, TrainFront } from "lucide-react";
import { lineColor } from "../../lineColors";
import { boardingKey, isBusStopCode } from "../../useBusArrivals";
import type { ArrivalEstimate, StopArrivals } from "../../useBusArrivals";
import { type Leg } from "./types";
import { titleCase } from "./format";

export const WALKING_MODES = new Set(["WALK", "BICYCLE", "SCOOTER"]);

/** The services you actually board on one leg of the journey.
 *
 * OneMap returns `routeShortName`, `routeLongName`, `agencyName` and
 * `intermediateStops` on every transit leg, and all of it was being discarded
 * - so a plan could say "37 minutes" without ever saying which train or bus to
 * get on, which is the one thing the traveller has to act on. */
export function RideLegs({
  legs,
  segment,
  arrivals = {},
}: {
  legs?: Leg[];
  segment: number;
  arrivals?: Record<string, StopArrivals>;
}) {
  const rides = (legs ?? []).filter(
    (leg) => leg.segment_index === segment && !WALKING_MODES.has(leg.mode.toUpperCase()),
  );
  if (!rides.length) return null;
  return (
    <>
      {rides.map((leg, index) => (
        <p
          className="ride-leg"
          key={`${segment}-${index}`}
          /* The official line colour, which the router was already returning
             and nobody was reading. Null for a bus, and for any line this
             table has not heard of - the accent then applies, because a wrong
             line colour is a confident claim about which train you are on. */
          style={
            {
              "--service-color":
                lineColor(leg.route_short_name, leg.route_long_name) ?? "var(--green)",
            } as React.CSSProperties
          }
        >
          {isRail(leg) ? (
            <TrainFront size={13} aria-hidden="true" />
          ) : (
            <Bus size={13} aria-hidden="true" />
          )}
          <span className="service">{serviceName(leg)}</span>
          <span className="ride-detail">{rideDetail(leg)}</span>
          <NextBuses leg={leg} arrivals={arrivals} />
        </p>
      ))}
    </>
  );
}

/* When the next buses on this service are due at the stop you board.
 *
 * Renders nothing unless there is something true to say - no skeleton, no
 * "loading", no dash. A timeline that was complete a moment ago should not
 * grow a hole while a request is in flight.
 *
 * The two states that do appear are deliberately different. A time LTA derived
 * from the bus's position is stated plainly; a time from the operator's
 * timetable is marked, because it is a different claim and this app does not
 * launder one into the other. */
export function NextBuses({ leg, arrivals }: { leg: Leg; arrivals: Record<string, StopArrivals> }) {
  const code = leg.from_stop_code;
  const service = leg.route_short_name?.trim();
  if (!isBusStopCode(code) || !service) return null;
  const stop = arrivals[boardingKey(code, service)];
  if (!stop) return null;
  const match = stop.services.find((item) => item.service_no === service);
  if (!match?.estimates.length) {
    /* Asked, and answered with nothing. Which of the two reasons it is comes
     * from the ingested timetable: LTA's advisement separates "no estimate
     * available" from "not in operation", and only the second is something the
     * traveller can act on. With no timetable held, `in_operation` is null and
     * the app declines to pick one. */
    if (stop.in_operation === false) {
      return (
        <span className="next-buses none" title={stop.operating_hours ?? undefined}>
          Not running now
        </span>
      );
    }
    return <span className="next-buses none">No live times</span>;
  }
  const shown = match.estimates.slice(0, 3);
  const scheduled = shown.every((estimate) => !estimate.live);
  return (
    <span
      className={`next-buses${scheduled ? " scheduled" : ""}`}
      title={
        scheduled
          ? "From the operator's timetable, not the bus's position"
          : `Live, checked ${new Date(stop.checked_at).toLocaleTimeString("en-SG", {
              hour: "numeric",
              minute: "2-digit",
            })}`
      }
    >
      {shown.map((estimate, index) => (
        <b key={index}>
          {/* Crowding sits beside the time, never on it. LTA sanctions
              colouring the timings themselves, but three differently coloured
              numbers in a row and no legend reads as urgency - amber for 8 min
              and red for 16 min looks like a claim about lateness. Only the bus
              you would actually catch carries the dot. */}
          {index === 0 && estimate.load && (
            <i className={loadClass(estimate.load)} aria-hidden="true" />
          )}
          {arrivalText(estimate)}
          {index === 0 && estimate.load && (
            <span className="sr-only">{`, ${loadLabel(estimate.load)}`}</span>
          )}
        </b>
      ))}
      {scheduled && <em>timetable</em>}
      {stop.source === "mock" && <em className="sample">sample</em>}
    </span>
  );
}

/** LTA's advisement is explicit: round down, and under a minute is arriving
 *  rather than "0 min". */
export function arrivalText(estimate: ArrivalEstimate) {
  return estimate.minutes <= 0 ? "Arr" : `${estimate.minutes} min`;
}

/** LTA's suggested scheme: seats green, standing amber, limited standing red. */
export function loadClass(load: ArrivalEstimate["load"]) {
  if (load === "SEA") return "load-seats";
  if (load === "SDA") return "load-standing";
  if (load === "LSD") return "load-full";
  return "";
}

/** The colour is decoration; this is the actual information. */
export function loadLabel(load: ArrivalEstimate["load"]) {
  if (load === "SEA") return "seats available";
  if (load === "SDA") return "standing room";
  if (load === "LSD") return "very full";
  return "";
}

export const RAIL_MODES = new Set([
  "SUBWAY",
  "RAIL",
  "TRAM",
  "METRO",
  "TRAIN",
  "LIGHT_RAIL",
  "FUNICULAR",
]);

export function isRail(leg: Leg) {
  return RAIL_MODES.has(leg.mode.toUpperCase());
}

export function serviceName(leg: Leg) {
  const short = leg.route_short_name?.trim();
  if (isRail(leg)) return short ? `${short} line` : "Train";
  if (short) return `Bus ${short}`;
  return leg.route_long_name?.trim() || titleCase(leg.mode);
}

export function rideDetail(leg: Leg) {
  const parts: string[] = [];
  if (leg.stop_count && leg.stop_count > 0) {
    parts.push(`${leg.stop_count} stop${leg.stop_count === 1 ? "" : "s"}`);
  }
  if (leg.duration_minutes >= 1) parts.push(`${Math.round(leg.duration_minutes)} min`);
  return parts.join(" · ");
}
