"use client";

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

import type { ResolvedLocation } from "./LocationField";

export type Business = {
  display_name: string;
  canonical_brand: string | null;
  category_labels: string[];
  location_context: string | null;
  opening_status?: string;
};

export type Stop = {
  name: string;
  display_name: string;
  coordinate: { latitude: number; longitude: number };
  businesses: Business[];
  matching_outlets: string[];
  semantic_type: string;
  location_context: string;
  context_kind: string;
  location_quality: number;
  navigation_ready: boolean;
  arrival_time?: string | null;
};

export type Recommendation = {
  time_dependent?: boolean;
  departure_time?: string | null;
  arrival_time?: string | null;
  label: string;
  quality_label: string;
  match_classification: string;
  hard_constraints_satisfied: boolean;
  stops: Stop[];
  consolidated: boolean;
  total_duration_minutes: number;
  total_walking_distance_m: number;
  total_transfers: number;
  incremental_detour_minutes: number;
  incremental_walking_distance_m: number;
  incremental_transfers: number;
  stop_relationship: string;
  why_this_wins: string;
  detour_breakdown: {
    extra_transport_minutes: number;
    dwell_minutes: number;
    dwell_allowances: Array<{ label: string; minutes: number }>;
    total_incremental_minutes: number;
    precision_note: string;
  };
  route_geometry: Array<{ latitude: number; longitude: number }>;
};

export type Result = {
  origin: ResolvedLocation;
  destination: ResolvedLocation;
  baseline: {
    duration_minutes: number;
    walking_distance_m: number;
    transfers: number;
    geometry: Array<{ latitude: number; longitude: number }>;
  };
  recommendations: Record<string, Recommendation>;
  outcome: string;
  message: string | null;
};

type Props = {
  recommendation: Recommendation;
  result: Result;
  alternatives: Array<[string, Recommendation]>;
  selectedKey: string;
  onSelect: (key: string) => void;
  onEdit: () => void;
  activeStop?: number | null;
  onStopSelect?: (index: number) => void;
};

