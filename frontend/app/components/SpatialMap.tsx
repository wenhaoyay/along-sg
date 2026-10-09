"use client";

import { useEffect, useRef } from "react";
import { lineColor } from "../lineColors";
import type { Coordinate, ResolvedLocation } from "./LocationField";
import type { Leg } from "./journey/types";

type Stop = { display_name: string; coordinate: Coordinate };

/* OneMap publishes five basemaps. GreyLite, used first, drew faint outlines and
 * no stations. Default drew them, along with orange expressways, saturated
 * parks, golf courses and pink restricted-area hatching, and the route - one
 * dark-green line - disappeared into it beside the East West line.
 *
 * Grey is the middle: it keeps every station, the MRT lines in their own
 * colours and the street names, and mutes the land and water, so the only
 * saturated thing on the map is the journey. Night is a real dark basemap. */
const BASEMAP = {
  light: "https://www.onemap.gov.sg/maps/tiles/Grey/{z}/{x}/{y}.png",
  dark: "https://www.onemap.gov.sg/maps/tiles/Night/{z}/{x}/{y}.png",
} as const;

const currentScheme = (): "light" | "dark" =>
  document.documentElement.dataset.theme === "dark" ? "dark" : "light";

// One breakpoint for the whole app: from here down the planner is a sheet.
export const COMPACT_MAX_WIDTH = 767;

/** A candidate that was routed and lost. Drawn so the map can show the
 *  comparison it made rather than a single line to be taken on trust. */
type Considered = {
  /** Stable across re-renders, because highlighting is driven from two
   *  different lists in the panel and index alone would not distinguish them. */
  key: string;
  display_name: string;
  coordinate: Coordinate;
  extra_transport_minutes: number;
  /** The second stop of a two-stop option: same decision, so it carries no
   *  label of its own. */
  secondary?: boolean;
};

type Preview = { origin: ResolvedLocation; destination: ResolvedLocation };

