"use client";

import {
  ArrowRight,
  Bus,
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
  legs?: Leg[];
  /** False for a routed candidate the app did not put forward. Selectable all
   *  the same, which is why it is a flag and not a separate shape. */
  offered?: boolean;
  inconvenience_score: number;
};

export type Leg = {
  mode: string;
  duration_minutes: number;
  distance_m: number;
  from_name: string | null;
  to_name: string | null;
  route_short_name: string | null;
  route_long_name: string | null;
  agency: string | null;
  stop_count: number | null;
  segment_index: number | null;
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
};

export function RecommendationPanel({
  recommendation,
  result,
  alternatives,
  compared = [],
  onComparedHover,
  rankBy,
  onRankChange,
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

      {/* The headline is extra travel, not total added time. Dwell is roughly
        constant across every option that satisfies the same errands, so
        leading with the total made every stop look expensive and squeezed the
        real differences between them into the last digit. */}
      <div className="result-impact">
        <strong>
          +{Math.round(recommendation.detour_breakdown.extra_transport_minutes)}
          <small> min</small>
          <em>extra travel</em>
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
          ? `Plus ~${Math.round(recommendation.detour_breakdown.dwell_minutes)} min at your stops, so +${Math.round(recommendation.incremental_detour_minutes)} min added in total.`
          : `+${Math.round(recommendation.incremental_detour_minutes)} min added in total.`}
      </p>

      <div className="stop-summary journey-timeline" aria-label="Errand stops">
        <p className="timeline-endpoint">
          A · {originLabel ?? result.origin.label}
          {recommendation.departure_time ? ` · ${sgTime(recommendation.departure_time)}` : ""}
        </p>
        {recommendation.stops.map((stop, stopIndex) => (
          <div key={`segment-${stopIndex}`}>
            <RideLegs legs={recommendation.legs} segment={stopIndex} />
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
                <p>{businessLine(stop)}</p>
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
        <RideLegs legs={recommendation.legs} segment={recommendation.stops.length} />
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

/* What the traveller wants least of.
 *
 * Every one of these is a figure the optimiser already computed per candidate,
 * so re-ranking is arithmetic over routed results rather than a new search -
 * which is exactly why it can be instant, and exactly why it must not be
 * dressed up as re-optimising. The candidate set was chosen under the default
 * weights; this reorders that set, and `rankNote` says so. */
export type RankKey = "recommended" | "time" | "walking" | "transfers";

export const RANK_LABELS: Record<RankKey, string> = {
  recommended: "Our pick",
  time: "Least time",
  walking: "Least walking",
  transfers: "Fewest transfers",
};

/* An option that drops an errand always sorts last, whatever the weighting.
 *
 * Otherwise re-ranking silently answers a different question: a partial option
 * covers fewer errands, so it is cheaper on every metric by construction, and
 * `inconvenience_score` additionally carries a preference adjustment that makes
 * it incomparable with a full match. A live Woodlands-HarbourFront run had a
 * one-errand option scoring better than every complete one. It stays pickable -
 * it is on the map and in the list - but you have to choose it. */
const COVERAGE_PENALTY = 1_000_000;

function coverageRank(item: Recommendation): number {
  return item.match_classification === "partial_option" ? COVERAGE_PENALTY : 0;
}

/** Lower is better for all four, so one comparator serves the whole set. */
export function rankValue(item: Recommendation, rank: RankKey): number {
  return coverageRank(item) + rankMetric(item, rank);
}

function rankMetric(item: Recommendation, rank: RankKey): number {
  switch (rank) {
    case "time":
      return item.detour_breakdown.extra_transport_minutes;
    case "walking":
      return item.incremental_walking_distance_m;
    case "transfers":
      // Transfers are coarse and tie constantly, so time breaks the tie rather
      // than leaving the order to whatever the object happened to be built in.
      return item.incremental_transfers * 1000 + item.detour_breakdown.extra_transport_minutes;
    case "recommended":
    default:
      /* The optimiser's own score, so the default is the app's actual verdict
       * rather than a fourth opinion invented in the client.
       *
       * It is deliberately NOT called "balanced": the score is the journey cost
       * minus a credit for how confidently the place is known (location
       * certainty plus published hours, weighted 2.5). On a live
       * Woodlands-HarbourFront run that credit picked a named shop at +11 min
       * over a mall at +5, which is defensible as a recommendation and
       * indefensible as "balanced" - the label would have been claiming the
       * three journey metrics and quietly using a fourth term. */
      return item.inconvenience_score;
  }
}

export function rankRoutedOptions(
  recommendations: Record<string, Recommendation>,
  rank: RankKey,
): Array<[string, Recommendation]> {
  return Object.entries(recommendations).sort(
    ([, first], [, second]) => rankValue(first, rank) - rankValue(second, rank),
  );
}

function rankNote(rank: RankKey, count: number) {
  if (rank === "recommended")
    return `Our ranking across ${count} routed options: added time, walking and transfers, and how confidently we know each place.`;
  return `Reordering the same ${count} routed options by one measure. The search itself used our own ranking.`;
}

/** Why a compared place is not the plan, in the figures the ranking used.
 *
 * Below a minute there is no honest difference to report, and inventing one
 * ("slightly slower") would misrepresent a tie as a decision. */
function comparedDetail(option: Recommendation, chosen: Recommendation) {
  const slower =
    option.detour_breakdown.extra_transport_minutes -
    chosen.detour_breakdown.extra_transport_minutes;
  const further = option.incremental_walking_distance_m - chosen.incremental_walking_distance_m;
  const transfers = option.incremental_transfers - chosen.incremental_transfers;
  const parts: string[] = [];
  if (transfers > 0) parts.push(`${transfers} more transfer${transfers > 1 ? "s" : ""}`);
  if (slower >= 1) parts.push(`${Math.round(slower)} min more travel`);
  if (further >= 100) parts.push(`${Math.round(further)} m more walking`);
  if (parts.length) return parts.join(", ");
  if (option.stops.length > chosen.stops.length) return "Needs an extra stop";
  return "Within a minute of the plan above";
}

/** The comparison is only evidence if its shape is stated. Five places within
 *  half a minute of each other is a different fact from one clear winner, and
 *  the reader cannot tell which from a list of rounded numbers. */
function comparedSummary(
  compared: Array<[string, Recommendation]>,
  chosen: Recommendation,
  otherOptions: Array<[string, Recommendation]>,
) {
  // Everything routed, not just the rejected half: the offered alternatives
  // were compared too, and counting only what is in this list would understate
  // the work by exactly the number of options the panel is already showing.
  const total = compared.length + otherOptions.length + 1;
  const spread = Math.max(
    ...compared.map(
      ([, option]) =>
        option.detour_breakdown.extra_transport_minutes -
        chosen.detour_breakdown.extra_transport_minutes,
    ),
    ...otherOptions.map(
      ([, item]) =>
        item.detour_breakdown.extra_transport_minutes -
        chosen.detour_breakdown.extra_transport_minutes,
    ),
    0,
  );
  if (spread < 1)
    return `All ${total} routed options landed within a minute of each other, so this pick is close to a tie.`;
  return `${total} options were routed and compared; the rest cost up to ${Math.round(spread)} min more travel.`;
}

export function deduplicatedAlternatives(
  recommendations: Record<string, Recommendation>,
): Array<[string, Recommendation]> {
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
    a.incremental_transfers === b.incremental_transfers &&
    Math.abs(a.incremental_detour_minutes - b.incremental_detour_minutes) <
      INDISTINGUISHABLE_MINUTES &&
    Math.abs(a.incremental_walking_distance_m - b.incremental_walking_distance_m) <
      INDISTINGUISHABLE_METRES
  );
}

/** What an alternative costs relative to the option on screen.
 *
 * An alternative reading "+12 min" beside a recommendation of "+14 min" looks
 * strictly better, and saying nothing invites the reader to conclude the
 * ranking is broken. It is not - the extra time bought less walking or one
 * fewer change. Name that trade, from the same numbers the ranking used. */
export function tradeoffCopy(item: Recommendation, selected: Recommendation): string | null {
  // A partial option covers fewer errands, so "20 min less travel" would read
  // as strictly better when it is simply doing less. Its label says so instead.
  if (item.match_classification === "partial_option") return null;
  // Extra travel, not total added time - the same figure the row displays and
  // the headline leads with. Comparing total added time here called a dwell
  // difference "less travel": a live run offered ION Orchard as "15 min less
  // travel" when its travel differed by 0.15 min and the whole 15 minutes was
  // one fewer shop to stand in. That is the mislabelling 0.7.7 removed from the
  // headline, left behind in the alternatives.
  const minutes =
    item.detour_breakdown.extra_transport_minutes -
    selected.detour_breakdown.extra_transport_minutes;
  const metres = item.incremental_walking_distance_m - selected.incremental_walking_distance_m;
  const transfers = item.incremental_transfers - selected.incremental_transfers;
  const gains: string[] = [];
  const costs: string[] = [];

  if (Math.abs(minutes) >= 0.5) {
    (minutes < 0 ? gains : costs).push(
      `${Math.abs(Math.round(minutes))} min ${minutes < 0 ? "less" : "more"} travel`,
    );
  }
  if (Math.abs(metres) >= 50) {
    (metres < 0 ? gains : costs).push(
      `${Math.abs(Math.round(metres))} m ${metres < 0 ? "less" : "more"} walking`,
    );
  }
  if (transfers !== 0) {
    (transfers < 0 ? gains : costs).push(
      `${Math.abs(transfers)} ${transfers < 0 ? "fewer" : "more"} transfer${Math.abs(transfers) === 1 ? "" : "s"}`,
    );
  }

  if (!gains.length && !costs.length) return null;
  if (!gains.length) return `${capitalise(costs.join(" and "))}.`;
  if (!costs.length) return `${capitalise(gains.join(" and "))}.`;
  return `${capitalise(gains.join(" and "))}, but ${costs.join(" and ")}.`;
}

function capitalise(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function businessLine(stop: Stop) {
  return stop.businesses.map((business) => business.display_name).join(" · ") || stop.display_name;
}

const WALKING_MODES = new Set(["WALK", "BICYCLE", "SCOOTER"]);

/** The services you actually board on one leg of the journey.
 *
 * OneMap returns `routeShortName`, `routeLongName`, `agencyName` and
 * `intermediateStops` on every transit leg, and all of it was being discarded
 * - so a plan could say "37 minutes" without ever saying which train or bus to
 * get on, which is the one thing the traveller has to act on. */
function RideLegs({ legs, segment }: { legs?: Leg[]; segment: number }) {
  const rides = (legs ?? []).filter(
    (leg) => leg.segment_index === segment && !WALKING_MODES.has(leg.mode.toUpperCase()),
  );
  if (!rides.length) return null;
  return (
    <>
      {rides.map((leg, index) => (
        <p className="ride-leg" key={`${segment}-${index}`}>
          {isRail(leg) ? (
            <TrainFront size={13} aria-hidden="true" />
          ) : (
            <Bus size={13} aria-hidden="true" />
          )}
          <span className="service">{serviceName(leg)}</span>
          <span className="ride-detail">{rideDetail(leg)}</span>
        </p>
      ))}
    </>
  );
}

const RAIL_MODES = new Set(["SUBWAY", "RAIL", "TRAM", "METRO", "TRAIN", "LIGHT_RAIL", "FUNICULAR"]);

function isRail(leg: Leg) {
  return RAIL_MODES.has(leg.mode.toUpperCase());
}

function serviceName(leg: Leg) {
  const short = leg.route_short_name?.trim();
  if (isRail(leg)) return short ? `${short} line` : "Train";
  if (short) return `Bus ${short}`;
  return leg.route_long_name?.trim() || titleCase(leg.mode);
}

function rideDetail(leg: Leg) {
  const parts: string[] = [];
  if (leg.stop_count && leg.stop_count > 0) {
    parts.push(`${leg.stop_count} stop${leg.stop_count === 1 ? "" : "s"}`);
  }
  if (leg.duration_minutes >= 1) parts.push(`${Math.round(leg.duration_minutes)} min`);
  return parts.join(" · ");
}

function titleCase(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1).toLowerCase().replace(/_/g, " ");
}

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

function metres(value: number) {
  return value >= 1000 ? `${(value / 1000).toFixed(1)} km` : `${Math.round(value)} m`;
}

function sgTime(value: string) {
  return new Intl.DateTimeFormat("en-SG", {
    timeZone: "Asia/Singapore",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function transferCopy(value: number) {
  if (!value) return "No extra transfers";
  return `+${value} extra transfer${value === 1 ? "" : "s"}`;
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
