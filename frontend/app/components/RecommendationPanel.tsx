"use client";

import { useMemo } from "react";
import {
  ArrowLeft,
  ArrowUpRight,
  Check,
  ChevronDown,
  Clock3,
  Footprints,
  TrainFront,
} from "lucide-react";
import { boardingIsImminent, boardingKey, isBusStopCode, useBusArrivals } from "../useBusArrivals";
import type { Boarding } from "../useBusArrivals";
import { type Recommendation, type Result } from "./journey/types";
import { rankNote, comparedSummary, rankValue, type RankKey } from "./journey/ranking";
import { metres, clockTime, isRoundTrip, transferCopy } from "./journey/format";
import { laterMinutes, shopMinutes, signed, travelMinutes } from "./journey/figures";
import { WALKING_MODES, isRail } from "./journey/RideLegs";
import { DetourDiagram } from "./journey/DetourDiagram";
import { Timeline } from "./journey/Timeline";

export type { Business, Leg, Recommendation, Result, Stop } from "./journey/types";
export {
  RANK_LABELS,
  deduplicatedAlternatives,
  rankRoutedOptions,
  rankValue,
  tradeoffCopy,
  type RankKey,
} from "./journey/ranking";

type Props = {
  recommendation: Recommendation;
  result: Result;
  alternatives: Array<[string, Recommendation]>;
  selectedKey: string;
  onSelect: (key: string) => void;
  onEdit: () => void;
  activeStop?: number | null;
  onStopSelect?: (index: number) => void;
  /* The request is sent as coordinates, so the API echoes back a
   * coordinate-derived label - the timeline read "A · 1.40578, 103.90290".
   * The client already resolved a real name for each endpoint; prefer it. */
  originLabel?: string;
  destinationLabel?: string;
  /** Routed, not volunteered, and selectable: [key, option] so a click can
   *  promote one straight into the plan. */
  compared?: Array<[string, Recommendation]>;
  onComparedHover?: (key: string | null) => void;
  rankBy: RankKey;
  onRankChange: (rank: RankKey) => void;
  // Required rather than defaulting to the frontend origin: deployments may
  // serve Next.js and FastAPI from different hosts.
  apiBase: string;
};