export function SpatialMap({
  origin,
  destination,
  stops = [],
  considered = [],
  baselineGeometry = [],
  routeGeometry = [],
  legs = [],
  preview = null,
  frame,
  activeStop,
  activeConsidered,
  onStopSelect,
  onConsideredSelect,
}: {
  origin: ResolvedLocation | null;
  destination: ResolvedLocation | null;
  stops?: Stop[];
  considered?: Considered[];
  baselineGeometry?: Coordinate[];
  routeGeometry?: Coordinate[];
  /** The plan's legs; with their own geometry each ride is drawn in its
   *  line's colour. */
  legs?: Leg[];
  /** An example journey to show on the empty map. */
  preview?: Preview | null;
  /** Changes when the planner's size on screen does, so the route is
   *  reframed into the space the sheet leaves. */
  frame?: string;
  activeStop?: number | null;
  activeConsidered?: string | null;
  onStopSelect?: (index: number) => void;
  onConsideredSelect?: (key: string) => void;
}) {
  const elementRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<import("leaflet").Map | null>(null);
  const layerRef = useRef<import("leaflet").LayerGroup | null>(null);
  const markersRef = useRef<import("leaflet").Marker[]>([]);
  const allMarkersRef = useRef<import("leaflet").Marker[]>([]);
  const consideredRef = useRef<import("leaflet").Marker[]>([]);
  const selectionRef = useRef(activeStop);
  const tileRef = useRef<import("leaflet").TileLayer | null>(null);
  const framingRef = useRef<(animate: boolean) => void>(() => {});

  useEffect(() => {
    selectionRef.current = activeStop;
    markersRef.current.forEach((marker, index) => {
      marker.getElement()?.classList.toggle("selected-stop", index === activeStop);
    });
  }, [activeStop]);

  // Pointing at a row in the comparison lifts its marker out of the dimmed
  // set, which is what makes the rows on the left and the pins on the right
  // into one thing.
  useEffect(() => {
    consideredRef.current.forEach((marker) => {
      const element = marker.getElement();
      element?.classList.toggle("highlighted", element?.dataset.comparedKey === activeConsidered);
    });
  }, [activeConsidered]);

  /* The basemap follows the theme, and the theme can change after the map is
   * built. Watching the data-theme attribute rather than subscribing to the
   * theme store keeps the map from importing it - the attribute is already the
   * contract, since the blocking script in the document head stamps it before
   * first paint. */
  useEffect(() => {
    const root = document.documentElement;
    const observer = new MutationObserver(() => {
      tileRef.current?.setUrl(BASEMAP[currentScheme()]);
    });
    observer.observe(root, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, []);

  // The sheet changed size: frame the same route into the new space. Not on
  // the first result, which the layer rebuild below already frames.
  const frameRef = useRef(frame);
  useEffect(() => {
    const previous = frameRef.current;
    frameRef.current = frame;
    if (previous === frame || previous === "input" || frame === "input") return;
    const timer = window.setTimeout(() => framingRef.current(true), 260);
    return () => window.clearTimeout(timer);
  }, [frame]);

  useEffect(() => {
    let cancelled = false;
    void import("leaflet").then((L) => {
      if (cancelled || !elementRef.current) return;
      if (!mapRef.current) {
        mapRef.current = L.map(elementRef.current, {
          zoomControl: false,
          attributionControl: true,
        }).setView([1.3521, 103.8198], 12);
        /* On a phone the result sheet covers the lower half of the map, so a
         * route has to be framed in the top half - which for a trip along the
         * south coast means the map centre sits well south of Singapore. With
         * the island's own bounds as the limit, Leaflet refused that pan and
         * left the route under the sheet. The south edge leaves room for it. */
        const compactLayout = window.innerWidth <= COMPACT_MAX_WIDTH;
        mapRef.current.setMaxBounds([
          [compactLayout ? 0.9 : 1.144, 103.535],
          [1.494, 104.502],
        ]);
        tileRef.current = L.tileLayer(BASEMAP[currentScheme()], {
          detectRetina: true,
          minZoom: 11,
          maxZoom: 19,
          attribution:
            '<a href="https://www.onemap.gov.sg/" target="_blank" rel="noopener noreferrer">OneMap</a> © contributors | <a href="https://www.sla.gov.sg/" target="_blank" rel="noopener noreferrer">Singapore Land Authority</a>',
        }).addTo(mapRef.current);
        /* OneMap's tiles at zoom 11-12 carry a printed "INSET - Not to Scale"
         * box for Pedra Branca in the sea off East Coast, which reads as a
         * glitch on an interactive map. From zoom 13 the tiles are clean, so
         * at the overview zooms the box is painted over in the sea's own
         * colour (set per theme in CSS) on a pane just above the tiles. The
         * box is drawn at a fixed pixel size, so it covers different ground
         * at each zoom; the bounds were measured from the tiles themselves. */
        mapRef.current.createPane("inset-mask").style.zIndex = "250";
        const insetBounds: Record<number, [[number, number], [number, number]]> = {
          11: [
            [1.1405, 103.963],
            [1.2435, 104.103],
          ],
          12: [
            [1.2355, 103.908],
            [1.3015, 103.999],
          ],
        };
        const insetMask = L.rectangle(insetBounds[12], {
          pane: "inset-mask",
          stroke: false,
          fillOpacity: 1,
          interactive: false,
          className: "inset-mask",
        });
        const map = mapRef.current;
        const syncInsetMask = () => {
          // Keyed by the zoom of the tiles drawn, not the map's: with
          // detectRetina a high-density screen draws tiles one level up.
          const tileZoom = Math.round(map.getZoom()) + (L.Browser.retina ? 1 : 0);
          const bounds = insetBounds[tileZoom];
          if (!bounds) {
            insetMask.remove();
            return;
          }
          insetMask.setBounds(L.latLngBounds(bounds)).addTo(map);
        };
        map.on("zoomend", syncInsetMask);
        syncInsetMask();
        L.control.zoom({ position: "bottomright" }).addTo(mapRef.current);
        // Overlap is a pixel question, so it has to be recomputed whenever the
        // projection moves. Registered once here, not per data change.
        mapRef.current.on("zoomend moveend", () =>
          spreadColliding(mapRef.current, allMarkersRef.current),
        );
      }
      layerRef.current?.remove();
      const layer = L.layerGroup().addTo(mapRef.current);
      layerRef.current = layer;
      const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      const points = [origin, ...stops, destination]
        .filter(Boolean)
        .map((item) => (item as ResolvedLocation | Stop).coordinate);
      const latLngs = (line: Coordinate[]) =>
        line.map((point) => [point.latitude, point.longitude] as [number, number]);

      const baselinePoints =
        baselineGeometry.length > 1
          ? baselineGeometry
          : origin && destination
            ? [origin.coordinate, destination.coordinate]
            : [];
      // A ghost of the direct trip: there to be compared with, not followed.
      if (baselinePoints.length > 1)
        L.polyline(latLngs(baselinePoints), {
          className: "route-direct",
          weight: 4,
          dashArray: "2 9",
          lineCap: "round",
          interactive: false,
        }).addTo(layer);

      /* The plan, one path per leg: each ride in its line's colour over a
       * casing that lifts it off the basemap, walks as dots. A response
       * without per-leg geometry draws the whole route in the accent. */
      const drawable = stops.length ? legs.filter((leg) => (leg.geometry?.length ?? 0) > 1) : [];
      const recommendedPoints = routeGeometry.length > 1 ? routeGeometry : points;
      // One entry per leg, so a ride's casing draws in step with the ride.
      const routePaths: import("leaflet").Polyline[][] = [];
      if (drawable.length) {
        for (const leg of drawable) {
          const walk = ["WALK", "BICYCLE", "SCOOTER"].includes(leg.mode.toUpperCase());
          if (walk) {
            routePaths.push([
              L.polyline(latLngs(leg.geometry ?? []), {
                className: "route-walk",
                weight: 4,
                dashArray: "0.5 8",
                lineCap: "round",
                interactive: false,
              }).addTo(layer),
            ]);
            continue;
          }
          const casing = L.polyline(latLngs(leg.geometry ?? []), {
            className: "route-casing",
            weight: 10,
            lineCap: "round",
            lineJoin: "round",
            interactive: false,
          }).addTo(layer);
          const color = lineColor(leg.route_short_name, leg.route_long_name);
          routePaths.push([
            casing,
            L.polyline(latLngs(leg.geometry ?? []), {
              className: color ? "route-ride" : "route-ride route-bus",
              color: color ?? undefined,
              weight: 6,
              lineCap: "round",
              lineJoin: "round",
              interactive: false,
            }).addTo(layer),
          ]);
        }
      } else if (recommendedPoints.length > 1 && stops.length) {
        routePaths.push([
          L.polyline(latLngs(recommendedPoints), {
            className: "route-casing",
            weight: 10,
            interactive: false,
          }).addTo(layer),
          L.polyline(latLngs(recommendedPoints), {
            className: "route-ride route-bus",
            weight: 6,
            interactive: false,
          }).addTo(layer),
        ]);
      }
      /* The route draws itself once, leg by leg, in travel order - the eye
       * follows the journey instead of being handed a finished line. */
      if (!reduceMotion) {
        routePaths.forEach((paths, index) => {
          for (const path of paths) {
            const element = path.getElement() as SVGPathElement | undefined;
            if (!element) continue;
            element.style.setProperty("--draw-delay", `${index * 140}ms`);
            if (element.classList.contains("route-walk")) {
              element.classList.add("route-fade");
              continue;
            }
            element.setAttribute("pathLength", "1");
            element.classList.add("route-draw");
          }
        });
      }

      /* Markers used to be already in place the instant a result arrived,
       * which is a good part of what "lifeless" was describing. They settle in
       * now, staggered in creation order so a plan lands as a sequence rather
       * than a flash. Capped, because a dozen compared places should not take
       * a second and a half to finish arriving. */
      let landOrder = 0;
      const marker = (coordinate: Coordinate, kind: string, label: string, glyph: string) =>
        L.marker([coordinate.latitude, coordinate.longitude], {
          icon: L.divIcon({
            className: `along-marker ${kind}`,
            html: `<span style="--land-delay:${Math.min(landOrder++ * 32, 360)}ms">${glyph}</span>`,
            iconSize: [30, 30],
            iconAnchor: [15, 15],
          }),
        })
          .bindTooltip(label, { direction: "top", offset: [0, -12] })
          .addTo(layer);
      allMarkersRef.current = [];

      if (preview) {
        // The example on the empty map: its two ends and the trip between,
        // drawn faintly enough that it reads as a suggestion.
        L.polyline(latLngs([preview.origin.coordinate, preview.destination.coordinate]), {
          className: "route-preview",
          weight: 3,
          dashArray: "2 9",
          lineCap: "round",
          interactive: false,
        }).addTo(layer);
        allMarkersRef.current.push(
          marker(preview.origin.coordinate, "origin preview", preview.origin.label, "A"),
          marker(
            preview.destination.coordinate,
            "destination preview",
            preview.destination.label,
            "B",
          ),
        );
      }

      // Drawn before the plan's own markers so a compared place can never
      // cover the stop that won. Each carries its extra travel, so the map
      // states the comparison rather than scattering anonymous dots.
      consideredRef.current = considered.map((option) => {
        const minutes = Math.round(option.extra_transport_minutes);
        const label = option.secondary
          ? option.display_name
          : `${option.display_name} · +${minutes} min travel · tap to pick`;
        const item = marker(
          option.coordinate,
          option.secondary ? "considered secondary" : "considered",
          label,
          option.secondary ? "" : `+${minutes}`,
        );
        const element = item.getElement();
        if (element) {
          element.dataset.comparedKey = option.key;
          element.classList.toggle("highlighted", option.key === activeConsidered);
          // Announced, but not focusable: the comparison in the panel is the
          // keyboard path to the same action, and a dozen tab stops scattered
          // over a map is not one.
          element.setAttribute("aria-label", `Pick ${option.display_name}`);
        }
        item.on("click", () => onConsideredSelect?.(option.key));
        return item;
      });
      if (origin)
        allMarkersRef.current.push(marker(origin.coordinate, "origin", origin.label, "A"));
      markersRef.current = stops.map((stop, index) => {
        const item = marker(stop.coordinate, "stop", stop.display_name, `${index + 1}`);
        item
          .getElement()
          ?.setAttribute("aria-label", `Show stop ${index + 1}: ${stop.display_name}`);
        item.getElement()?.classList.toggle("selected-stop", index === selectionRef.current);
        item.on("click", () => onStopSelect?.(index));
        return item;
      });

      if (destination)
        allMarkersRef.current.push(
          marker(destination.coordinate, "destination", destination.label, "B"),
        );
      allMarkersRef.current.push(...markersRef.current, ...consideredRef.current);
      spreadColliding(mapRef.current, allMarkersRef.current);
      // Compared places frame too, or the evidence sits outside the viewport
      // and the map is back to showing one line.
      const framingPoints = [
        ...points,
        ...baselinePoints,
        ...recommendedPoints,
        ...considered.map((option) => option.coordinate),
        ...(preview ? [preview.origin.coordinate, preview.destination.coordinate] : []),
      ];

      framingRef.current = (animate: boolean) => {
        const map = mapRef.current;
        if (!map) return;
        const compact = window.innerWidth <= COMPACT_MAX_WIDTH;
        const motion = animate && !reduceMotion;
        if (origin && !destination && !stops.length) {
          if (motion)
            map.flyTo([origin.coordinate.latitude, origin.coordinate.longitude], 14, {
              duration: 0.65,
            });
          else map.setView([origin.coordinate.latitude, origin.coordinate.longitude], 14);
          return;
        }
        if (framingPoints.length < 2) return;
        const bounds = L.latLngBounds(
          framingPoints.map((point) => [point.latitude, point.longitude]),
        );
        /* The sheet's real height, not a guess at it: the old fixed 390px
         * left the destination under a sheet that is 55% of a phone. The
         * desktop panel is measured the same way, for its width. */
        const planner = document.getElementById("planner");
        const sheet = planner?.getBoundingClientRect();
        const options = {
          paddingTopLeft: compact
            ? L.point(36, 142)
            : L.point((sheet ? sheet.right : 424) + 40, 92),
          paddingBottomRight: compact
            ? L.point(36, (sheet ? window.innerHeight - sheet.top : 390) + 28)
            : L.point(72, 84),
          maxZoom: 15,
          animate: motion,
          duration: 0.75,
        };
        if (motion) map.flyToBounds(bounds, options);
        else map.fitBounds(bounds, options);
      };
      framingRef.current(true);
      window.setTimeout(() => {
        mapRef.current?.invalidateSize();
        spreadColliding(mapRef.current, allMarkersRef.current);
      }, 50);
    });
    return () => {
      cancelled = true;
    };
    // `activeConsidered` is deliberately absent: highlighting is handled by the
    // effect above, and rebuilding every layer on hover would refit the map.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    origin,
    destination,
    stops,
    considered,
    baselineGeometry,
    routeGeometry,
    legs,
    preview,
    onStopSelect,
    onConsideredSelect,
  ]);

  useEffect(
    () => () => {
      mapRef.current?.remove();
      mapRef.current = null;
    },
    [],
  );
  return <div className="map" ref={elementRef} role="region" aria-label="Journey map" />;
}

/* Singapore builds malls on top of stations, so the recommended stop is
 * routinely within ~50 m of the origin or destination and its marker hides the
 * other completely - the "A" pin simply vanished behind stop "1". Fan any
 * overlapping cluster out around its centre.
 *
 * The offset goes on the inner span, because Leaflet owns the outer element's
 * transform for positioning, and it is recomputed on zoom since overlap is a
 * pixel question rather than a distance one. */
function spreadColliding(map: import("leaflet").Map | null, markers: import("leaflet").Marker[]) {
  if (!map || markers.length < 2) return;
  const glyph = (marker: import("leaflet").Marker) =>
    marker.getElement()?.firstElementChild as HTMLElement | null | undefined;
  markers.forEach((marker) => {
    const el = glyph(marker);
    if (el) {
      el.style.removeProperty("--fan-x");
      el.style.removeProperty("--fan-y");
    }
  });

  const points = markers.map((marker) => map.latLngToLayerPoint(marker.getLatLng()));
  const claimed = new Set<number>();
  for (let index = 0; index < markers.length; index += 1) {
    if (claimed.has(index)) continue;
    const cluster = [index];
    claimed.add(index);
    for (let other = index + 1; other < markers.length; other += 1) {
      // 30px icons: any closer and one sits on top of another.
      if (!claimed.has(other) && points[index].distanceTo(points[other]) < 34) {
        cluster.push(other);
        claimed.add(other);
      }
    }
    if (cluster.length < 2) continue;
    const radius = 18 + (cluster.length - 2) * 5;
    cluster.forEach((member, position) => {
      const angle = (2 * Math.PI * position) / cluster.length - Math.PI / 2;
      const el = glyph(markers[member]);
      if (el) {
        // Custom properties, not `transform`: the stop marker already carries a
        // scale, and an inline transform would silently drop it.
        el.style.setProperty("--fan-x", `${(Math.cos(angle) * radius).toFixed(1)}px`);
        el.style.setProperty("--fan-y", `${(Math.sin(angle) * radius).toFixed(1)}px`);
      }
    });
  }
}
