"use client";

import { useMemo, useState } from "react";
import {
  ArrowLeft,
  ArrowUpRight,
  Check,
  Clock3,
  Footprints,
  Share2,
  TrainFront,
} from "lucide-react";
import { boardingIsImminent, boardingKey, isBusStopCode, useBusArrivals } from "../useBusArrivals";
import type { Boarding } from "../useBusArrivals";
import { type Recommendation, type Result } from "./journey/types";
import { rankValue, type RankKey } from "./journey/ranking";
import { metres, clockTime, transferCopy } from "./journey/format";
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
  /** The plan as a query string (see share.ts), or null when it cannot be
   *  shared - a browsed selection has no text to put in a link. */
  shareQuery?: string | null;
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
  shareQuery,
}: Props) {
  const primaryStop = recommendation.stops[0];

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
    <section className="recommendation" data-testid="recommendation-sheet">
      <button className="edit-journey" type="button" onClick={onEdit}>
        <ArrowLeft size={15} aria-hidden="true" />
        Edit journey
      </button>

      {/* The outcome's message ("We couldn't fit everything comfortably")
        and a "Why?" behind the label said again what the label and the
        sentence under the figures say, and vaguely. The server's sentence
        names the reason ("No pharmacy on the way is open..."). */}
      <div className="result-heading">
        <span className="quality-label">
          <Check size={13} aria-hidden="true" />
          {sentenceCase(recommendation.quality_label)}
        </span>
        <h1 tabIndex={-1}>{primaryStop?.display_name ?? "Your best stop"}</h1>
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
      <p className="impact-caption">{impactCaption(recommendation)}</p>
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
      />

      {/* Named for screen readers and anything reading the page's outline;
        on screen the A-to-B timeline needs no heading. */}
      <h2 className="sr-only">Your plan</h2>
      <Timeline
        recommendation={recommendation}
        originName={originLabel ?? result.origin.label}
        destinationName={destinationLabel ?? result.destination.label}
        arrivals={arrivals}
        activeStop={activeStop}
        onStopSelect={onStopSelect}
      />
      {recommendation.time_dependent === false && (
        <p className="precision-note">Times are estimates, not a timetable.</p>
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
      {shareQuery && <ShareButton query={shareQuery} />}
    </section>
  );
}

function sentenceCase(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1).toLowerCase();
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

/* The plan as a link (see share.ts): the phone's share sheet where there is
 * one, the clipboard otherwise. */
function ShareButton({ query }: { query: string }) {
  const [copied, setCopied] = useState(false);
  async function share() {
    const url = `${window.location.origin}${window.location.pathname}${query}`;
    try {
      if (navigator.share) {
        await navigator.share({ title: "Along: errands on the way", url });
        return;
      }
      await navigator.clipboard.writeText(url);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2500);
    } catch {
      // Dismissing the share sheet is not an error worth showing.
    }
  }
  return (
    <>
      <button className="share-plan" type="button" onClick={share}>
        <Share2 size={16} aria-hidden="true" />
        Share this plan
      </button>
      <p className="share-copied" role="status">
        {copied ? "Link copied" : ""}
      </p>
    </>
  );
}
