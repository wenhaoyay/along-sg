import { type Business, type Stop } from "./types";

/* What the stop does for each errand, rather than everything in the building.
 *
 * Waterway Point listed "FairPrice · Unity · Watsons · Guardian · Scoop
 * Wholefoods Australia" and then five lines of opening-hours caveats, one per
 * shop - for a request that was "panadol and groceries". The traveller asked
 * two questions; the stop answers each with one shop, and says how many more
 * could do the same. */

export type ErrandLine = {
  errand: string;
  shop: string;
  status: string;
  others: number;
};

export function errandLabel(slug: string) {
  const text = slug.replace(/_/g, " ").trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function errandLines(stop: Stop): ErrandLine[] {
  const byErrand = new Map<string, string[]>();
  for (const outlet of stop.matching_outlets ?? []) {
    const split = outlet.lastIndexOf(" · ");
    if (split < 0) continue;
    const shop = outlet.slice(0, split).trim();
    const errand = outlet.slice(split + 3).trim();
    const shops = byErrand.get(errand) ?? [];
    if (!shops.includes(shop)) shops.push(shop);
    byErrand.set(errand, shops);
  }
  if (!byErrand.size) {
    // Older responses, and discovered places, name shops without the errand.
    return stop.businesses.slice(0, 2).map((business) => ({
      errand: business.category_labels[0] ?? "Stop",
      shop: business.display_name,
      status: business.opening_status ?? "unknown",
      others: 0,
    }));
  }
  return [...byErrand.entries()].map(([errand, shops]) => ({
    errand: errandLabel(errand),
    shop: shops[0],
    status: statusOf(stop.businesses, shops[0]),
    others: shops.length - 1,
  }));
}

function statusOf(businesses: Business[], name: string) {
  return businesses.find((business) => business.display_name === name)?.opening_status ?? "unknown";
}

export const STATUS_WORD: Record<string, string> = {
  open: "listed open",
  closed: "listed closed",
  closing_soon: "may close soon",
  unknown: "hours not confirmed",
};

/** One note for the stop's hours, however many shops it names. */
export function hoursSummary(lines: ErrandLine[]): string | null {
  if (!lines.length) return null;
  const statuses = new Set(lines.map((line) => line.status));
  if (statuses.size === 1) {
    const [status] = statuses;
    if (status === "open") return "Listed open when you arrive · hours can change";
    if (status === "closed") return "Listed closed when you arrive · check before travelling";
    if (status === "closing_soon") return "May close before you finish · check before travelling";
    return "Opening hours not confirmed · check before travelling";
  }
  // A closed shop is the more urgent fact, so a mixed stop leads with it.
  const closing = lines
    .filter((line) => line.status === "closed" || line.status === "closing_soon")
    .map((line) => line.shop);
  if (closing.length)
    return `${closing.join(" and ")} may be closed when you arrive · check before travelling`;
  const unconfirmed = lines.filter((line) => line.status !== "open").map((line) => line.shop);
  return `Hours not confirmed for ${unconfirmed.join(" and ")} · check before travelling`;
}
