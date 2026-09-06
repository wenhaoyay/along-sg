"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { ArrowRight, ChevronRight, Info, Search } from "lucide-react";

import { CatalogCategory, DiscoveryPalette, DiscoverySelection } from "./components/DiscoveryPalette";
import { LocationField, ResolvedLocation } from "./components/LocationField";
import { deduplicatedAlternatives, RecommendationPanel, type Recommendation, type Result } from "./components/RecommendationPanel";
import { SpatialMap } from "./components/SpatialMap";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";
const QUICK_NEEDS = [["fast_food", "Food"], ["coffee", "Coffee"], ["bubble_tea", "Bubble tea"], ["groceries", "Groceries"], ["pharmacy", "Pharmacy"]] as const;

type OpenNeed = { raw_text: string; inferred_type: string; category_hint?: string | null; resolution_status: string };
type IntentErrand = { category: string; required: boolean; exact_brand?: string | null; preferred_brand?: string | null; exact_place?: string | null; substitutes_allowed: boolean; discovery_concept?: string | null; discovery_category?: string | null; open_need?: OpenNeed | null };
type Intent = { schema_version: "1.0"; original_text: string; required_errands: IntentErrand[]; optional_errands: IntentErrand[]; preferences: { walking_tolerance: string; transfer_tolerance: string; prefer_consolidated_stops: boolean; urgency: string; max_detour_is_hard?: boolean }; parse_method: "deterministic" | "llm"; confidence: number };
type Conflict = { endpoint: "origin" | "destination"; current_label: string; mentioned_text: string; mentioned_label: string | null; latitude: number | null; longitude: number | null; reason: string };

function context(location: ResolvedLocation) { return { label: location.label, coordinate: location.coordinate }; }

