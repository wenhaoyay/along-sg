"use client";

import { FormEvent, KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, ArrowDownUp, ChevronRight, Info, Search } from "lucide-react";

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
import { LogoMark } from "./components/Logo";
import { EXAMPLES, placeName, type Example } from "./examples";
import { laterMinutes, signed, travelMinutes } from "./components/journey/figures";
import { clockTime } from "./components/journey/format";
import { readTrip, tripQuery } from "./share";
import { NoticeLane } from "./components/planner/NoticeLane";
import { TripOptions } from "./components/planner/TripOptions";
import {
  categoryName,
  intentLabel,
  type Conflict,
  type Intent,
  type Notice,
  type TripStyle,
} from "./components/planner/types";

/* How long an example waits for the live answer before showing the saved run
 * of it. A free host sleeps when idle and takes about a minute to wake; a
 * reviewer's first click should not be that minute of spinner. */
const SAVED_EXAMPLE_AFTER_MS = 2500;
type SavedRun = { generatedAt: string; liveFailed: boolean };

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";
/* The planner's preference and the result's sort are one idea, so they share
 * one vocabulary, and the result opens sorted the way the search was asked. */
/* One empty list for the map's props. A fresh `[]` per render is a new
 * dependency every keystroke, and the map rebuilt and refitted its layers on
 * each one. */