export function RecommendationPanel({
  recommendation,
  result,
  alternatives,
  compared = [],
  onComparedHover,
  rankBy,
  onRankChange,
  apiBase,
  selectedKey,
  onSelect,
  onEdit,
  activeStop,
  onStopSelect,
  originLabel,
  destinationLabel,
}: Props) {
  const primaryStop = recommendation.stops[0];
  const otherOptions = alternatives.filter(([key]) => key !== selectedKey);
  // Everything routed, the plan on screen included - the number the ranking
  // note quotes has to be the size of the set being reordered.
  const routedCount = otherOptions.length + compared.length + 1;
  const roundTrip = isRoundTrip(result);

  /* Offered alternatives and compared candidates were two collapsed lists
   * under the Navigate button, where nobody opened them - and the comparison
   * is the product. They are one set of rows in the diagram now, in the order
   * the sort control asks for.
   *
   * "Best overall" is the app's own order, not a sort by score: the options
   * it offers come first, as it ranked them, then the ones it routed and
   * passed over. Sorting the union by `inconvenience_score` put an "easier
   * alternative" (a 7-Eleven standing in for a supermarket, 15 minutes less in
   * shops) above the exact match the app had actually picked. */
  const rows = useMemo(() => {
    const byKey = new Map<string, Recommendation>([[selectedKey, recommendation]]);
    for (const [key, item] of [...alternatives, ...compared])
      if (!byKey.has(key)) byKey.set(key, item);
    const offeredOrder = new Map(alternatives.map(([key], index) => [key, index]));
    const order = (key: string, item: Recommendation) =>
      rankBy === "recommended"
        ? (offeredOrder.get(key) ?? 1_000 + rankValue(item, rankBy))
        : rankValue(item, rankBy);
    return [...byKey.entries()].sort(
      ([firstKey, first], [secondKey, second]) => order(firstKey, first) - order(secondKey, second),
    );
  }, [selectedKey, recommendation, alternatives, compared, rankBy]);
  const note = [
    compared.length
      ? comparedSummary(compared, recommendation, otherOptions)
      : rankNote("recommended", routedCount),
    rankBy !== "recommended" ? rankNote(rankBy, routedCount) : "",
  ]
    .filter(Boolean)
    .join(" ");

  /* Only the bus legs of the plan on screen, and only while boarding is close
   * enough for "next in 4 min" to be about the bus you will actually catch. */
  const boardings = useMemo<Boarding[]>(() => {
    const seen = new Set<string>();
    const wanted: Boarding[] = [];
    for (const leg of recommendation.legs ?? []) {
      const service = leg.route_short_name?.trim();
      if (
        isRail(leg) ||
        WALKING_MODES.has(leg.mode.toUpperCase()) ||
        !service ||
        !isBusStopCode(leg.from_stop_code) ||
        !boardingIsImminent(leg.departure_time)
      ) {
        continue;
      }
      const key = boardingKey(leg.from_stop_code, service);
      if (seen.has(key)) continue;
      seen.add(key);
      wanted.push({ stopCode: leg.from_stop_code, service });
    }
    return wanted;
  }, [recommendation]);
  const arrivals = useBusArrivals(apiBase, boardings);

  return (
    <section className="recommendation" aria-live="polite" data-testid="recommendation-sheet">
      <button className="edit-journey" type="button" onClick={onEdit}>
        <ArrowLeft size={15} aria-hidden="true" />
        Edit journey
      </button>

      {result.message && <p className="result-context">{result.message}</p>}

      <div className="result-heading">
        <details className="quality-note">
          <summary className="quality-label">
            <Check size={13} aria-hidden="true" />
            {sentenceCase(recommendation.quality_label)}
            <span className="quality-why">Why?</span>
          </summary>
          <p>{qualityExplanation(recommendation, routedCount)}</p>
        </details>
        <h1>{primaryStop?.display_name ?? "Your best stop"}</h1>
        {primaryStop && primaryStop.location_context !== primaryStop.display_name && (
          <p>{primaryStop.location_context}</p>
        )}
      </div>

      {/* Two figures, both in plain sight. Extra travel leads because it is
        what the choice changes; the time in shops is about the same wherever
        the errands are done. A single "+32 min" headline hid that the pick
        cost 2 minutes of travel, and an earlier travel-only headline hid the
        30 minutes in shops - so neither is small print any more. */}
      <div className="result-impact">
        <strong>
          {signed(travelMinutes(recommendation))}
          <small> min</small>
          <em>extra travel</em>
        </strong>
        <div>
          {recommendation.arrival_time && (
            <span className="result-arrival">
              <Clock3 size={16} aria-hidden="true" />
              arrive {clockTime(recommendation.arrival_time)}
            </span>
          )}
          <span>
            <Footprints size={16} aria-hidden="true" />+
            {metres(recommendation.incremental_walking_distance_m)} walking
          </span>
          <span>
            <TrainFront size={16} aria-hidden="true" />
            {transferCopy(recommendation.incremental_transfers)}
          </span>
        </div>
      </div>
      <p className="impact-caption">
        {impactCaption(recommendation)}
        {roundTrip && " A round trip: you start and finish at the same place."}
      </p>
      {/* The one sentence that explains the pick, written by the server from
        the options it actually routed, so it cannot claim a win the list
        below contradicts. */}
      <p className="why-brief">
        {recommendation.why_this_wins || relationshipCopy(recommendation)}
      </p>

      <DetourDiagram
        result={result}
        rows={rows}
        selectedKey={selectedKey}
        selected={recommendation}
        onSelect={onSelect}
        onHover={onComparedHover}
        rankBy={rankBy}
        onRankChange={onRankChange}
        note={note}
      />

      <h2 className="section-title">Your plan</h2>
      <Timeline
        recommendation={recommendation}
        originName={originLabel ?? result.origin.label}
        destinationName={destinationLabel ?? result.destination.label}
        arrivals={arrivals}
        activeStop={activeStop}
        onStopSelect={onStopSelect}
      />
      {recommendation.time_dependent === false && (
        <p className="precision-note">
          Departure-time routing is not verified for this provider. Stop arrival times are
          unavailable; this comparison is not a timetable promise.
        </p>
      )}

      {primaryStop?.navigation_ready && (
        <nav className="handoff" aria-label="Open each part in Google Maps">
          {/* Google Maps cannot take a stop on a public-transport route, so
            the plan is handed over one leg at a time rather than losing
            everything after the first stop. */}
          {handoffLegs(result, recommendation, originLabel, destinationLabel).map((leg, index) => (
            <a
              key={index}
              className={index === 0 ? "navigate-button" : "navigate-button secondary"}
              href={leg.href}
              target="_blank"
              rel="noopener noreferrer"
            >
              <span>{leg.label}</span>
              <ArrowUpRight size={18} aria-hidden="true" />
            </a>
          ))}
        </nav>
      )}

      <details className="result-disclosure why-disclosure">
        <summary>
          <span>How the {Math.round(laterMinutes(recommendation))} minutes add up</span>
          <ChevronDown size={18} aria-hidden="true" />
        </summary>
        <div className="disclosure-body">
          <dl className="breakdown-list">
            <div>
              <dt>Extra travel</dt>
              <dd>{signed(travelMinutes(recommendation))} min</dd>
            </div>
            {recommendation.detour_breakdown.dwell_allowances.map((item) => (
              <div key={item.label}>
                <dt>{shortDwellLabel(item.label)}</dt>
                <dd>~{Math.round(item.minutes)} min</dd>
              </div>
            ))}
            <div className="total">
              <dt>Later than going direct</dt>
              <dd>{signed(laterMinutes(recommendation))} min</dd>
            </div>
          </dl>
          <p className="precision-note">
            <Clock3 size={13} aria-hidden="true" />
            {recommendation.detour_breakdown.precision_note}
          </p>
        </div>
      </details>
    </section>
  );
}

