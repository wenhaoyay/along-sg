"use client";

import { useMemo } from "react";
import {
  ArrowRight,
  Check,
  ChevronDown,
  Clock3,
  Footprints,
  Navigation,
  Route,
  TrainFront,
} from "lucide-react";
import { boardingIsImminent, boardingKey, isBusStopCode, useBusArrivals } from "../useBusArrivals";
import type { Boarding } from "../useBusArrivals";
import PlaceMark from "./PlaceMark";
import { type Stop, type Recommendation, type Result } from "./journey/types";
import {
  RANK_LABELS,
  rankNote,
  comparedDetail,
  comparedSummary,
  tradeoffCopy,
  type RankKey,
} from "./journey/ranking";
import {
  businessLine,
  hoursNotes,
  metres,
  clockTime,
  isRoundTrip,
  sgTime,
  transferCopy,
} from "./journey/format";
import { WALKING_MODES, RideLegs, isRail } from "./journey/RideLegs";

export type { Business, Leg, Recommendation, Result, Stop } from "./journey/types";
export {
  RANK_LABELS,
  deduplicatedAlternatives,
  rankRoutedOptions,
  rankValue,
  tradeoffCopy,
  type RankKey,
} from "./journey/ranking";
export { hoursNotes } from "./journey/format";

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
        <ArrowRight size={15} aria-hidden="true" />
        Edit journey
      </button>

      {result.message && <p className="result-context">{result.message}</p>}

      <div className="result-heading">
        <span className="quality-label">
          <Check size={13} aria-hidden="true" />
          {recommendation.quality_label}
        </span>
        <h1>{primaryStop?.display_name ?? "Your best stop"}</h1>
        {primaryStop && primaryStop.location_context !== primaryStop.display_name && (
          <p>{primaryStop.location_context}</p>
        )}
      </div>

      {/* The headline is what the traveller lives with: how much later they
        arrive than going direct, and when. Extra travel alone (+6 min) read
        as the whole cost while the ~30 min in shops sat in small print; it
        stays in the caption, since it is what differs between options. */}
      <div className="result-impact">
        <strong>
          +{Math.round(recommendation.incremental_detour_minutes)}
          <small> min</small>
          <em>
            {recommendation.arrival_time
              ? `arrive ${clockTime(recommendation.arrival_time)}`
              : "later than going direct"}
          </em>
        </strong>
        <div>
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

      <p className="trip-comparison">
        Direct <strong>{Math.round(result.baseline.duration_minutes)} min</strong>
        <ArrowRight size={14} aria-hidden="true" />
        With stops <strong>{Math.round(recommendation.total_duration_minutes)} min</strong>
      </p>
      <p className="impact-caption">
        {Math.round(recommendation.detour_breakdown.dwell_minutes) >= 1
          ? `${Math.round(recommendation.detour_breakdown.extra_transport_minutes)} min extra travel + ~${Math.round(recommendation.detour_breakdown.dwell_minutes)} min at your stops.`
          : `${Math.round(recommendation.detour_breakdown.extra_transport_minutes)} min extra travel.`}
        {roundTrip && " A round trip: you start and finish at the same place."}
      </p>

      <div className="stop-summary journey-timeline" aria-label="Errand stops">
        <p className="timeline-endpoint">
          A · {originLabel ?? result.origin.label}
          {recommendation.departure_time ? ` · ${sgTime(recommendation.departure_time)}` : ""}
        </p>
        {recommendation.stops.map((stop, stopIndex) => (
          <div key={`segment-${stopIndex}`}>
            <RideLegs arrivals={arrivals} legs={recommendation.legs} segment={stopIndex} />
            <div
              className={`stop-summary-row ${activeStop === stopIndex ? "selected-stop-card" : ""}`}
            >
              <button
                type="button"
                className="stop-number"
                aria-label={`Highlight stop ${stopIndex + 1}: ${stop.display_name}`}
                aria-pressed={activeStop === stopIndex}
                onClick={() => onStopSelect?.(stopIndex)}
              >
                {recommendation.stops.length > 1 ? (
                  stopIndex + 1
                ) : (
                  <Route size={15} aria-hidden="true" />
                )}
              </button>
              <div>
                {/* A single-shop stop is often named after the shop, so printing
              both gave "7-Eleven / 7-Eleven". Show the hub name only when it
              adds something. */}
                {recommendation.stops.length > 1 && stop.display_name !== businessLine(stop) && (
                  <strong>{stop.display_name}</strong>
                )}
                <p className="business-line">
                  {stop.businesses.length > 0 && (
                    <span className="place-marks">
                      {stop.businesses.slice(0, 3).map((business, index) => (
                        <PlaceMark
                          key={`${business.display_name}-${index}`}
                          logoUrl={business.logo_url}
                          categoryLabels={business.category_labels}
                          name={business.display_name}
                          size={18}
                        />
                      ))}
                    </span>
                  )}
                  {businessLine(stop)}
                </p>
                {stop.arrival_time && (
                  <small>
                    Estimated arrival{" "}
                    {new Intl.DateTimeFormat("en-SG", {
                      timeZone: "Asia/Singapore",
                      hour: "numeric",
                      minute: "2-digit",
                    }).format(new Date(stop.arrival_time))}
                  </small>
                )}
                {hoursNotes(stop.businesses).map((note) => (
                  <small className={`hours-status hours-${note.status}`} key={note.key}>
                    {note.text}
                  </small>
                ))}
              </div>
            </div>
          </div>
        ))}
        <RideLegs
          arrivals={arrivals}
          legs={recommendation.legs}
          segment={recommendation.stops.length}
        />
        <p className="timeline-endpoint">
          B · {destinationLabel ?? result.destination.label}
          {recommendation.arrival_time ? ` · Est. ${sgTime(recommendation.arrival_time)}` : ""}
        </p>
      </div>
      {recommendation.time_dependent === false && (
        <p className="precision-note">
          Departure-time routing is not verified for this provider. Stop arrival times are
          unavailable; this comparison is not a timetable promise.
        </p>
      )}

      {primaryStop?.navigation_ready && (
        <button className="navigate-button" type="button" onClick={() => navigate(primaryStop)}>
          <Navigation size={18} aria-hidden="true" />
          <span>
            {recommendation.stops.length > 1
              ? `Start with ${primaryStop.display_name}`
              : "Navigate"}
          </span>
          <ArrowRight size={18} aria-hidden="true" />
        </button>
      )}

      <p className="why-brief">
        {relationshipCopy(recommendation)} {transferCopy(recommendation.incremental_transfers)}.
      </p>

      <details className="result-disclosure why-disclosure">
        <summary>
          <span>Why this option</span>
          <ChevronDown size={18} aria-hidden="true" />
        </summary>
        <div className="disclosure-body">
          <dl className="breakdown-list">
            <div>
              <dt>Extra travel</dt>
              <dd>+{Math.round(recommendation.detour_breakdown.extra_transport_minutes)} min</dd>
            </div>
            {recommendation.detour_breakdown.dwell_allowances.map((item) => (
              <div key={item.label}>
                <dt>{shortDwellLabel(item.label)}</dt>
                <dd>~{Math.round(item.minutes)} min</dd>
              </div>
            ))}
            <div className="total">
              <dt>Total</dt>
              <dd>+{Math.round(recommendation.detour_breakdown.total_incremental_minutes)} min</dd>
            </div>
          </dl>
          <div className="journey-comparison">
            <div>
              <span>Direct</span>
              <strong>{Math.round(result.baseline.duration_minutes)} min</strong>
              <small>{metres(result.baseline.walking_distance_m)} walk</small>
            </div>
            <ArrowRight size={16} aria-hidden="true" />
            <div>
              <span>With errands</span>
              <strong>{Math.round(recommendation.total_duration_minutes)} min</strong>
              <small>{metres(recommendation.total_walking_distance_m)} walk</small>
            </div>
          </div>
          <p className="precision-note">
            <Clock3 size={13} aria-hidden="true" />
            {recommendation.detour_breakdown.precision_note}
          </p>
        </div>
      </details>

      {routedCount > 1 && (
        <div className="rank-control">
          <span id="rank-label">What matters most</span>
          <div role="group" aria-labelledby="rank-label">
            {(Object.keys(RANK_LABELS) as RankKey[]).map((key) => (
              <button
                type="button"
                key={key}
                aria-pressed={rankBy === key}
                onClick={() => onRankChange(key)}
              >
                {RANK_LABELS[key]}
              </button>
            ))}
          </div>
          <small>{rankNote(rankBy, routedCount)}</small>
        </div>
      )}

      {otherOptions.length > 0 && (
        <details className="result-disclosure alternatives-disclosure">
          <summary>
            <span>
              Other options <small>{otherOptions.length}</small>
            </span>
            <ChevronDown size={18} aria-hidden="true" />
          </summary>
          <div className="alternative-list">
            {otherOptions.map(([key, item]) => (
              <button
                type="button"
                onClick={() => onSelect(key)}
                onMouseEnter={() => onComparedHover?.(key)}
                onFocus={() => onComparedHover?.(key)}
                onMouseLeave={() => onComparedHover?.(null)}
                onBlur={() => onComparedHover?.(null)}
                key={key}
              >
                <span>
                  <strong>{alternativeLabel(key, item)}</strong>
                  <small>{item.stops.map((stop) => stop.display_name).join(" then ")}</small>
                  {tradeoffCopy(item, recommendation) && (
                    <small className="alternative-tradeoff">
                      {tradeoffCopy(item, recommendation)}
                    </small>
                  )}
                </span>
                <b>+{Math.round(item.detour_breakdown.extra_transport_minutes)} min</b>
                <ArrowRight size={16} aria-hidden="true" />
              </button>
            ))}
          </div>
        </details>
      )}

      {compared.length > 0 && (
        <details className="result-disclosure considered-disclosure">
          <summary>
            <span>
              Also compared <small>{compared.length}</small>
            </span>
            <ChevronDown size={18} aria-hidden="true" />
          </summary>
          {/* Buttons, not text. Last round these were inert and the marker
              highlight was a pointer-only garnish; now a row promotes a routed
              candidate into the plan, so it has to be reachable by keyboard
              too. */}
          <div className="considered-list" onMouseLeave={() => onComparedHover?.(null)}>
            {compared.map(([key, item]) => (
              <button
                type="button"
                key={key}
                onClick={() => onSelect(key)}
                onMouseEnter={() => onComparedHover?.(key)}
                onFocus={() => onComparedHover?.(key)}
                onBlur={() => onComparedHover?.(null)}
              >
                <span>
                  <strong>{item.stops.map((stop) => stop.display_name).join(" then ")}</strong>
                  <small>{comparedDetail(item, recommendation)}</small>
                </span>
                <b>+{Math.round(item.detour_breakdown.extra_transport_minutes)} min</b>
                <ArrowRight size={16} aria-hidden="true" />
              </button>
            ))}
          </div>
          <p className="precision-note">
            <Clock3 size={13} aria-hidden="true" />
            {comparedSummary(compared, recommendation, otherOptions)}
          </p>
        </details>
      )}
    </section>
  );
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
  if (item.match_classification === "easier_alternative")
    return `${relationship} It uses an alternative you allowed.`;
  if (item.match_classification === "partial_option")
    return `${relationship} It fits one useful part of your request.`;
  return relationship;
}

function alternativeLabel(key: string, item: Recommendation) {
  if (item.match_classification === "partial_option") return "One errand only";
  if (item.match_classification === "easier_alternative") return "Easier option";
  if (key === "least_walking") return "Less walking";
  if (key === "fastest") return "Less extra travel";
  return item.quality_label;
}

function navigate(stop: Stop) {
  if (!stop.navigation_ready) return;
  window.open(
    `https://www.google.com/maps/dir/?api=1&destination=${stop.coordinate.latitude},${stop.coordinate.longitude}&travelmode=transit&dir_action=navigate`,
    "_blank",
    "noopener,noreferrer",
  );
}
