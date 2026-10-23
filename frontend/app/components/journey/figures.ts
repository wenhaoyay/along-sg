import { type Recommendation } from "./types";

/* The three numbers every view of an option quotes, from one place.
 *
 * The headline, the breakdown's total, the bar's overrun past the direct line,
 * the row figures and the map pins each used to compute their own, and they
 * disagreed: a headline of "+8 min" sat over a breakdown of 8 min travel plus
 * 23 min in shops. Each figure now has one definition here.
 *
 *  - travel: extra time moving (trains, buses, walking) against going direct.
 *    It is what tells two places apart, so it leads, and it is the number on
 *    every row and every pin.
 *  - shops: the time allowed for the errands themselves, about the same
 *    wherever they are done.
 *  - later: how much later you arrive than going direct, travel plus shops.
 */
export function travelMinutes(item: Recommendation): number {
  return item.incremental_travel_minutes ?? item.detour_breakdown.extra_transport_minutes;
}

export function shopMinutes(item: Recommendation): number {
  return item.detour_breakdown.dwell_minutes;
}

export function laterMinutes(item: Recommendation): number {
  return item.incremental_detour_minutes;
}

/** "+3", "0" or "−2": never "+-2", whatever rounding does. */
export function signed(minutes: number): string {
  const rounded = Math.round(minutes);
  if (rounded === 0) return "0";
  return rounded > 0 ? `+${rounded}` : `−${Math.abs(rounded)}`;
}

const CATEGORY_NOUNS: Record<string, string> = {
  groceries: "supermarket",
  convenience: "convenience store",
  pharmacy: "pharmacy",
  bubble_tea: "bubble tea",
  coffee: "coffee",
  fast_food: "fast food",
  restaurants: "restaurant",
  parcel: "parcel point",
  post_office: "post office",
  banking: "bank",
  atm: "ATM",
  haircuts: "haircut",
};

export function categoryNoun(slug: string): string {
  return CATEGORY_NOUNS[slug] ?? slug.replace(/_/g, " ");
}

/** What makes an option a different kind of answer, in words, on its row and
 *  in its accessible name. Without it a +22 beside a +32 looked strictly
 *  better when it was a 7-Eleven standing in for the supermarket. */
export function optionTag(item: Recommendation): string | null {
  switch (item.match_classification) {
    case "partial_option": {
      const skipped = item.omitted_categories ?? [];
      return skipped.length
        ? `skips ${skipped.map(categoryNoun).join(" and ")}`
        : "one errand only";
    }
    case "substitute": {
      const swaps = item.substituted_categories ?? [];
      return swaps.length
        ? `substitute: ${swaps.map((swap) => categoryNoun(swap.substitute)).join(" and ")}`
        : "substitute";
    }
    case "without_preferred_brand": {
      const brands = item.missing_preferred_brands ?? [];
      return brands.length ? `no ${brands.join(" or ")}` : "not your preferred brand";
    }
    case "exceeds_limit":
      return "over your limit";
    default:
      return null;
  }
}
