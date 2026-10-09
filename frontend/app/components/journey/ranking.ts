import { type Recommendation } from "./types";
import { capitalise } from "./format";

/* What the traveller wants least of.
 *
 * Every one of these is a figure the optimiser already computed per candidate,
 * so re-ranking is arithmetic over routed results rather than a new search -
 * which is exactly why it can be instant, and exactly why it must not be
 * dressed up as re-optimising. The candidate set was chosen under the default
 * weights; this reorders that set, and `rankNote` says so. */
export type RankKey = "recommended" | "time" | "walking" | "transfers";

/* The same words as the planner's own preference control. The form asked
 * "Balanced / Faster / Less walking" and the result answered with "Our pick /
 * Least time / Least walking / Fewest transfers": one idea, two vocabularies,
 * two places. "Best overall" rather than "Balanced", for the reason below. */
export const RANK_LABELS: Record<RankKey, string> = {
  recommended: "Best overall",
  time: "Faster",
  walking: "Less walking",
  transfers: "Fewer changes",
};

/* An option that drops an errand always sorts last, whatever the weighting.
 *
 * Otherwise re-ranking silently answers a different question: a partial option
 * covers fewer errands, so it is cheaper on every metric by construction, and
 * `inconvenience_score` additionally carries a preference adjustment that makes
 * it incomparable with a full match. A live Woodlands-HarbourFront run had a
 * one-errand option scoring better than every complete one. It stays pickable -
 * it is on the map and in the list - but you have to choose it. */
export const COVERAGE_PENALTY = 1_000_000;

export function coverageRank(item: Recommendation): number {
  return item.match_classification === "partial_option" ? COVERAGE_PENALTY : 0;
}

/** Lower is better for all four, so one comparator serves the whole set. */
export function rankValue(item: Recommendation, rank: RankKey): number {
  return coverageRank(item) + rankMetric(item, rank);
}

export function rankMetric(item: Recommendation, rank: RankKey): number {
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

export function rankNote(rank: RankKey, count: number) {
  if (rank === "recommended")
    return `Our ranking across ${count} routed options: added time, walking and transfers, and how confidently we know each place.`;
  return `Reordering the same ${count} routed options by one measure. The search itself used our own ranking.`;
}

/** The comparison is only evidence if its shape is stated. Five places within
 *  half a minute of each other is a different fact from one clear winner, and
 *  the reader cannot tell which from a list of rounded numbers. */
export function comparedSummary(
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
export const INDISTINGUISHABLE_MINUTES = 2;
export const INDISTINGUISHABLE_METRES = 100;

export function indistinguishable(a: Recommendation, b: Recommendation) {
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
