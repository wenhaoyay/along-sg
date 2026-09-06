"use client";

import { KeyboardEvent, useEffect, useMemo, useState } from "react";
import { ArrowLeft, Check, LoaderCircle, Search, Store, Tag, X } from "lucide-react";

export type CatalogCategory = { slug: string; name: string; parent_slug: string | null; outlet_count: number };
export type CatalogItem = { display_name: string; kind: "category" | "brand" | "place"; canonical_brand: string | null; categories: string[]; outlet_count: number; example_location: string | null; coordinate?: { latitude: number; longitude: number }; address?: string | null; semantic_type?: string; discovery_concept?: string; suitability?: string };
export type SelectionMode = "any" | "preferred" | "required";
export type DiscoverySelection = { category: string; item: CatalogItem | null; mode: SelectionMode };

const POPULAR = ["fast_food", "bubble_tea", "coffee", "groceries", "pharmacy", "banking", "clothing", "parcel"];

export function DiscoveryPalette({ apiBase, categories, selections, onChange, onClose }: { apiBase: string; categories: CatalogCategory[]; selections: DiscoverySelection[]; onChange: (items: DiscoverySelection[]) => void; onClose: () => void }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<CatalogItem[]>([]);
  const [searching, setSearching] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const categoryBySlug = useMemo(() => new Map(categories.map((item) => [item.slug, item])), [categories]);

  useEffect(() => {
    if (query.trim().length < 2) return;
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      setSearching(true);
      try {
        const [catalogResponse, discoveryResponse] = await Promise.all([
          fetch(`${apiBase}/api/catalog/search?q=${encodeURIComponent(query)}&limit=12`, { signal: controller.signal }),
          fetch(`${apiBase}/api/discovery/needs?q=${encodeURIComponent(query)}&limit=8`, { signal: controller.signal }),
        ]);
        const catalogItems = catalogResponse.ok ? await catalogResponse.json() : [];
        const discovery = discoveryResponse.ok ? await discoveryResponse.json() : null;
        const discoveryItems: CatalogItem[] = [];
        if (discovery?.canonical_concept && discovery?.category && discovery?.places?.length) discoveryItems.push({ display_name: discovery.canonical_concept, kind: "category", canonical_brand: null, categories: [discovery.category], outlet_count: discovery.places.length, example_location: humanType(discovery.semantic_type), semantic_type: discovery.semantic_type, discovery_concept: discovery.canonical_concept });
        for (const place of discovery?.places ?? []) discoveryItems.push({ display_name: place.display_name, kind: "place", canonical_brand: null, categories: [discovery.category ?? place.category].filter(Boolean), outlet_count: 1, example_location: place.mall_or_hub ?? place.address ?? null, coordinate: place.coordinate, address: place.address, semantic_type: discovery.semantic_type, discovery_concept: discovery.canonical_concept, suitability: place.suitability });
        const seen = new Set<string>();
        const items = [...discoveryItems, ...catalogItems].filter((item) => { const key = `${item.kind}:${item.display_name.toLowerCase()}:${item.example_location ?? ""}`; if (seen.has(key)) return false; seen.add(key); return true; }).slice(0, 12);
        setResults(items); setActiveIndex(items.length ? 0 : -1);
      } catch (error) {
        if ((error as Error).name !== "AbortError") { setResults([]); setActiveIndex(-1); }
      } finally { setSearching(false); }
    }, 250);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [apiBase, query]);

  function choose(item: CatalogItem) {
    const category = item.kind === "category" ? item.categories[0] : item.categories.find((slug) => categoryBySlug.has(slug)) ?? item.categories[0];
    if (!category) return;
    const next: DiscoverySelection = { category, item: item.kind === "category" && !item.discovery_concept ? null : item, mode: item.kind === "category" ? "any" : item.kind === "place" ? "required" : "preferred" };
    const withoutCategory = selections.filter((selection) => selection.category !== category);
    onChange([...withoutCategory, next].slice(-2));
    setQuery(""); setResults([]); setActiveIndex(-1);
  }

  function chooseCategory(slug: string) {
    const category = categoryBySlug.get(slug);
    if (!category) return;
    choose({ display_name: category.name, kind: "category", canonical_brand: null, categories: [slug], outlet_count: category.outlet_count, example_location: null });
  }

  function setMode(index: number, mode: SelectionMode) {
    onChange(selections.map((selection, itemIndex) => itemIndex === index ? { ...selection, mode, item: mode === "any" && !selection.item?.discovery_concept ? null : selection.item } : selection));
  }

  function onSearchKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape") { if (query) { setQuery(""); setResults([]); } else onClose(); return; }
    if (!results.length) return;
    if (event.key === "ArrowDown") { event.preventDefault(); setActiveIndex((index) => (index + 1) % results.length); }
    if (event.key === "ArrowUp") { event.preventDefault(); setActiveIndex((index) => index <= 0 ? results.length - 1 : index - 1); }
    if (event.key === "Enter" && activeIndex >= 0) { event.preventDefault(); choose(results[activeIndex]); }
  }

  const resultListId = "catalog-discovery-results";
  return <section className="discovery" aria-label="Find something" data-testid="discovery-palette">
    <div className="discovery-title">
      <button type="button" className="discovery-back" onClick={onClose} aria-label="Close category browser"><ArrowLeft size={18} /></button>
      <div><span>Find something</span><p>Choose up to two needs</p></div>
      <span className="selection-count">{selections.length}/2</span>
    </div>
    <label className="discovery-search"><Search size={18} aria-hidden="true" /><input autoFocus value={query} onChange={(event) => { const value = event.target.value; setQuery(value); if (value.trim().length < 2) { setResults([]); setActiveIndex(-1); setSearching(false); } }} onKeyDown={onSearchKeyDown} placeholder="Brands, shops or categories" aria-label="Search brands, shops or categories" aria-controls={resultListId} aria-autocomplete="list" aria-activedescendant={activeIndex >= 0 ? `${resultListId}-${activeIndex}` : undefined} />{searching && <LoaderCircle className="spinner-icon" size={17} aria-label="Searching catalog" />}</label>
    {!query && <div className="popular"><span>Popular</span><div>{POPULAR.map((slug) => categoryBySlug.has(slug) && <button type="button" key={slug} onClick={() => chooseCategory(slug)} disabled={selections.length >= 2 && !selections.some((item) => item.category === slug)}>{categoryBySlug.get(slug)?.name}</button>)}</div></div>}
    {query.trim().length >= 2 && !searching && <div className="discovery-results" id={resultListId} role="listbox">
      {results.map((item, index) => <button type="button" role="option" id={`${resultListId}-${index}`} aria-selected={activeIndex === index} className={activeIndex === index ? "active" : ""} key={`${item.kind}-${item.display_name}-${item.example_location ?? item.address ?? index}`} onMouseEnter={() => setActiveIndex(index)} onClick={() => choose(item)}>
        <span className={`result-icon ${item.kind}`} aria-hidden="true">{item.kind === "category" ? <Tag size={17} /> : <Store size={17} />}</span>
        <span><strong>{item.display_name}</strong><small>{item.discovery_concept && item.kind === "category" ? `${humanType(item.semantic_type ?? "concept")} · ${item.outlet_count.toLocaleString()} matching place${item.outlet_count === 1 ? "" : "s"}` : item.kind === "category" ? `${item.outlet_count.toLocaleString()} places` : `${item.outlet_count.toLocaleString()} outlet${item.outlet_count === 1 ? "" : "s"}${item.example_location ? ` · ${item.example_location}` : ""}${item.suitability === "category_likely" ? " · Stock not guaranteed" : ""}`}</small></span>
      </button>)}
      {!results.length && <p className="empty-search">No reliable place yet. You can still search the free-form request, try a broader category, or edit the term.</p>}
    </div>}
    {!!selections.length && <div className="selected-needs">
      {selections.map((selection, index) => <article key={`${selection.category}-${index}`}>
        <div><span>{categoryBySlug.get(selection.category)?.name ?? selection.category.replaceAll("_", " ")}</span><strong>{selection.item?.display_name ?? `Any ${categoryBySlug.get(selection.category)?.name.toLowerCase() ?? selection.category}`}</strong></div>
        <button className="remove-selection" type="button" aria-label={`Remove ${selection.category}`} onClick={() => onChange(selections.filter((_, itemIndex) => itemIndex !== index))}><X size={16} /></button>
        <div className="mode-picker" aria-label="Preference strength">{(["any", "preferred", "required"] as SelectionMode[]).map((mode) => {
          const disabled = (mode !== "any" && !selection.item) || (mode === "preferred" && selection.item?.kind === "place");
          return <button type="button" key={mode} disabled={disabled} className={selection.mode === mode ? "active" : ""} onClick={() => setMode(index, mode)}>{selection.mode === mode && <Check size={12} aria-hidden="true" />}{mode === "any" ? "Any" : mode === "preferred" ? "Preferred" : "Required"}</button>;
        })}</div>
      </article>)}
    </div>}
  </section>;
}

function humanType(value: string) { return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase()); }