export function RecommendationPanel({ recommendation, result, alternatives, selectedKey, onSelect, onEdit, activeStop, onStopSelect }: Props) {
  const primaryStop = recommendation.stops[0];
  const otherOptions = alternatives.filter(([key]) => key !== selectedKey);

  return <section className="recommendation" aria-live="polite" data-testid="recommendation-sheet">
    <button className="edit-journey" type="button" onClick={onEdit}>
      <ArrowRight size={15} aria-hidden="true" />
      Edit journey
    </button>

    {result.message && <p className="result-context">{result.message}</p>}

    <div className="result-heading">
      <span className="quality-label"><Check size={13} aria-hidden="true" />{recommendation.quality_label}</span>
      <h1>{primaryStop?.display_name ?? "Your best stop"}</h1>
      {primaryStop && primaryStop.location_context !== primaryStop.display_name && <p>{primaryStop.location_context}</p>}
    </div>

    {/* The headline is extra travel, not total added time. Dwell is roughly
        constant across every option that satisfies the same errands, so
        leading with the total made every stop look expensive and squeezed the
        real differences between them into the last digit. */}
    <div className="result-impact">
      <strong>+{Math.round(recommendation.detour_breakdown.extra_transport_minutes)}<small> min</small><em>extra travel</em></strong>
      <div>
        <span><Footprints size={16} aria-hidden="true" />+{metres(recommendation.incremental_walking_distance_m)} walking</span>
        <span><TrainFront size={16} aria-hidden="true" />{transferCopy(recommendation.incremental_transfers)}</span>
      </div>
    </div>

    <p className="trip-comparison">Direct <strong>{Math.round(result.baseline.duration_minutes)} min</strong><ArrowRight size={14} aria-hidden="true" />With stops <strong>{Math.round(recommendation.total_duration_minutes)} min</strong></p>
    <p className="impact-caption">{Math.round(recommendation.detour_breakdown.dwell_minutes) >= 1
      ? `Plus ~${Math.round(recommendation.detour_breakdown.dwell_minutes)} min at your stops, so +${Math.round(recommendation.incremental_detour_minutes)} min added in total.`
      : `+${Math.round(recommendation.incremental_detour_minutes)} min added in total.`}</p>

    <div className="stop-summary journey-timeline" aria-label="Errand stops">
      <p className="timeline-endpoint">A · {result.origin.label}{recommendation.departure_time ? ` · ${sgTime(recommendation.departure_time)}` : ""}</p>
      {recommendation.stops.map((stop, stopIndex) => <div className={`stop-summary-row ${activeStop === stopIndex ? "selected-stop-card" : ""}`} key={`${stop.display_name}-${stopIndex}`}>
        <button type="button" className="stop-number" aria-label={`Highlight stop ${stopIndex + 1}: ${stop.display_name}`} aria-pressed={activeStop === stopIndex} onClick={() => onStopSelect?.(stopIndex)}>{recommendation.stops.length > 1 ? stopIndex + 1 : <Route size={15} aria-hidden="true" />}</button>
        <div>
          {recommendation.stops.length > 1 && <strong>{stop.display_name}</strong>}
          <p>{stop.businesses.map((business) => business.display_name).join(" · ") || stop.display_name}</p>
          {stop.arrival_time && <small>Estimated arrival {new Intl.DateTimeFormat("en-SG", { timeZone: "Asia/Singapore", hour: "numeric", minute: "2-digit" }).format(new Date(stop.arrival_time))}</small>}
          {hoursNotes(stop.businesses).map((note) => <small className={`hours-status hours-${note.status}`} key={note.key}>{note.text}</small>)}
        </div>
      </div>)}
      <p className="timeline-endpoint">B · {result.destination.label}{recommendation.arrival_time ? ` · Est. ${sgTime(recommendation.arrival_time)}` : ""}</p>
    </div>
    {recommendation.time_dependent === false && <p className="precision-note">Departure-time routing is not verified for this provider. Stop arrival times are unavailable; this comparison is not a timetable promise.</p>}

    {primaryStop?.navigation_ready && <button className="navigate-button" type="button" onClick={() => navigate(primaryStop)}>
      <Navigation size={18} aria-hidden="true" />
      <span>{recommendation.stops.length > 1 ? `Start with ${primaryStop.display_name}` : "Navigate"}</span>
      <ArrowRight size={18} aria-hidden="true" />
    </button>}

    <p className="why-brief">{relationshipCopy(recommendation)} {transferCopy(recommendation.incremental_transfers)}.</p>

    <details className="result-disclosure why-disclosure">
      <summary><span>Why this option</span><ChevronDown size={18} aria-hidden="true" /></summary>
      <div className="disclosure-body">
        <dl className="breakdown-list">
          <div><dt>Extra travel</dt><dd>+{Math.round(recommendation.detour_breakdown.extra_transport_minutes)} min</dd></div>
          {recommendation.detour_breakdown.dwell_allowances.map((item) => <div key={item.label}><dt>{shortDwellLabel(item.label)}</dt><dd>~{Math.round(item.minutes)} min</dd></div>)}
          <div className="total"><dt>Total</dt><dd>+{Math.round(recommendation.detour_breakdown.total_incremental_minutes)} min</dd></div>
        </dl>
        <div className="journey-comparison">
          <div><span>Direct</span><strong>{Math.round(result.baseline.duration_minutes)} min</strong><small>{metres(result.baseline.walking_distance_m)} walk</small></div>
          <ArrowRight size={16} aria-hidden="true" />
          <div><span>With errands</span><strong>{Math.round(recommendation.total_duration_minutes)} min</strong><small>{metres(recommendation.total_walking_distance_m)} walk</small></div>
        </div>
        <p className="precision-note"><Clock3 size={13} aria-hidden="true" />{recommendation.detour_breakdown.precision_note}</p>
      </div>
    </details>

    {otherOptions.length > 0 && <details className="result-disclosure alternatives-disclosure">
      <summary><span>Other options <small>{otherOptions.length}</small></span><ChevronDown size={18} aria-hidden="true" /></summary>
      <div className="alternative-list">
        {otherOptions.map(([key, item]) => <button type="button" onClick={() => onSelect(key)} key={key}>
          <span>
            <strong>{alternativeLabel(key, item)}</strong>
            <small>{item.stops.map((stop) => stop.display_name).join(" then ")}</small>
            {tradeoffCopy(item, recommendation) && <small className="alternative-tradeoff">{tradeoffCopy(item, recommendation)}</small>}
          </span>
          <b>+{Math.round(item.detour_breakdown.extra_transport_minutes)} min</b>
          <ArrowRight size={16} aria-hidden="true" />
        </button>)}
      </div>
    </details>}
  </section>;
}

export function deduplicatedAlternatives(recommendations: Record<string, Recommendation>): Array<[string, Recommendation]> {
  const seen = new Set<string>();
  const kept: Array<[string, Recommendation]> = [];
  for (const [key, item] of Object.entries(recommendations)) {
    const signature = `${item.stops.map((stop) => `${stop.coordinate.latitude.toFixed(4)},${stop.coordinate.longitude.toFixed(4)}`).join("|")}:${Math.round(item.incremental_detour_minutes)}:${Math.round(item.incremental_walking_distance_m / 50)}:${item.incremental_transfers}`;
    if (seen.has(signature)) continue;
    // A different building is a different answer only when the journey it
    // produces differs by something you could act on. Below the thresholds it
    // is noise dressed as a choice.
    if (kept.some(([, existing]) => indistinguishable(item, existing))) continue;
    seen.add(signature);
    kept.push([key, item]);
  }
  return kept;
}