const NONE: never[] = [];
const STYLE_RANK: Record<"balanced" | "faster" | "walking", RankKey> = {
  balanced: "recommended",
  faster: "time",
  walking: "walking",
};
const QUICK_NEEDS = [
  ["fast_food", "Food"],
  ["coffee", "Coffee"],
  ["bubble_tea", "Bubble tea"],
  ["groceries", "Groceries"],
  ["pharmacy", "Pharmacy"],
] as const;

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
  const [tripStyle, setTripStyle] = useState<TripStyle>("balanced");
  // At most one message before a plan: a question, a journey conflict, a
  // partly understood request or an error (see Notice).
  const [notice, setNotice] = useState<Notice | null>(null);
  const error = notice?.kind === "error" ? notice.text : null;
  const [sheet, setSheet] = useState<"peek" | "half">("half");
  const needRef = useRef<HTMLTextAreaElement>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [selectedKey, setSelectedKey] = useState("best_overall");
  const plannerRef = useRef<HTMLElement>(null);
  const formRef = useRef<HTMLFormElement>(null);
  const noticeRef = useRef<HTMLDivElement>(null);
  const discoveryRef = useRef<HTMLDivElement>(null);
  // Set by an example card or a shared link: run the search once its fields
  // have rendered.
  const pendingExample = useRef(false);
  // Which example is running, so a saved run of it can stand in while a
  // sleeping server wakes up.
  const exampleRef = useRef<string | null>(null);
  const [savedRun, setSavedRun] = useState<SavedRun | null>(null);
  const [previewExample, setPreviewExample] = useState<Example | null>(null);
  // True when the server plans over the offline rail network with estimated
  // minutes; said on screen so nobody reads them as a timetable.
  const [sampleTimes, setSampleTimes] = useState(false);
  // Results already shown, by link, so Back and Forward restore a plan
  // instead of planning it again.
  const visited = useRef(new Map<string, Result>());
  // Whether the server has answered at all. A saved run stands in only while
  // it has not: a server that is awake but slow gives the live answer, rather
  // than a saved one that is swapped out a second later.
  const serverAwake = useRef(false);

  useEffect(() => {
    void fetch(`${API_BASE}/api/catalog/categories`)
      .then((response) => (response.ok ? response.json() : []))
      .then(setCategories)
      .catch(() => setCategories([]));
    // Also wakes a sleeping host before the first search needs it.
    void fetch(`${API_BASE}/health`)
      .then((response) => {
        serverAwake.current = response.ok;
        return response.ok ? response.json() : null;
      })
      .then((body) => setSampleTimes(Boolean(body?.onemap_mock)))
      .catch(() => undefined);
  }, []);
  // A shared link plans its trip on arrival. The page is a static export, so
  // the address can only be read after hydration, once.
  useEffect(() => {
    const shared = readTrip(window.location.search);
    if (!shared) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- one-time sync from the URL
    setOrigin(shared.origin);
    setDestination(shared.destination);
    setNeed(shared.need);
    setTripStyle(shared.style);
    pendingExample.current = true;
  }, []);
  // Back from a result returns to the form; Forward brings the result back.
  useEffect(() => {
    function restore() {
      const kept = visited.current.get(window.location.search);
      if (kept) {
        setResult(kept);
        setSelectedKey("best_overall");
      } else {
        setResult(null);
      }
      setActiveStop(null);
    }
    window.addEventListener("popstate", restore);
    return () => window.removeEventListener("popstate", restore);
  }, []);
  // Focus follows the answer: to its heading when one arrives, back to the
  // search button when the journey is being edited. Without this the submit
  // button unmounted under the keyboard and focus fell to the page body.
  const hadResult = useRef(false);
  useEffect(() => {
    if (result && !hadResult.current) {
      document.querySelector<HTMLElement>(".result-heading h1")?.focus();
    } else if (!result && hadResult.current) {
      document.querySelector<HTMLElement>(".find-button")?.focus();
    }
    hadResult.current = Boolean(result);
  }, [result]);
  useEffect(() => {
    if (!loading) return;
    const timer = window.setTimeout(() => setLoadingSlow(true), 4500);
    return () => window.clearTimeout(timer);
  }, [loading]);
  useEffect(() => {
    plannerRef.current?.scrollTo({ top: 0, behavior: "auto" });
  }, [result]);
  useEffect(() => () => searchRef.current?.abort(), []);
  /* A message answering the button press opened below the fold of the
   * planner card - "A quick check" for "hello" was cut off at the bottom
   * edge, and Browse categories opened its search box there with no list in
   * sight. Whatever just appeared is scrolled into view. */
  useEffect(() => {
    if (!notice) return;
    if (notice.kind === "conflict") plannerRef.current?.scrollTo({ top: 0, behavior: "auto" });
    noticeRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [notice]);
  useEffect(() => {
    if (discoveryOpen) discoveryRef.current?.scrollIntoView({ block: "start", behavior: "smooth" });
  }, [discoveryOpen]);
  useEffect(() => {
    if (!pendingExample.current || !origin || !destination || !need) return;
    pendingExample.current = false;
    formRef.current?.requestSubmit();
  }, [origin, destination, need]);
  // The need field grows with what is typed, rather than offering a
  // textarea's resize grip inside something styled as a search box.
  useEffect(() => {
    const field = needRef.current;
    if (!field) return;
    field.style.height = "auto";
    field.style.height = `${field.scrollHeight}px`;
  }, [need, result]);

  function runExample(example: Example) {
    setResult(null);
    setOrigin(example.origin);
    setDestination(example.destination);
    setNeed(example.need);
    setIntent(null);
    setSelections([]);
    setNotice(null);
    setPreviewExample(null);
    setTripStyle("balanced");
    exampleRef.current = example.id;
    pendingExample.current = true;
  }

  /* While a sleeping server wakes, show the saved run of an example after a
   * moment, said as such. The live answer replaces it on arrival. */
  function standInForExample(controller: AbortController) {
    const id = exampleRef.current;
    exampleRef.current = null;
    if (!id) return;
    window.setTimeout(async () => {
      if (serverAwake.current) return;
      if (searchRef.current !== controller || controller.signal.aborted) return;
      try {
        const response = await fetch(`/examples/${id}.json`);
        if (!response.ok) return;
        const saved = await response.json();
        if (searchRef.current !== controller || controller.signal.aborted) return;
        if (!saved?.optimize?.recommendations) return;
        setResult(saved.optimize);
        setSelectedKey("best_overall");
        setSavedRun({ generatedAt: saved.generated_at, liveFailed: false });
      } catch {
        // No saved run: the spinner carries on, as it always did.
      }
    }, SAVED_EXAMPLE_AFTER_MS);
  }

  function beginSearch() {
    searchRef.current?.abort();
    const controller = new AbortController();
    searchRef.current = controller;
    setCancelled(false);
    setLoading(true);
    setLoadingSlow(false);
    // A new search answers the last error; a question or a partial match
    // stays on screen until the answer replaces it.
    setNotice((current) => (current?.kind === "error" ? null : current));
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
    const body = await readBody(response);
    signal.throwIfAborted();
    if (!response.ok) throw new Error(errorMessage(response.status, body));
    setIntent(interpreted);
    setResult(body as Result);
    setSavedRun(null);
    const rank = STYLE_RANK[tripStyle];
    setRankBy(rank);
    const ranked =
      rank === "recommended" ? [] : rankRoutedOptions((body as Result).recommendations ?? {}, rank);
    setSelectedKey(ranked[0]?.[0] ?? "best_overall");
    setSheet("half");
    setNotice(null);
    setActiveStop(null);
    // The plan becomes a link: shareable, and Back returns to the form. A
    // structured (browsed) selection has no text to put in a link.
    if (need.trim() && !selections.length) {
      const query = tripQuery({ origin, destination, need: need.trim(), style: tripStyle });
      visited.current.set(query, body as Result);
      if (window.location.search !== query)
        window.history.pushState(null, "", `${window.location.pathname}${query}`);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setNotice(null);
    setLoadingSlow(false);
    setSearchStage("discovery");
    const controller = beginSearch();
    standInForExample(controller);
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
      const body = (await readBody(response)) as ParseResponse;
      controller.signal.throwIfAborted();
      if (!response.ok) throw new Error(errorMessage(response.status, body));
      if (body.journey_conflicts?.length) {
        setNotice({
          kind: "conflict",
          conflict: body.journey_conflicts[0],
          pending: body.intent ?? null,
          text: body.clarification_question ?? "",
        });
        return;
      }
      if (body.intent && body.unresolved_terms?.length) {
        setNotice({
          kind: "partial",
          intent: body.intent,
          text: need,
          missing: body.unresolved_terms,
        });
        return;
      }
      if (body.status !== "resolved" || !body.intent) {
        setNotice({
          kind: "clarify",
          text: body.clarification_question ?? "Tell us a little more about the errand.",
        });
        return;
      }
      await optimize(body.intent, controller.signal);
    } catch (caught) {
      if (controller.signal.aborted) return;
      // A saved run already on screen stays, marked as not refreshed.
      setSavedRun((saved) => (saved ? { ...saved, liveFailed: true } : saved));
      setNotice({ kind: "error", text: failureMessage(caught) });
    } finally {
      if (searchRef.current === controller) setLoading(false);
    }
  }

  /* Enter searches, as it does in every search box; Shift+Enter still breaks
   * a line for a long list. It used to add a newline to a field that looks
   * like a single-line search. */
  function submitOnEnter(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    if (origin && destination && !loading) formRef.current?.requestSubmit();
  }

  function resolveConflict(action: "keep" | "change") {
    if (notice?.kind !== "conflict") return;
    const { conflict, pending } = notice;
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
    if (pending) {
      setNeed(pending.original_text);
      setIntent(pending);
    }
    setNotice(null);
  }

  function editConflictEndpoint() {
    if (notice?.kind !== "conflict") return;
    if (notice.conflict.endpoint === "origin") setOrigin(null);
    else setDestination(null);
    setNotice(null);
  }

  async function continuePartial() {
    if (notice?.kind !== "partial") return;
    const controller = beginSearch();
    try {
      await optimize(notice.intent, controller.signal);
    } catch (caught) {
      if (!controller.signal.aborted) setNotice({ kind: "error", text: failureMessage(caught) });
    } finally {
      if (searchRef.current === controller) setLoading(false);
    }
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

  // The empty map shows an example journey rather than the whole island with
  // nothing on it; pointing at another example previews that one.
  const preview = !result && !origin && !destination ? (previewExample ?? EXAMPLES[0]) : null;
  // A browsed selection has no text to put in a link, so it is not shareable.
  const shareQuery =
    result && origin && destination && need.trim() && !selections.length
      ? tripQuery({ origin, destination, need: need.trim(), style: tripStyle })
      : null;

  return (
    <main className={`app-shell ${result ? `has-result sheet-${sheet}` : "input-state"}`}>
      <header className="app-bar">
        <a href="#planner" className="logo" aria-label="Along home">
          <LogoMark />
          <strong>Along</strong>
        </a>
        <div>
          {/* Plain links, not next/link: Next 16's static export names the
            page's prefetch file differently from the one the client asks for,
            so a prefetch 404s. A plan is a link now, so leaving for this page
            and coming Back no longer loses it. */}
          {sampleTimes && (
            <a
              className="sample-badge"
              href="/privacy/#demo"
              title="Real lines and stations; the minutes are estimates"
            >
              Sample times
            </a>
          )}
          <ThemeToggle />
          <a className="icon-link" href="/privacy/">
            <Info size={17} aria-hidden="true" />
            <span>Privacy</span>
          </a>
        </div>
      </header>

      <aside
        ref={plannerRef}
        className={`planner ${result ? `result-mode sheet-${sheet}` : ""}`}
        id="planner"
        aria-label={result ? "Recommendation" : "Plan your journey"}
      >
        <div className="sheet-handle" aria-hidden="true" />
        {result && selected && (
          <>
            {/* Two states, named for what you then see. "Summary" and
                "Details" sounded like different content and were the same
                panel at two heights. */}
            <div className="sheet-controls" role="group" aria-label="Show on screen">
              {(
                [
                  ["peek", "Map"],
                  ["half", "Plan"],
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
                {signed(travelMinutes(selected))} min extra travel &middot; arrive{" "}
                {Math.round(laterMinutes(selected))} min later than direct
              </span>
            </div>
          </>
        )}
        {!result && (
          <form onSubmit={submit} ref={formRef}>
            {/* One sentence that says what the app does, instead of three
                taglines that said it was useful. */}
            <div className="planner-intro">
              <h1>
                Errands on the way, <br />
                <em>not out of the way.</em>
              </h1>
              <p>
                Say what you need. Along compares real stops along a trip you are already making by
                MRT or bus, and shows what each one adds.
              </p>
            </div>
            {!origin && !destination && (
              <div className="examples" aria-labelledby="examples-title">
                <span id="examples-title">Try one</span>
                <div onMouseLeave={() => setPreviewExample(null)}>
                  {EXAMPLES.map((example) => (
                    <button
                      type="button"
                      key={example.id}
                      onClick={() => runExample(example)}
                      onMouseEnter={() => setPreviewExample(example)}
                      onFocus={() => setPreviewExample(example)}
                      onBlur={() => setPreviewExample(null)}
                    >
                      <strong>
                        {placeName(example.origin)} <ArrowRight size={12} aria-hidden="true" />{" "}
                        {placeName(example.destination)}
                      </strong>
                      <span>{example.need}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}
            <fieldset className="planner-controls" disabled={loading}>
              <div className="journey-fields">
                <LocationField
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
                    // A partial match is about the text, which the swap keeps.
                    setNotice((current) => (current?.kind === "partial" ? current : null));
                  }}
                >
                  <ArrowDownUp size={16} aria-hidden="true" />
                </button>
                <LocationField
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
                <span>What do you need on the way?</span>
                <div className="need-input-wrap">
                  <Search size={19} aria-hidden="true" />
                  <textarea
                    ref={needRef}
                    value={need}
                    onKeyDown={submitOnEnter}
                    onChange={(event) => {
                      setNeed(event.target.value);
                      setNotice((current) => (current?.kind === "partial" ? null : current));
                      setIntent(null);
                      setSelections([]);
                    }}
                    placeholder="Mee pok, Molly Tea or printer ink"
                    rows={1}
                    maxLength={300}
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
              <TripOptions
                style={tripStyle}
                onStyle={setTripStyle}
                leaveMode={leaveMode}
                onLeaveMode={setLeaveMode}
                leaveAt={leaveAt}
                onLeaveAt={setLeaveAt}
              />

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

              <NoticeLane
                ref={noticeRef}
                notice={notice}
                need={need}
                browsing={selections.length > 0}
                categories={categories}
                onKeep={() => resolveConflict("keep")}
                onUseMentioned={() => resolveConflict("change")}
                onEditEndpoint={editConflictEndpoint}
                onContinuePartial={continuePartial}
                onEditRequest={() => needRef.current?.focus()}
              />

              <div ref={discoveryRef}>
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
              </div>
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

        {/* One short sentence for screen readers when an answer arrives; the
          panel itself is no longer a live region that re-read everything on
          every bus-arrival refresh. */}
        <p className="sr-only" role="status">
          {result && selected
            ? `${selected.stops.map((stop) => stop.display_name).join(" then ")}: ${signed(
                travelMinutes(selected),
              )} minutes extra travel${
                selected.arrival_time ? `, arrive ${clockTime(selected.arrival_time)}` : ""
              }.`
            : ""}
        </p>
        {result && savedRun && (
          <p className="notice saved-run" role="note">
            {savedRun.liveFailed
              ? `The live check didn’t come back, so this is a saved run of the example from ${savedDate(savedRun.generatedAt)}. Its clock times are from then.`
              : `Showing a saved run of this example while the server wakes up; the live answer replaces it in a moment.`}
          </p>
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
              setSavedRun(null);
              setActiveStop(null);
              setSelectedKey("best_overall");
              if (window.location.search)
                window.history.pushState(null, "", window.location.pathname);
            }}
            shareQuery={shareQuery}
            originLabel={origin?.label}
            destinationLabel={destination?.label}
          />
        )}
        {result && !selected && (
          <section className="recommendation empty-result" aria-live="polite">
            <button className="edit-journey" type="button" onClick={() => setResult(null)}>
              <ArrowLeft size={15} aria-hidden="true" />
              Edit journey
            </button>
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
      {/* The map follows the planner in the document so a keyboard reaches
        the journey form first, not the zoom buttons and attribution links.
        Both are positioned, so the order on screen is unchanged. */}
      <section className="map-area">
        <SpatialMap
          origin={origin}
          destination={destination}
          stops={selected?.stops ?? NONE}
          considered={comparedPoints}
          onConsideredSelect={setSelectedKey}
          baselineGeometry={result?.baseline.geometry ?? NONE}
          routeGeometry={selected?.route_geometry ?? NONE}
          legs={selected?.legs ?? NONE}
          preview={preview}
          frame={result ? sheet : "input"}
          activeStop={activeStop}
          activeConsidered={activeConsidered}
          onStopSelect={setActiveStop}
        />
      </section>
    </main>
  );
}

type ParseResponse = {
  status?: string;
  intent?: Intent | null;
  journey_conflicts?: Conflict[];
  unresolved_terms?: string[];
  clarification_question?: string | null;
  detail?: unknown;
};

/* A body that is not JSON - a host's HTML error page, a cold start's
 * placeholder - reads as no body, so the status decides the message. It used
 * to throw a SyntaxError whose text ("Unexpected token '<'") reached the user. */
async function readBody(response: Response): Promise<Record<string, unknown>> {
  try {
    const body: unknown = await response.json();
    return body && typeof body === "object" ? (body as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

function failureMessage(caught: unknown) {
  // fetch rejects with a TypeError when the network or the server is gone.
  if (caught instanceof TypeError)
    return "We couldn’t reach Along just now. Check your connection and try again.";
  return caught instanceof Error ? caught.message : "We couldn’t compare that journey.";
}

function savedDate(value: string) {
  const date = new Date(value);
  return Number.isFinite(date.getTime())
    ? new Intl.DateTimeFormat("en-SG", { day: "numeric", month: "short", year: "numeric" }).format(
        date,
      )
    : "an earlier run";
}

function errorMessage(status: number, body: { detail?: unknown }) {
  if (status === 404) return "We couldn’t find a public-transport route for this journey.";
  if (status === 413) return "That request is too long. Shorten what you typed and try again.";
  if (status === 429) return "Lots of searches just now. Wait a few seconds and try again.";
  if (status === 503) return "Journey checks are busy. Try again shortly.";
  if (status === 504) return "The route check took too long. Please try again.";
  if (status === 422)
    return typeof body.detail === "string"
      ? body.detail
      : "Part of that request needs another look.";
  return "We couldn’t check routes right now. Please try again.";
}
