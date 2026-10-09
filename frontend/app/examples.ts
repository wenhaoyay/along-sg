import type { ResolvedLocation } from "./components/LocationField";

/* One click to a real plan.
 *
 * A reviewer who does not know Singapore had nothing to type: "Punggol" is
 * not a word you guess. Each example is a request the deterministic parser
 * resolves and the offline catalog answers well, with endpoints exactly as the
 * geocoder returns them, so choosing one is the same as typing it. */

export type Example = {
  id: string;
  origin: ResolvedLocation;
  destination: ResolvedLocation;
  need: string;
};

const station = (
  label: string,
  latitude: number,
  longitude: number,
  subtitle: string,
): ResolvedLocation => ({
  label,
  coordinate: { latitude, longitude },
  entity_type: "mrt_station",
  confirmed: true,
  confidence: "exact",
  subtitle,
});

export const EXAMPLES: Example[] = [
  {
    id: "punggol-orchard",
    origin: station(
      "Punggol MRT",
      1.4057779,
      103.9028951,
      "NE17 / PTC · North East Line · Punggol LRT",
    ),
    destination: station(
      "Orchard MRT Station",
      1.3042331,
      103.8316034,
      "NS22 / TE14 · North-South Line · Thomson-East Coast Line",
    ),
    need: "panadol and some groceries, prefer FairPrice",
  },
  {
    id: "jurong-raffles",
    origin: station(
      "Jurong East MRT Station",
      1.3337388,
      103.7420635,
      "EW24 / NS1 · East-West Line · North-South Line",
    ),
    destination: station(
      "Raffles Place MRT Station",
      1.2851641,
      103.8517645,
      "EW14 / NS26 · East-West Line · North-South Line",
    ),
    need: "KFC and bubble tea",
  },
  {
    id: "tampines-harbourfront",
    origin: station(
      "Tampines MRT Station",
      1.3541999,
      103.9441273,
      "DT32 / EW2 · Downtown Line · East-West Line",
    ),
    destination: station(
      "Harbourfront MRT Station",
      1.2656479,
      103.8218885,
      "CC29 / NE1 · Circle Line · North East Line",
    ),
    need: "coffee and a birthday cake",
  },
];

/** "Punggol MRT" → "Punggol", for the example cards. */
export function placeName(location: ResolvedLocation) {
  return location.label.replace(/\s+MRT(\s+Station)?$/i, "");
}
