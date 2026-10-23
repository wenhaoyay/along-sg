"use client";

import { KeyboardEvent, useEffect, useId, useRef, useState } from "react";
import { Check, LocateFixed, LoaderCircle, MapPin } from "lucide-react";

export type Coordinate = { latitude: number; longitude: number };
export type ResolvedLocation = {
  label: string;
  address?: string | null;
  postal_code?: string | null;
  entity_type: string;
  coordinate: Coordinate;
  confirmed: boolean;
  confidence?: "exact" | "strong" | "likely" | "ambiguous" | "unresolved";
  subtitle?: string | null;
};

type Props = {
  label: string;
  placeholder: string;
  apiBase: string;
  value: ResolvedLocation | null;
  onChange: (value: ResolvedLocation | null) => void;
  allowCurrentLocation?: boolean;
};

export function LocationField({
  label,
  placeholder,
  apiBase,
  value,
  onChange,
  allowCurrentLocation,
}: Props) {
  const id = useId();
  const [query, setQuery] = useState(value?.label ?? "");
  const [results, setResults] = useState<ResolvedLocation[]>([]);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [status, setStatus] = useState<
    "empty" | "typing" | "searching" | "suggestions" | "not_found" | "no_location" | "resolved"
  >(value ? "resolved" : "empty");
  const [locating, setLocating] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  /* Follow a value set from outside (swap, an example, a conflict resolved)
   * without remounting. The field used to be keyed on its value, so the first
   * keystroke in a chosen place cleared the value, changed the key, and
   * remounted an empty field with focus gone: editing "Punggol MRT" typed
   * nothing at all. A value cleared by our own typing leaves the text alone;
   * one cleared from outside empties the field only if it still shows it. */
  const [shown, setShown] = useState(value);
  if (value !== shown) {
    setShown(value);
    if (value) {
      setQuery(value.label);
      setResults([]);
      setActiveIndex(-1);
      setStatus("resolved");
    } else if (shown && query === shown.label) {
      setQuery("");
      setStatus("empty");
    }
  }

  useEffect(() => {
    if ((value && query === value.label) || query.trim().length < 2) return;
    const timer = window.setTimeout(async () => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      try {
        const response = await fetch(
          `${apiBase}/api/geocode?q=${encodeURIComponent(query)}&limit=6`,
          { signal: controller.signal },
        );
        if (!response.ok) throw new Error("geocode failed");
        const body = await response.json();
        const matches = (body.results ?? []) as ResolvedLocation[];
        setResults(matches);
        setActiveIndex(matches.length ? 0 : -1);
        setStatus(matches.length ? "suggestions" : "not_found");
      } catch (error) {
        if ((error as Error).name !== "AbortError") {
          setResults([]);
          setActiveIndex(-1);
          setStatus("not_found");
        }
      }
    }, 350);
    return () => window.clearTimeout(timer);
  }, [apiBase, query, value]);

  function type(next: string) {
    setQuery(next);
    setResults([]);
    setActiveIndex(-1);
    setStatus(next.trim().length >= 2 ? "searching" : next ? "typing" : "empty");
    if (!value || next !== value.label) onChange(null);
  }

  function select(match: ResolvedLocation) {
    setQuery(match.label);
    setResults([]);
    setActiveIndex(-1);
    setStatus("resolved");
    onChange({ ...match, confirmed: true });
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (status !== "suggestions" || !results.length) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((index) => (index + 1) % results.length);
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((index) => (index <= 0 ? results.length - 1 : index - 1));
    }
    if (event.key === "Enter" && activeIndex >= 0) {
      event.preventDefault();
      select(results[activeIndex]);
    }
    if (event.key === "Escape") {
      setResults([]);
      setActiveIndex(-1);
      setStatus(query ? "typing" : "empty");
    }
  }

  function close() {
    if (status !== "suggestions") return;
    setResults([]);
    setActiveIndex(-1);
    setStatus(query ? "typing" : "empty");
  }

  function locate() {
    if (!navigator.geolocation) {
      setStatus("no_location");
      return;
    }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => {
        const current: ResolvedLocation = {
          label: "Current location",
          address: "Device position",
          entity_type: "current_location",
          coordinate: { latitude: coords.latitude, longitude: coords.longitude },
          confirmed: true,
        };
        setQuery(current.label);
        setStatus("resolved");
        onChange(current);
        setLocating(false);
      },
      () => {
        setStatus("no_location");
        setLocating(false);
      },
      { timeout: 8000, maximumAge: 300000 },
    );
  }

  const listboxId = `${id}-results`;
  return (
    <div className={`location-control state-${status}`}>
      <div className="field-heading">
        <label htmlFor={id}>{label}</label>
        {allowCurrentLocation && (
          <button type="button" className="use-current" onClick={locate} disabled={locating}>
            <LocateFixed size={14} aria-hidden="true" />
            {locating ? "Locating" : "Current"}
          </button>
        )}
      </div>
      <div className="location-input-wrap">
        <span
          className={`location-glyph ${label === "To" ? "destination" : "origin"}`}
          aria-hidden="true"
        >
          <MapPin size={17} />
        </span>
        {/* Named by its visible label ("From", "To"): a hidden "Origin" that
          differs from what is on screen fails voice control and WCAG 2.5.3. */}
        <input
          id={id}
          value={query}
          placeholder={placeholder}
          autoComplete="off"
          role="combobox"
          onChange={(event) => type(event.target.value)}
          onKeyDown={handleKeyDown}
          onBlur={close}
          aria-autocomplete="list"
          aria-controls={listboxId}
          aria-expanded={status === "suggestions"}
          aria-activedescendant={activeIndex >= 0 ? `${listboxId}-${activeIndex}` : undefined}
        />
        {status === "searching" && (
          <LoaderCircle className="spinner-icon" size={17} aria-label="Searching Singapore" />
        )}
        {status === "resolved" && (
          <span className="confirmed" aria-label="Location selected">
            <Check size={16} />
          </span>
        )}
      </div>
      {status === "resolved" && value && (
        <p className="resolved-detail">
          {value.subtitle ??
            (value.address && value.address !== value.label
              ? value.address
              : humanEntity(value.entity_type))}
        </p>
      )}
      {status === "suggestions" &&
        (results.length > 1 || results.some((item) => item.confidence === "ambiguous")) && (
          <p className="ambiguous-prompt">Pick the one you mean</p>
        )}
      {/* The options are the listbox's own rows, driven from the input: a
        button inside each was a Tab stop of its own and read as "option,
        button". Pressing keeps focus in the input, so blur can close it. */}
      {status === "suggestions" && (
        <ul
          className="location-results"
          id={listboxId}
          role="listbox"
          aria-label={`${label} suggestions`}
        >
          {results.map((match, index) => (
            <li
              role="option"
              aria-selected={activeIndex === index}
              id={`${listboxId}-${index}`}
              key={`${match.label}-${index}`}
              className={activeIndex === index ? "active" : ""}
              onMouseEnter={() => setActiveIndex(index)}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => select(match)}
            >
              <span className="suggestion-icon" aria-hidden="true">
                <MapPin size={16} />
              </span>
              <span>
                <strong>{match.label}</strong>
                <small>
                  {match.subtitle ?? match.address ?? humanEntity(match.entity_type)}
                  {match.postal_code ? ` · ${match.postal_code}` : ""}
                </small>
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className="sr-only" role="status">
        {status === "suggestions"
          ? `${results.length} ${results.length === 1 ? "suggestion" : "suggestions"}`
          : ""}
      </p>
      {status === "not_found" && (
        <p className="field-error">
          No match for “{query}”. Try a station, building, postal code or address.
        </p>
      )}
      {status === "no_location" && (
        <p className="field-error">
          We couldn’t get your location. Type a station, building or postal code instead.
        </p>
      )}
    </div>
  );
}

function humanEntity(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}
