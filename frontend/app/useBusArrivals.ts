"use client";

import { useEffect, useMemo, useState } from "react";

export type ArrivalEstimate = {
  minutes: number;
  arrival_time: string;
  live: boolean;
  load: "SEA" | "SDA" | "LSD" | null;
  wheelchair_accessible: boolean;
  vehicle_type: "SD" | "DD" | "BD" | null;
};

export type StopArrivals = {
  stop_code: string;
  checked_at: string;
  services: Array<{ service_no: string; operator: string | null; estimates: ArrivalEstimate[] }>;
  source: string;
  attribution: string | null;
  stop_name?: string | null;
  /** Whether this service is scheduled to be calling here now. Null means the
   *  timetable is not held, which is not the same as "not running" and must
   *  never be rendered as it. */
  in_operation?: boolean | null;
  operating_hours?: string | null;
};

export type Boarding = { stopCode: string; service: string };

/** A BusStopCode is exactly five digits. A rail leg carries a station code
 *  (NE17), which is not a bus stop and must never be sent as one. */
export function isBusStopCode(code: string | null | undefined): code is string {
  return typeof code === "string" && /^\d{5}$/.test(code);
}

/* How close to boarding a live arrival is worth showing.
 *
 * This is the whole honesty question for the feature. "Next 95 in 4 min" is
 * useful when you are about to walk to the stop and actively misleading when
 * the plan has you boarding in two hours - the number would be real, current,
 * and about a bus you will not be on. Journeys planned for later therefore
 * show no live times at all rather than times that quietly refer to now.
 *
 * The lower bound covers a departure a minute or two in the past, which is
 * normal while a result sits on screen. */
const HORIZON_MINUTES = 30;
const GRACE_MINUTES = 3;

export function boardingIsImminent(departure: string | null | undefined, now = Date.now()) {
  if (!departure) return false;
  const minutes = (new Date(departure).getTime() - now) / 60_000;
  return minutes >= -GRACE_MINUTES && minutes <= HORIZON_MINUTES;
}

/** The feed refreshes every 20 seconds; polling faster spends someone's quota
 *  to redraw the same number. */
const POLL_MS = 30_000;

/**
 * Arrivals for a set of stop codes, keyed by code.
 *
 * Returns an empty map rather than throwing: bus times are an enrichment, and
 * a plan that renders without them is still a correct plan. A stop that is
 * fetched and answers with nothing is recorded as an empty service list, which
 * is how the caller tells "no buses due" from "not asked".
 */
export function useBusArrivals(apiBase: string, boardings: Boarding[]) {
  /* Keyed by stop and service together.
   *
   * The service has to reach the endpoint, or it cannot say whether that
   * service is running here - which is the difference between "nothing due"
   * and "stopped for the night". It also narrows LTA's answer from every route
   * at the stop to the one being ridden. */
  const key = boardings.map((item) => `${item.stopCode}|${item.service}`).join(",");
  const [arrivals, setArrivals] = useState<Record<string, StopArrivals>>({});

  useEffect(() => {
    const codes = key ? key.split(",") : [];
    if (!codes.length) return;
    let cancelled = false;
    const controller = new AbortController();

    async function load() {
      const results = await Promise.all(
        codes.map(async (pair) => {
          const [code, service] = pair.split("|");
          try {
            const query = new URLSearchParams({ stop_code: code, service });
            const response = await fetch(`${apiBase}/api/bus-arrivals?${query}`, {
              signal: controller.signal,
            });
            if (!response.ok) return null;
            return [pair, (await response.json()) as StopArrivals] as const;
          } catch {
            // Offline, aborted, or the provider is down. The timeline is
            // complete without this.
            return null;
          }
        }),
      );
      if (cancelled) return;
      const next: Record<string, StopArrivals> = {};
      results.forEach((result) => {
        if (result) next[result[0]] = result[1];
      });
      setArrivals(next);
    }

    void load();
    const timer = window.setInterval(() => void load(), POLL_MS);
    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(timer);
    };
  }, [apiBase, key]);

  /* Restricted to what is currently being asked for, rather than cleared when
   * the request changes. Selecting a different plan swaps the stop codes, and
   * returning the raw store would show the previous plan's bus times against
   * the new one until the next fetch resolved. */
  return useMemo(() => {
    const wanted = new Set(key ? key.split(",") : []);
    return Object.fromEntries(
      Object.entries(arrivals).filter(([code]) => wanted.has(code)),
    ) as Record<string, StopArrivals>;
  }, [arrivals, key]);
}

/** The lookup key the hook returns its results under. */
export function boardingKey(stopCode: string, service: string) {
  return `${stopCode}|${service}`;
}
