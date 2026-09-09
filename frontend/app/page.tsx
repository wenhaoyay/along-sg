"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRight,
  ArrowDownUp,
  ChevronRight,
  Footprints,
  Info,
  Search,
  SlidersHorizontal,
  Zap,
} from "lucide-react";

import {
  CatalogCategory,
  DiscoveryPalette,
  DiscoverySelection,
} from "./components/DiscoveryPalette";
import { LocationField, ResolvedLocation } from "./components/LocationField";
import {
  deduplicatedAlternatives,
  RecommendationPanel,
  type Recommendation,
  rankRoutedOptions,
  type RankKey,
  type Result,
} from "./components/RecommendationPanel";
import { SpatialMap } from "./components/SpatialMap";
import { ThemeToggle } from "./components/ThemeToggle";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";
const QUICK_NEEDS = [
  ["fast_food", "Food"],
  ["coffee", "Coffee"],
  ["bubble_tea", "Bubble tea"],
  ["groceries", "Groceries"],
  ["pharmacy", "Pharmacy"],
] as const;

type OpenNeed = {
  raw_text: string;
  inferred_type: string;
  category_hint?: string | null;
  resolution_status: string;
};
type IntentErrand = {
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
type Intent = {
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
type Conflict = {
  endpoint: "origin" | "destination";
  current_label: string;
  mentioned_text: string;
  mentioned_label: string | null;
  latitude: number | null;
  longitude: number | null;
  reason: string;
};

function context(location: ResolvedLocation) {
  return { label: location.label, coordinate: location.coordinate };
}

export default function Home() {
  const [origin, setOrigin] = useState<ResolvedLocation | null>(null);
  const [destination, setDestination] = useState<ResolvedLocation | null>(null);
  const [need, setNeed] = useState("");
  const [intent, setIntent] = useState<Intent | null>(null);
  const [categories, setCategories] = useState<CatalogCategory[]>([]);
  const [discoveryOpen, setDiscoveryOpen] = useState(false);
  const [selections, setSelections] = useState<DiscoverySelection[]>([]);
  const [loading, setLoading] = useState(false);
  const [leaveMode, setLeaveMode] = useState<"now" | "later">("now");
  const [leaveAt, setLeaveAt] = useState("");
  const [cancelled, setCancelled] = useState(false);
  const [activeStop, setActiveStop] = useState<number | null>(null);
  // Which compared place the pointer is over, so its map marker can lift.
  const [activeConsidered, setActiveConsidered] = useState<string | null>(null);
  const [rankBy, setRankBy] = useState<RankKey>("recommended");
  const searchRef = useRef<AbortController | null>(null);
  const [loadingSlow, setLoadingSlow] = useState(false);
  const [searchStage, setSearchStage] = useState<"discovery" | "routing">("discovery");
  const [tripStyle, setTripStyle] = useState<"balanced" | "faster" | "walking">("balanced");
  const [error, setError] = useState<string | null>(null);
  const [clarification, setClarification] = useState<string | null>(null);
  const [conflict, setConflict] = useState<Conflict | null>(null);
  const [pendingIntent, setPendingIntent] = useState<Intent | null>(null);
  const [partial, setPartial] = useState<{
    intent: Intent;
    text: string;
    missing: string[];
  } | null>(null);
  const [sheet, setSheet] = useState<"peek" | "half" | "full">("half");
  const needRef = useRef<HTMLTextAreaElement>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [selectedKey, setSelectedKey] = useState("best_overall");
  const plannerRef = useRef<HTMLElement>(null);

  useEffect(() => {
    void fetch(`${API_BASE}/api/catalog/categories`)
      .then((response) => (response.ok ? response.json() : []))
      .then(setCategories)
      .catch(() => setCategories([]));
  }, []);
  useEffect(() => {
    if (!loading) return;
    const timer = window.setTimeout(() => setLoadingSlow(true), 4500);
    return () => window.clearTimeout(timer);
  }, [loading]);
  useEffect(() => {
    plannerRef.current?.scrollTo({ top: 0, behavior: "auto" });
  }, [result]);
  useEffect(() => {
    if (conflict) plannerRef.current?.scrollTo({ top: 0, behavior: "auto" });
  }, [conflict]);
  useEffect(() => () => searchRef.current?.abort(), []);

  function beginSearch() {
    searchRef.current?.abort();
    const controller = new AbortController();
    searchRef.current = controller;
    setCancelled(false);
    setLoading(true);
    setLoadingSlow(false);
    setError(null);
    return controller;
  }

  function departureValue() {
    if (leaveMode === "now") return null;
    const value = `${leaveAt}:00+08:00`;
    if (!leaveAt || !Number.isFinite(Date.parse(value)) || Date.parse(value) <= Date.now())
      throw new Error("Choose a future departure time in Singapore time.");
    return value;
  }

  function structuredIntent(): Intent {
    if (!selections.length) throw new Error("Choose at least one errand.");
    return {
      schema_version: "1.0",
      original_text: "Structured discovery selection",
      required_errands: selections.map(({ category, item, mode }) => ({
        category,
        required: true,
        exact_brand: mode === "required" && item?.kind === "brand" ? item.canonical_brand : null,
        preferred_brand:
          mode === "preferred" && item?.kind === "brand" ? item.canonical_brand : null,
        exact_place:
          mode === "required" && item?.kind === "place" && !item.coordinate
            ? item.display_name
            : null,
        discovery_concept: item?.discovery_concept ?? null,
        substitutes_allowed: mode !== "required",
      })),
      optional_errands: [],
      preferences: {
        walking_tolerance: "standard",
        transfer_tolerance: "standard",
        prefer_consolidated_stops: selections.length === 2,
        urgency: "normal",
      },
      parse_method: "deterministic",
      confidence: 1,
    };
  }

  async function optimize(interpreted: Intent, signal: AbortSignal) {
    if (!origin || !destination) throw new Error("Choose both From and To before searching.");
    setSearchStage("routing");
    interpreted = {
      ...interpreted,
      preferences: {
        ...interpreted.preferences,
        ...(tripStyle === "walking" ? { walking_tolerance: "minimal" } : {}),
        ...(tripStyle === "faster" ? { urgency: "urgent" } : {}),
      },
    };
    const confirmedDiscoveryPlaces = selections.flatMap(({ category, item }) =>
      item?.coordinate
        ? [
            {
              display_name: item.display_name,
              coordinate: item.coordinate,
              category,
              address: item.address ?? null,
            },
          ]
        : [],
    );
    const response = await fetch(`${API_BASE}/api/optimize-intent`, {
      signal,
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        origin: { coordinate: origin.coordinate },
        destination: { coordinate: destination.coordinate },
        departure: departureValue(),
        intent: interpreted,
        confirmed_discovery_places: confirmedDiscoveryPlaces,
      }),
    });
    const body = await response.json();
    signal.throwIfAborted();
    if (!response.ok) throw new Error(errorMessage(response.status, body));
    setIntent(interpreted);
    setResult(body);
    setSelectedKey("best_overall");
    setSheet("half");
    setPartial(null);
    setActiveStop(null);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setClarification(null);
    setConflict(null);
    setLoadingSlow(false);
    setSearchStage("discovery");
    setLoading(true);
    const controller = beginSearch();
    try {
      departureValue();
      if (!origin || !destination)
        throw new Error("Choose both From and To from the suggestions first.");
      if (selections.length) {
        await optimize(structuredIntent(), controller.signal);
        return;
      }
      if (!need.trim()) throw new Error("Tell us what you need, or browse categories.");
      const response = await fetch(`${API_BASE}/api/intent/parse`, {
        signal: controller.signal,
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: need,
          origin: context(origin),
          destination: context(destination),
        }),
      });
      const body = await response.json();
      controller.signal.throwIfAborted();
      if (!response.ok) throw new Error(errorMessage(response.status, body));
      if (body.journey_conflicts?.length) {
        setConflict(body.journey_conflicts[0]);
        setPendingIntent(body.intent);
        setClarification(body.clarification_question);
        return;
      }
      if (body.intent && body.unresolved_terms?.length) {
        setPartial({ intent: body.intent, text: need, missing: body.unresolved_terms });
        return;
      }
      if (body.status !== "resolved" || !body.intent) {
        setClarification(body.clarification_question ?? "Tell us a little more about the errand.");
        return;
      }
      if (body.clarification_question) setClarification(body.clarification_question);
      await optimize(body.intent, controller.signal);
    } catch (caught) {
      if (!controller.signal.aborted)
        setError(caught instanceof Error ? caught.message : "We couldn’t compare that journey.");
    } finally {
      if (searchRef.current === controller) setLoading(false);
    }
  }

  function resolveConflict(action: "keep" | "change") {
    if (!conflict) return;
    if (
      action === "change" &&
      conflict.mentioned_label &&
      conflict.latitude != null &&
      conflict.longitude != null
    ) {
      const next: ResolvedLocation = {
        label: conflict.mentioned_label,
        address: conflict.mentioned_label,
        entity_type: "place",
        coordinate: { latitude: conflict.latitude, longitude: conflict.longitude },
        confirmed: true,
      };
      if (conflict.endpoint === "origin") setOrigin(next);
      else setDestination(next);
    }
    if (pendingIntent) {
      setNeed(pendingIntent.original_text);
      setIntent(pendingIntent);
    }
    setConflict(null);
    setClarification(null);
  }

  function selectQuickNeed(slug: string, label: string) {
    const category = categories.find((item) => item.slug === slug);
    if (!category) {
      setNeed(label);
      setSelections([]);
      return;
    }
    setNeed("");
    setIntent(null);
    setSelections([{ category: slug, item: null, mode: "any" }]);
  }

  /* One dict of routed options, split by whether the app volunteered it.
   *
   * A compared candidate is a full recommendation now, so promoting one is
   * `setSelectedKey` and nothing else - no second code path, and the marker key
   * is just the recommendation key. */
  const offeredRecommendations = useMemo(() => {
    const entries = Object.entries(result?.recommendations ?? {}).filter(
      ([, item]) => item.offered !== false,
    );
    return Object.fromEntries(entries);
  }, [result]);
  const selected: Recommendation | undefined =
    result?.recommendations[selectedKey] ??
    result?.recommendations.best_overall ??
    Object.values(result?.recommendations ?? {})[0];
  // The dedupe stays on the offered set only: #5 suppressed indistinguishable
  // choices deliberately, and feeding the compared options through here would
  // quietly undo it.
  const alternatives = useMemo(
    () => deduplicatedAlternatives(offeredRecommendations),
    [offeredRecommendations],
  );
  const compared = useMemo(
    () =>
      rankRoutedOptions(result?.recommendations ?? {}, rankBy).filter(
        ([key, item]) => item.offered === false && key !== selectedKey,
      ),
    [result, rankBy, selectedKey],
  );
  /* Every routed place that is not the plan on screen, as one set.
   *
   * From the map's point of view an offered alternative and a rejected
   * candidate are the same thing: somewhere that was routed and is not where
   * you are being sent. Which of them the app volunteered is a question the
   * panel answers. Clicking any of them makes it the plan. */
  const comparedPoints = useMemo(
    () =>
      [...alternatives.filter(([key]) => key !== selectedKey), ...compared].flatMap(([key, item]) =>
        item.stops.map((stop, index) => ({
          key,
          display_name: stop.display_name,
          extra_transport_minutes: item.detour_breakdown.extra_transport_minutes,
          coordinate: stop.coordinate,
          // A two-stop option puts two markers on the map for one decision,
          // so only the first carries the name of the whole option.
          secondary: index > 0,
        })),
      ),
    [alternatives, compared, selectedKey],
  );

  return (
    <main className={`app-shell ${result ? "has-result" : "input-state"}`}>
      <header className="app-bar">
        <a href="#planner" className="logo" aria-label="Along home">
          <span aria-hidden="true">A</span>
          <strong>Along</strong>
        </a>
        <div>
          <span className="beta-label">Singapore beta</span>
          <ThemeToggle />
          <a className="icon-link" href="/privacy">
            <Info size={17} aria-hidden="true" />
            <span>Privacy</span>
          </a>
        </div>
      </header>

      <section className="map-area">
        <SpatialMap
          origin={origin}
          destination={destination}
          stops={selected?.stops ?? []}
          considered={comparedPoints}
          onConsideredSelect={setSelectedKey}
          baselineGeometry={result?.baseline.geometry ?? []}
          routeGeometry={selected?.route_geometry ?? []}
          activeStop={activeStop}
          activeConsidered={activeConsidered}
          onStopSelect={setActiveStop}
        />
        {selected && (
          <div className="map-key" aria-label="Map route key">
            <span>
              <i className="baseline" />
              Direct
            </span>
            <span>
              <i className="recommended" />
              With stop
            </span>
            {comparedPoints.length > 0 && (
              <span>
                <i className="considered" />
                Compared
              </span>
            )}
          </div>
        )}
      </section>

      <aside
        ref={plannerRef}
        className={`planner ${result ? `result-mode sheet-${sheet}` : ""}`}
        id="planner"
        aria-label={result ? "Recommendation" : "Plan your journey"}
      >
        <div className="sheet-handle" aria-hidden="true" />
        {result && selected && (
          <>
            <div className="sheet-controls" role="group" aria-label="Result sheet size">
              {(
                [
                  ["peek", "Map"],
                  ["half", "Summary"],
                  ["full", "Details"],
                ] as const
              ).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  aria-pressed={sheet === value}
                  onClick={() => {
                    setSheet(value);
                    plannerRef.current?.scrollTo({ top: 0 });
                  }}
                >
                  {label}
                </button>
              ))}
            </div>
            <div className="sheet-peek">
              <strong>{selected.stops[0]?.display_name ?? "Your journey"}</strong>
              <span>
                +{Math.round(selected.detour_breakdown.extra_transport_minutes)} min extra travel
                &middot; +{Math.round(selected.incremental_detour_minutes)} min in total
              </span>
            </div>
          </>
        )}
        {!result && (
          <form onSubmit={submit}>
            <div className="planner-intro">
              <span className="intro-eyebrow">
                <i aria-hidden="true" />
                Your journey, a little more useful
              </span>
              <h1>
                Find what you need <br />
                <em>along the way.</em>
              </h1>
              <p>One journey. A better way to get things done.</p>
            </div>
            <fieldset className="planner-controls" disabled={loading}>
              <div className="journey-fields">
                <LocationField
                  key={`origin-${origin?.label ?? "empty"}`}
                  label="From"
                  placeholder="Search starting point"
                  apiBase={API_BASE}
                  value={origin}
                  onChange={(value) => {
                    setOrigin(value);
                    setResult(null);
                  }}
                  allowCurrentLocation
                />
                <div className="journey-line" aria-hidden="true" />
                <button
                  className="swap-journey"
                  type="button"
                  aria-label="Reverse journey"
                  disabled={!origin && !destination}
                  onClick={() => {
                    setOrigin(destination);
                    setDestination(origin);
                    setIntent(null);
                    setError(null);
                    setClarification(null);
                  }}
                >
                  <ArrowDownUp size={16} aria-hidden="true" />
                </button>
                <LocationField
                  key={`destination-${destination?.label ?? "empty"}`}
                  label="To"
                  placeholder="Search destination"
                  apiBase={API_BASE}
                  value={destination}
                  onChange={(value) => {
                    setDestination(value);
                    setResult(null);
                  }}
                />
              </div>

              <label className="need-control">
                <span>What do you need?</span>
                <div className="need-input-wrap">
                  <Search size={19} aria-hidden="true" />
                  <textarea
                    ref={needRef}
                    aria-label="What do you need on the way?"
                    value={need}
                    onChange={(event) => {
                      setNeed(event.target.value);
                      setPartial(null);
                      setIntent(null);
                      setSelections([]);
                    }}
                    placeholder="Mee pok, Molly Tea or printer ink"
                    rows={1}
                    maxLength={500}
                  />
                </div>
              </label>
              {!intent && !selections.length && (
                <div className="quick-needs" aria-label="Popular needs">
                  {QUICK_NEEDS.map(([slug, label]) => (
                    <button type="button" key={slug} onClick={() => selectQuickNeed(slug, label)}>
                      {label}
                    </button>
                  ))}
                </div>
              )}
              <div className="trip-style" role="group" aria-label="Journey preference">
                <button
                  type="button"
                  aria-pressed={tripStyle === "balanced"}
                  onClick={() => setTripStyle("balanced")}
                >
                  <SlidersHorizontal size={14} aria-hidden="true" />
                  Balanced
                </button>
                <button
                  type="button"
                  aria-pressed={tripStyle === "faster"}
                  onClick={() => setTripStyle("faster")}
                >
                  <Zap size={14} aria-hidden="true" />
                  Faster
                </button>
                <button
                  type="button"
                  aria-pressed={tripStyle === "walking"}
                  onClick={() => setTripStyle("walking")}
                >
                  <Footprints size={14} aria-hidden="true" />
                  Less walking
                </button>
              </div>
              <p className="preference-hint">
                {tripStyle === "walking"
                  ? "Give easier walks more weight when comparing stops."
                  : tripStyle === "faster"
                    ? "Give extra journey time more weight when comparing stops."
                    : "Balance extra time, walking and changes."}
              </p>
              <div className="departure-controls">
                <label>
                  Departure
                  <select
                    aria-label="Departure mode"
                    value={leaveMode}
                    onChange={(event) => setLeaveMode(event.target.value as "now" | "later")}
                  >
                    <option value="now">Leave now</option>
                    <option value="later">Leave later</option>
                  </select>
                </label>
                {leaveMode === "later" && (
                  <label>
                    Singapore time (SGT)
                    <input
                      aria-label="Departure time in Singapore"
                      type="datetime-local"
                      value={leaveAt}
                      onChange={(event) => setLeaveAt(event.target.value)}
                      required
                    />
                  </label>
                )}
              </div>

              {(intent || selections.length > 0) && (
                <div className="intent-preview">
                  <span>Looking for</span>
                  <div>
                    {intent
                      ? [...intent.required_errands, ...intent.optional_errands].map((item) => (
                          <span
                            className="intent-token"
                            key={`${item.category}-${item.exact_brand ?? item.preferred_brand ?? "any"}`}
                          >
                            {intentLabel(categories, item)}
                          </span>
                        ))
                      : selections.map((item) => (
                          <span className="intent-token" key={item.category}>
                            {item.item?.display_name ?? categoryName(categories, item.category)}
                            {item.mode !== "any" ? ` · ${item.mode}` : ""}
                          </span>
                        ))}
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      setIntent(null);
                      setSelections([]);
                    }}
                  >
                    Edit
                  </button>
                </div>
              )}

              {clarification && (
                <div className={conflict ? "notice conflict" : "notice"} role="alert">
                  <strong>{conflict ? "Your journey changed" : "A quick check"}</strong>
                  <p>{clarification}</p>
                  {conflict && (
                    <div className="conflict-actions">
                      <button type="button" onClick={() => resolveConflict("keep")}>
                        Keep {conflict.current_label}
                      </button>
                      {conflict.mentioned_label && (
                        <button type="button" onClick={() => resolveConflict("change")}>
                          Use {conflict.mentioned_label}
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => {
                          if (conflict.endpoint === "origin") setOrigin(null);
                          else setDestination(null);
                          setConflict(null);
                        }}
                      >
                        Edit {conflict.endpoint}
                      </button>
                    </div>
                  )}
                </div>
              )}
              {error && (
                <div className="notice error" role="alert">
                  <strong>One more thing</strong>
                  <p>{error}</p>
                </div>
              )}
              {partial && partial.text === need && !selections.length && (
                <div className="notice" role="alert">
                  <strong>We found part of your request</strong>
                  <p>
                    Not resolved: {partial.missing.join(", ")}. Continue with{" "}
                    {[...partial.intent.required_errands, ...partial.intent.optional_errands]
                      .map((item) => intentLabel(categories, item))
                      .join(" and ")}{" "}
                    only?
                  </p>
                  <div className="conflict-actions">
                    <button
                      type="button"
                      onClick={async () => {
                        const controller = beginSearch();
                        try {
                          await optimize(partial.intent, controller.signal);
                        } catch (caught) {
                          if (!controller.signal.aborted)
                            setError(
                              caught instanceof Error
                                ? caught.message
                                : "We couldn’t compare that journey.",
                            );
                        } finally {
                          if (searchRef.current === controller) setLoading(false);
                        }
                      }}
                    >
                      Continue with matched errands
                    </button>
                    <button type="button" onClick={() => needRef.current?.focus()}>
                      Edit request
                    </button>
                  </div>
                </div>
              )}

              {discoveryOpen && (
                <DiscoveryPalette
                  apiBase={API_BASE}
                  categories={categories}
                  selections={selections}
                  onClose={() => setDiscoveryOpen(false)}
                  onChange={(items) => {
                    setSelections(items);
                    setNeed("");
                    setIntent(null);
                  }}
                />
              )}
            </fieldset>

            <button
              className="find-button"
              type="submit"
              disabled={loading || !origin || !destination}
            >
              <span>
                {loading
                  ? searchStage === "routing"
                    ? "Comparing journeys…"
                    : "Finding suitable stops…"
                  : error
                    ? "Retry search"
                    : "Find best stop"}
              </span>
              {loading ? (
                <span className="button-spinner" />
              ) : (
                <ArrowRight size={19} aria-hidden="true" />
              )}
            </button>
            {loading && (
              <button
                className="cancel-search"
                type="button"
                onClick={() => {
                  searchRef.current?.abort();
                  searchRef.current = null;
                  setLoading(false);
                  setCancelled(true);
                }}
              >
                Cancel search
              </button>
            )}
            {cancelled && (
              <p role="status" className="precision-note">
                Search cancelled. Your journey is kept; edit it or search again. A server check
                already in progress may still finish.
              </p>
            )}
            {loading && (
              <div className="search-progress" role="status">
                <span className={searchStage === "discovery" ? "active" : "complete"}>
                  1 · Find places
                </span>
                <span className={searchStage === "routing" ? "active" : ""}>
                  2 · Compare journeys
                </span>
                {loadingSlow && (
                  <small>This is taking a little longer. We’re still checking your options.</small>
                )}
              </div>
            )}
            {!discoveryOpen && (
              <button
                className="catalog-toggle"
                type="button"
                aria-expanded="false"
                onClick={() => setDiscoveryOpen(true)}
              >
                <span>Browse categories</span>
                <ChevronRight size={17} aria-hidden="true" />
              </button>
            )}
          </form>
        )}

        {result && selected && (
          <RecommendationPanel
            recommendation={selected}
            result={result}
            alternatives={alternatives}
            compared={compared}
            onComparedHover={setActiveConsidered}
            rankBy={rankBy}
            apiBase={API_BASE}
            onRankChange={(rank) => {
              setRankBy(rank);
              // Changing what matters changes the answer, not just the order -
              // otherwise the control would reshuffle a list while leaving the
              // recommendation contradicting the top of it.
              const ranked = rankRoutedOptions(result?.recommendations ?? {}, rank);
              if (ranked.length) setSelectedKey(ranked[0][0]);
            }}
            selectedKey={selectedKey}
            onSelect={(key) => {
              setSelectedKey(key);
              setActiveStop(null);
            }}
            activeStop={activeStop}
            onStopSelect={setActiveStop}
            onEdit={() => {
              setResult(null);
              setActiveStop(null);
              setSelectedKey("best_overall");
            }}
            originLabel={origin?.label}
            destinationLabel={destination?.label}
          />
        )}
        {result && !selected && (
          <section className="recommendation empty-result" aria-live="polite">
            <button className="edit-journey" type="button" onClick={() => setResult(null)}>
              <ArrowRight size={15} aria-hidden="true" />
              Edit journey
            </button>
            <span>Try another way</span>
            <h1>No easy match</h1>
            <p>
              {result.message ?? "Try a broader category or loosen a brand or time preference."}
            </p>
            <button
              className="find-button"
              type="button"
              onClick={() => {
                setDiscoveryOpen(true);
                setResult(null);
              }}
            >
              Browse options
              <ArrowRight size={18} aria-hidden="true" />
            </button>
          </section>
        )}
      </aside>
    </main>
  );
}

function categoryName(categories: CatalogCategory[], slug: string) {
  return categories.find((item) => item.slug === slug)?.name ?? slug.replaceAll("_", " ");
}
function intentLabel(categories: CatalogCategory[], item: IntentErrand) {
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
function errorMessage(status: number, body: { detail?: unknown }) {
  if (status === 404) return "We couldn’t find a public-transport route for this journey.";
  if (status === 429 || status === 503) return "Journey checks are busy. Try again shortly.";
  if (status === 504) return "The route check took too long. Please try again.";
  if (status === 422)
    return typeof body.detail === "string"
      ? body.detail
      : "Part of that request needs another look.";
  return "We couldn’t check routes right now. Please try again.";
}