export default function Home() {
  const [origin, setOrigin] = useState<ResolvedLocation | null>(null);
  const [destination, setDestination] = useState<ResolvedLocation | null>(null);
  const [need, setNeed] = useState("");
  const [intent, setIntent] = useState<Intent | null>(null);
  const [categories, setCategories] = useState<CatalogCategory[]>([]);
  const [discoveryOpen, setDiscoveryOpen] = useState(false);
  const [selections, setSelections] = useState<DiscoverySelection[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadingSlow, setLoadingSlow] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [clarification, setClarification] = useState<string | null>(null);
  const [conflict, setConflict] = useState<Conflict | null>(null);
  const [pendingIntent, setPendingIntent] = useState<Intent | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [selectedKey, setSelectedKey] = useState("best_overall");
  const plannerRef = useRef<HTMLElement>(null);

  useEffect(() => { void fetch(`${API_BASE}/api/catalog/categories`).then((response) => response.ok ? response.json() : []).then(setCategories).catch(() => setCategories([])); }, []);
  useEffect(() => { if (!loading) return; const timer = window.setTimeout(() => setLoadingSlow(true), 4500); return () => window.clearTimeout(timer); }, [loading]);
  useEffect(() => { plannerRef.current?.scrollTo({ top: 0, behavior: "auto" }); }, [result]);
  useEffect(() => { if (conflict) plannerRef.current?.scrollTo({ top: 0, behavior: "auto" }); }, [conflict]);

  function structuredIntent(): Intent {
    if (!selections.length) throw new Error("Choose at least one errand.");
    return {
      schema_version: "1.0", original_text: "Structured discovery selection",
      required_errands: selections.map(({ category, item, mode }) => ({
        category, required: true,
        exact_brand: mode === "required" && item?.kind === "brand" ? item.canonical_brand : null,
        preferred_brand: mode === "preferred" && item?.kind === "brand" ? item.canonical_brand : null,
        exact_place: mode === "required" && item?.kind === "place" && !item.coordinate ? item.display_name : null,
        discovery_concept: item?.discovery_concept ?? null,
        substitutes_allowed: mode !== "required",
      })), optional_errands: [],
      preferences: { walking_tolerance: "standard", transfer_tolerance: "standard", prefer_consolidated_stops: selections.length === 2, urgency: "normal" },
      parse_method: "deterministic", confidence: 1,
    };
  }

  async function optimize(interpreted: Intent) {
    if (!origin || !destination) throw new Error("Choose both From and To before searching.");
    const confirmedDiscoveryPlaces = selections.flatMap(({ category, item }) => item?.coordinate ? [{ display_name: item.display_name, coordinate: item.coordinate, category, address: item.address ?? null }] : []);
    const response = await fetch(`${API_BASE}/api/optimize-intent`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ origin: { coordinate: origin.coordinate }, destination: { coordinate: destination.coordinate }, intent: interpreted, confirmed_discovery_places: confirmedDiscoveryPlaces }) });
    const body = await response.json();
    if (!response.ok) throw new Error(errorMessage(response.status, body));
    setIntent(interpreted); setResult(body); setSelectedKey("best_overall");
  }

  async function submit(event: FormEvent) {
    event.preventDefault(); setError(null); setClarification(null); setConflict(null); setLoadingSlow(false); setLoading(true);
    try {
      if (!origin || !destination) throw new Error("Choose both From and To from the suggestions first.");
      if (selections.length) { await optimize(structuredIntent()); return; }
      if (!need.trim()) throw new Error("Tell us what you need, or browse categories.");
      const response = await fetch(`${API_BASE}/api/intent/parse`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: need, origin: context(origin), destination: context(destination) }) });
      const body = await response.json();
      if (!response.ok) throw new Error(errorMessage(response.status, body));
      if (body.journey_conflicts?.length) { setConflict(body.journey_conflicts[0]); setPendingIntent(body.intent); setClarification(body.clarification_question); return; }
      if (body.status !== "resolved" || !body.intent) { setClarification(body.clarification_question ?? "Tell us a little more about the errand."); return; }
      if (body.clarification_question) setClarification(body.clarification_question);
      await optimize(body.intent);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "We couldn’t compare that journey."); }
    finally { setLoading(false); }
  }

  function resolveConflict(action: "keep" | "change") {
    if (!conflict) return;
    if (action === "change" && conflict.mentioned_label && conflict.latitude != null && conflict.longitude != null) {
      const next: ResolvedLocation = { label: conflict.mentioned_label, address: conflict.mentioned_label, entity_type: "place", coordinate: { latitude: conflict.latitude, longitude: conflict.longitude }, confirmed: true };
      if (conflict.endpoint === "origin") setOrigin(next); else setDestination(next);
    }
    if (pendingIntent) { setNeed(pendingIntent.original_text); setIntent(pendingIntent); }
    setConflict(null); setClarification(null);
  }

  function selectQuickNeed(slug: string, label: string) {
    const category = categories.find((item) => item.slug === slug);
    if (!category) { setNeed(label); setSelections([]); return; }
    setNeed(""); setIntent(null); setSelections([{ category: slug, item: null, mode: "any" }]);
  }

  const selected: Recommendation | undefined = result?.recommendations[selectedKey] ?? result?.recommendations.best_overall ?? Object.values(result?.recommendations ?? {})[0];
  const alternatives = useMemo(() => deduplicatedAlternatives(result?.recommendations ?? {}), [result]);

  return <main className={`app-shell ${result ? "has-result" : "input-state"}`}>
    <header className="app-bar">
      <a href="#planner" className="logo" aria-label="Along home"><span aria-hidden="true">A</span><strong>Along</strong></a>
      <div><span className="beta-label">Singapore beta</span><a className="icon-link" href="/privacy"><Info size={17} aria-hidden="true" /><span>Privacy</span></a></div>
    </header>

    <section className="map-area">
      <SpatialMap origin={origin} destination={destination} stops={selected?.stops ?? []} baselineGeometry={result?.baseline.geometry ?? []} routeGeometry={selected?.route_geometry ?? []} />
      {selected && <div className="map-key" aria-label="Map route key"><span><i className="baseline" />Straight</span><span><i className="recommended" />With stop</span></div>}
    </section>

    <aside ref={plannerRef} className={`planner ${result ? "result-mode" : ""}`} id="planner" aria-label={result ? "Recommendation" : "Plan your journey"}>
      <div className="sheet-handle" aria-hidden="true" />
      {!result && <form onSubmit={submit}>
        <div className="planner-intro"><span>Plan a stop</span><h1>Find what you need <br />along the way.</h1><p>Keep your journey. Add a useful stop.</p></div>
        <div className="journey-fields">
          <LocationField key={`origin-${origin?.label ?? "empty"}`} label="From" placeholder="Search starting point" apiBase={API_BASE} value={origin} onChange={(value) => { setOrigin(value); setResult(null); }} allowCurrentLocation />
          <div className="journey-line" aria-hidden="true" />
          <LocationField key={`destination-${destination?.label ?? "empty"}`} label="To" placeholder="Search destination" apiBase={API_BASE} value={destination} onChange={(value) => { setDestination(value); setResult(null); }} />
        </div>

        <label className="need-control"><span>What do you need?</span><div className="need-input-wrap"><Search size={19} aria-hidden="true" /><textarea aria-label="What do you need on the way?" value={need} onChange={(event) => { setNeed(event.target.value); setIntent(null); setSelections([]); }} placeholder="Mee pok, Molly Tea or printer ink" rows={1} maxLength={500} /></div></label>
        {!intent && !selections.length && <div className="quick-needs" aria-label="Popular needs">{QUICK_NEEDS.map(([slug, label]) => <button type="button" key={slug} onClick={() => selectQuickNeed(slug, label)}>{label}</button>)}</div>}

        {(intent || selections.length > 0) && <div className="intent-preview">
          <span>Looking for</span>
          <div>{intent ? [...intent.required_errands, ...intent.optional_errands].map((item) => <span className="intent-token" key={`${item.category}-${item.exact_brand ?? item.preferred_brand ?? "any"}`}>{intentLabel(categories, item)}</span>) : selections.map((item) => <span className="intent-token" key={item.category}>{item.item?.display_name ?? categoryName(categories, item.category)}{item.mode !== "any" ? ` · ${item.mode}` : ""}</span>)}</div>
          <button type="button" onClick={() => { setIntent(null); setSelections([]); }}>Edit</button>
        </div>}

        {clarification && <div className={conflict ? "notice conflict" : "notice"} role="alert"><strong>{conflict ? "Your journey changed" : "A quick check"}</strong><p>{clarification}</p>{conflict && <div className="conflict-actions"><button type="button" onClick={() => resolveConflict("keep")}>Keep {conflict.current_label}</button>{conflict.mentioned_label && <button type="button" onClick={() => resolveConflict("change")}>Use {conflict.mentioned_label}</button>}<button type="button" onClick={() => { if (conflict.endpoint === "origin") setOrigin(null); else setDestination(null); setConflict(null); }}>Edit {conflict.endpoint}</button></div>}</div>}
        {error && <div className="notice error" role="alert"><strong>One more thing</strong><p>{error}</p></div>}

        {discoveryOpen && <DiscoveryPalette apiBase={API_BASE} categories={categories} selections={selections} onClose={() => setDiscoveryOpen(false)} onChange={(items) => { setSelections(items); setNeed(""); setIntent(null); }} />}

        <button className="find-button" type="submit" disabled={loading || !origin || !destination}><span>{loading ? loadingSlow ? "Checking live public-transport routes…" : need.trim() ? `Looking for ${need.trim()}…` : "Finding stops along your route…" : "Find best stop"}</span>{loading ? <span className="button-spinner" /> : <ArrowRight size={19} aria-hidden="true" />}</button>
        {!discoveryOpen && <button className="catalog-toggle" type="button" aria-expanded="false" onClick={() => setDiscoveryOpen(true)}><span>Browse categories</span><ChevronRight size={17} aria-hidden="true" /></button>}
      </form>}

      {result && selected && <RecommendationPanel recommendation={selected} result={result} alternatives={alternatives} selectedKey={selectedKey} onSelect={setSelectedKey} onEdit={() => { setResult(null); setSelectedKey("best_overall"); }} />}
      {result && !selected && <section className="recommendation empty-result" aria-live="polite"><button className="edit-journey" type="button" onClick={() => setResult(null)}><ArrowRight size={15} aria-hidden="true" />Edit journey</button><span>Try another way</span><h1>No easy match</h1><p>{result.message ?? "Try a broader category or loosen a brand or time preference."}</p><button className="find-button" type="button" onClick={() => { setDiscoveryOpen(true); setResult(null); }}>Browse options<ArrowRight size={18} aria-hidden="true" /></button></section>}
    </aside>
  </main>;
}

function categoryName(categories: CatalogCategory[], slug: string) { return categories.find((item) => item.slug === slug)?.name ?? slug.replaceAll("_", " "); }
function intentLabel(categories: CatalogCategory[], item: IntentErrand) {
  const label = item.open_need?.raw_text ?? item.exact_brand ?? item.preferred_brand ?? item.exact_place ?? categoryName(categories, item.category);
  if (item.open_need?.inferred_type === "product" && item.discovery_category) return `${label} · ${categoryName(categories, item.discovery_category)}`;
  return label;
}
function errorMessage(status: number, body: { detail?: unknown }) { if (status === 404) return "We couldn’t find a public-transport route for this journey."; if (status === 429 || status === 503) return "Journey checks are busy. Try again shortly."; if (status === 504) return "The route check took too long. Please try again."; if (status === 422) return typeof body.detail === "string" ? body.detail : "Part of that request needs another look."; return "We couldn’t check routes right now. Please try again."; }
