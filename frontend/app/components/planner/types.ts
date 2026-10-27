import type { CatalogCategory } from "../DiscoveryPalette";

export type OpenNeed = {
  raw_text: string;
  inferred_type: string;
  category_hint?: string | null;
  resolution_status: string;
};

export type IntentErrand = {
  category: string;
  required: boolean;
  exact_brand?: string | null;
  preferred_brand?: string | null;
  exact_place?: string | null;
  substitutes_allowed: boolean;
  discovery_concept?: string | null;
  discovery_category?: string | null;
  open_need?: OpenNeed | null;
};

export type Intent = {
  schema_version: "1.0";
  original_text: string;
  required_errands: IntentErrand[];
  optional_errands: IntentErrand[];
  preferences: {
    walking_tolerance: string;
    transfer_tolerance: string;
    prefer_consolidated_stops: boolean;
    urgency: string;
    max_detour_is_hard?: boolean;
  };
  parse_method: "deterministic" | "llm";
  confidence: number;
};

export type Conflict = {
  endpoint: "origin" | "destination";
  current_label: string;
  mentioned_text: string;
  mentioned_label: string | null;
  latitude: number | null;
  longitude: number | null;
  reason: string;
};

/* What the planner has to say before it can show a plan - at most one thing
 * at a time. These were four independent pieces of state (a question, a
 * journey conflict, a partly understood request, an error), so the screen
 * could show any combination of them, including contradictory ones. */
export type Notice =
  | { kind: "clarify"; text: string }
  | { kind: "conflict"; text: string; conflict: Conflict; pending: Intent | null }
  | { kind: "partial"; intent: Intent; text: string; missing: string[] }
  | { kind: "error"; text: string };

export function categoryName(categories: CatalogCategory[], slug: string) {
  return categories.find((item) => item.slug === slug)?.name ?? slug.replaceAll("_", " ");
}

export function intentLabel(categories: CatalogCategory[], item: IntentErrand) {
  const label =
    item.open_need?.raw_text ??
    item.exact_brand ??
    item.preferred_brand ??
    item.exact_place ??
    categoryName(categories, item.category);
  if (item.open_need?.inferred_type === "product" && item.discovery_category)
    return `${label} · ${categoryName(categories, item.discovery_category)}`;
  return label;
}