// Mirrors the server thresholds. The server is authoritative; this is the last
// gate before the list is rendered.
const INDISTINGUISHABLE_MINUTES = 2;
const INDISTINGUISHABLE_METRES = 100;

function indistinguishable(a: Recommendation, b: Recommendation) {
  return (
    a.incremental_transfers === b.incremental_transfers
    && Math.abs(a.incremental_detour_minutes - b.incremental_detour_minutes) < INDISTINGUISHABLE_MINUTES
    && Math.abs(a.incremental_walking_distance_m - b.incremental_walking_distance_m) < INDISTINGUISHABLE_METRES
  );
}

/** What an alternative costs relative to the option on screen.
 *
 * An alternative reading "+12 min" beside a recommendation of "+14 min" looks
 * strictly better, and saying nothing invites the reader to conclude the
 * ranking is broken. It is not - the extra time bought less walking or one
 * fewer change. Name that trade, from the same numbers the ranking used. */
export function tradeoffCopy(item: Recommendation, selected: Recommendation): string | null {
  const minutes = item.incremental_detour_minutes - selected.incremental_detour_minutes;
  const metres = item.incremental_walking_distance_m - selected.incremental_walking_distance_m;
  const transfers = item.incremental_transfers - selected.incremental_transfers;
  const gains: string[] = [];
  const costs: string[] = [];

  if (Math.abs(minutes) >= 0.5) {
    (minutes < 0 ? gains : costs).push(`${Math.abs(Math.round(minutes))} min ${minutes < 0 ? "less" : "more"} travel`);
  }
  if (Math.abs(metres) >= 50) {
    (metres < 0 ? gains : costs).push(`${Math.abs(Math.round(metres))} m ${metres < 0 ? "less" : "more"} walking`);
  }
  if (transfers !== 0) {
    (transfers < 0 ? gains : costs).push(`${Math.abs(transfers)} ${transfers < 0 ? "fewer" : "more"} transfer${Math.abs(transfers) === 1 ? "" : "s"}`);
  }

  if (!gains.length && !costs.length) return null;
  if (!gains.length) return `${capitalise(costs.join(" and "))}.`;
  if (!costs.length) return `${capitalise(gains.join(" and "))}.`;
  return `${capitalise(gains.join(" and "))}, but ${costs.join(" and ")}.`;
}

function capitalise(value: string) { return value.charAt(0).toUpperCase() + value.slice(1); }

const HOURS_COPY: Record<string, string> = {
  open: "Listed open at arrival · hours may change",
  closed: "Listed closed at arrival · check before travelling",
  closing_soon: "May close before you finish",
  unknown: "Hours not confirmed · check before travelling",
};

const HOURS_COPY_SHARED: Record<string, (subject: string) => string> = {
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
export function hoursNotes(businesses: Business[]): Array<{ key: string; status: string; text: string }> {
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

function metres(value: number) {
  return value >= 1000 ? `${(value / 1000).toFixed(1)} km` : `${Math.round(value)} m`;
}

function sgTime(value: string) { return new Intl.DateTimeFormat("en-SG", { timeZone: "Asia/Singapore", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(new Date(value)); }

function transferCopy(value: number) {
  if (!value) return "No extra transfers";
  return `+${value} extra transfer${value === 1 ? "" : "s"}`;
}

function shortDwellLabel(label: string) {
  return label.replace(/^Estimated /i, "").replace(/ stop$/i, " stop");
}

function relationshipCopy(item: Recommendation) {
  if (item.match_classification === "partial_option") return "This option covers only part of your request. Edit your journey to change the remaining errand.";
  const relationship = {
    same_mall: "Both errands are together in one mall along your route.",
    same_place: "Both errands are handled in one place.",
    same_transport_hub: "Both stops are within the same station area.",
    nearby_separate_stores: "The shops are close together, keeping the detour compact.",
    separate_stops: "This is the least disruptive order for the two stops.",
    single_stop: "One errand stop between your starting point and destination.",
  }[item.stop_relationship] ?? "This option stays close to your existing journey.";
  if (item.match_classification === "best_available") return `${relationship} It takes longer than usual.`;
  if (item.match_classification === "closest_exact") return `${relationship} It is just above your preference.`;
  if (item.match_classification === "exceeds_limit") return `${relationship} It exceeds the limit you set.`;
  if (item.match_classification === "easier_alternative") return `${relationship} It uses an alternative you allowed.`;
  if (item.match_classification === "partial_option") return `${relationship} It fits one useful part of your request.`;
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
  window.open(`https://www.google.com/maps/dir/?api=1&destination=${stop.coordinate.latitude},${stop.coordinate.longitude}&travelmode=transit&dir_action=navigate`, "_blank", "noopener,noreferrer");
}
