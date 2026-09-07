"use client";

import { useEffect, useRef } from "react";
import type { Coordinate, ResolvedLocation } from "./LocationField";

type Stop = { display_name: string; coordinate: Coordinate };

export function SpatialMap({ origin, destination, stops = [], baselineGeometry = [], routeGeometry = [], activeStop, onStopSelect }: { origin: ResolvedLocation | null; destination: ResolvedLocation | null; stops?: Stop[]; baselineGeometry?: Coordinate[]; routeGeometry?: Coordinate[]; activeStop?: number | null; onStopSelect?: (index: number) => void }) {
  const elementRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<import("leaflet").Map | null>(null);
  const layerRef = useRef<import("leaflet").LayerGroup | null>(null);
  const markersRef = useRef<import("leaflet").Marker[]>([]);
  const selectionRef = useRef(activeStop);

  useEffect(() => { selectionRef.current = activeStop; markersRef.current.forEach((marker, index) => { marker.getElement()?.classList.toggle("selected-stop", index === activeStop); }); }, [activeStop]);

  useEffect(() => {
    let cancelled = false;
    void import("leaflet").then((L) => {
      if (cancelled || !elementRef.current) return;
      if (!mapRef.current) {
        mapRef.current = L.map(elementRef.current, { zoomControl: false, attributionControl: true }).setView([1.3521, 103.8198], 12);
        mapRef.current.setMaxBounds([[1.144, 103.535], [1.494, 104.502]]);
        L.tileLayer("https://www.onemap.gov.sg/maps/tiles/GreyLite/{z}/{x}/{y}.png", { detectRetina: true, minZoom: 11, maxZoom: 19, attribution: '<a href="https://www.onemap.gov.sg/" target="_blank" rel="noopener noreferrer">OneMap</a> © contributors | <a href="https://www.sla.gov.sg/" target="_blank" rel="noopener noreferrer">Singapore Land Authority</a>' }).addTo(mapRef.current);
        L.control.zoom({ position: "bottomright" }).addTo(mapRef.current);
      }
      layerRef.current?.remove();
      const layer = L.layerGroup().addTo(mapRef.current); layerRef.current = layer;
      const points = [origin, ...stops, destination].filter(Boolean).map((item) => (item as ResolvedLocation | Stop).coordinate);
      const baselinePoints = baselineGeometry.length > 1 ? baselineGeometry : origin && destination ? [origin.coordinate, destination.coordinate] : [];
      if (baselinePoints.length > 1) L.polyline(baselinePoints.map((point) => [point.latitude, point.longitude]), { color: "#64748b", weight: 4, dashArray: "8 8", opacity: .55 }).addTo(layer);
      const recommendedPoints = routeGeometry.length > 1 ? routeGeometry : points;
      if (recommendedPoints.length > 1 && stops.length) L.polyline(recommendedPoints.map((point) => [point.latitude, point.longitude]), { color: "#0d6b57", weight: 5, opacity: .9 }).addTo(layer);
      const marker = (coordinate: Coordinate, kind: string, label: string, glyph: string) => L.marker([coordinate.latitude, coordinate.longitude], { icon: L.divIcon({ className: `along-marker ${kind}`, html: `<span>${glyph}</span>`, iconSize: [30, 30], iconAnchor: [15, 15] }) }).bindTooltip(label, { direction: "top", offset: [0, -12] }).addTo(layer);
      if (origin) marker(origin.coordinate, "origin", origin.label, "A");
      markersRef.current = stops.map((stop, index) => {
        const item = marker(stop.coordinate, "stop", stop.display_name, `${index + 1}`);
        item.getElement()?.setAttribute("aria-label", `Show stop ${index + 1}: ${stop.display_name}`);
        item.getElement()?.classList.toggle("selected-stop", index === selectionRef.current);
        item.on("click", () => onStopSelect?.(index));
        return item;
      });
      if (destination) marker(destination.coordinate, "destination", destination.label, "B");
      const framingPoints = [...points, ...baselinePoints, ...recommendedPoints];
      const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      const compact = window.innerWidth <= 820;
      if (origin && !destination && !stops.length) {
        if (reduceMotion) mapRef.current.setView([origin.coordinate.latitude, origin.coordinate.longitude], 14);
        else mapRef.current.flyTo([origin.coordinate.latitude, origin.coordinate.longitude], 14, { duration: .65 });
      } else if (framingPoints.length > 1) {
        const bounds = L.latLngBounds(framingPoints.map((point) => [point.latitude, point.longitude]));
        const options = {
          paddingTopLeft: compact ? L.point(42, 82) : L.point(470, 88),
          paddingBottomRight: compact ? L.point(42, stops.length ? 390 : 330) : L.point(72, 72),
          maxZoom: 15,
          animate: !reduceMotion,
          duration: .75,
        };
        if (reduceMotion) mapRef.current.fitBounds(bounds, options);
        else mapRef.current.flyToBounds(bounds, options);
      }
      window.setTimeout(() => mapRef.current?.invalidateSize(), 50);
    });
    return () => { cancelled = true; };
  }, [origin, destination, stops, baselineGeometry, routeGeometry, onStopSelect]);

  useEffect(() => () => { mapRef.current?.remove(); mapRef.current = null; }, []);
  return <div className="map" ref={elementRef} role="region" aria-label="Journey map" />;
}