function sentenceCase(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1).toLowerCase();
}

/* "EXACT MATCH" above the stop name raised the question of what had been
 * matched, and nothing answered it. The label stays; tapping it says what it
 * means, in the terms the ranking used. */
function qualityExplanation(item: Recommendation, routed: number) {
  const scope = routed > 1 ? `the ${routed} options we routed` : "the options we routed";
  switch (item.match_classification) {
    case "best_available":
      return `Nothing fitted every preference, so this is the closest of ${scope}.`;
    case "closest_exact":
      return "It matches what you asked for, and is just above the detour you prefer.";
    case "exceeds_limit":
      return "It is over the limit you set. Nothing came in under it.";
    case "exact_match":
      return `It has the brand you prefer, and the best mix of extra travel, walking and changes of ${scope} that do.`;
    case "without_preferred_brand":
      return "Nothing with your preferred brand came out ahead, so this one does not have it.";
    case "substitute":
      return "It uses a similar kind of shop instead of the one you asked for.";
    case "partial_option":
      return "It covers only part of your request.";
    default:
      return `It has the best mix of extra travel, walking and changes of ${scope}, weighed with how sure we are of each place.`;
  }
}

function impactCaption(item: Recommendation) {
  const shops = Math.round(shopMinutes(item));
  const later = Math.round(laterMinutes(item));
  if (shops < 1) return `${later} min later than going direct.`;
  return `${later} min later than going direct, including about ${shops} min in shops.`;
}

type Handoff = { label: string; href: string };

function mapsLink(
  from: { latitude: number; longitude: number } | undefined,
  to: { latitude: number; longitude: number },
) {
  const origin = from ? `&origin=${from.latitude},${from.longitude}` : "";
  return `https://www.google.com/maps/dir/?api=1${origin}&destination=${to.latitude},${to.longitude}&travelmode=transit`;
}

function handoffLegs(
  result: Result,
  item: Recommendation,
  originLabel?: string,
  destinationLabel?: string,
): Handoff[] {
  const points = [
    { name: originLabel ?? result.origin.label, coordinate: result.origin.coordinate },
    ...item.stops.map((stop) => ({ name: stop.display_name, coordinate: stop.coordinate })),
    {
      name: destinationLabel ?? result.destination.label,
      coordinate: result.destination.coordinate,
    },
  ];
  const legs: Handoff[] = [];
  for (let index = 1; index < points.length; index += 1) {
    const to = points[index].coordinate;
    if (!to) continue;
    const label =
      index === 1 ? `Directions to ${points[index].name}` : `Then on to ${points[index].name}`;
    legs.push({ label, href: mapsLink(points[index - 1].coordinate ?? undefined, to) });
  }
  return legs;
}

function shortDwellLabel(label: string) {
  return label.replace(/^Estimated /i, "").replace(/ stop$/i, " stop");
}

function relationshipCopy(item: Recommendation) {
  if (item.match_classification === "partial_option")
    return "This option covers only part of your request. Edit your journey to change the remaining errand.";
  const relationship =
    {
      same_mall: "Both errands are together in one mall along your route.",
      same_place: "Both errands are handled in one place.",
      same_transport_hub: "Both stops are within the same station area.",
      nearby_separate_stores: "The shops are close together, keeping the detour compact.",
      separate_stops: "This is the least disruptive order for the two stops.",
      single_stop: "One errand stop between your starting point and destination.",
    }[item.stop_relationship] ?? "This option stays close to your existing journey.";
  if (item.match_classification === "best_available")
    return `${relationship} It takes longer than usual.`;
  if (item.match_classification === "closest_exact")
    return `${relationship} It is just above your preference.`;
  if (item.match_classification === "exceeds_limit")
    return `${relationship} It exceeds the limit you set.`;
  if (item.match_classification === "substitute")
    return `${relationship} It uses a similar kind of shop instead.`;
  return relationship;
}
