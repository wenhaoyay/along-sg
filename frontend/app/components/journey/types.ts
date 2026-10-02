import type { ResolvedLocation } from "../LocationField";

export type Business = {
  display_name: string;
  canonical_brand: string | null;
  category_labels: string[];
  location_context: string | null;
  opening_status?: string;
  // Null for most places; PlaceMark draws a category glyph instead.
  logo_url?: string | null;
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
  from_stop_code: string | null;
  to_stop_code: string | null;
  // Needed to decide whether a live arrival is about the bus you will catch.
  departure_time?: string | null;
  arrival_time?: string | null;
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
