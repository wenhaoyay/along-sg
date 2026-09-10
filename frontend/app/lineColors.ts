/**
 * Official colours of the Singapore rail network, keyed on the line code the
 * router already returns.
 *
 * The app was drawing every leg in the same grey-green while `route_short_name`
 * came back as "DT" or "NS" on every rail leg, unused. Singapore has a mature,
 * instantly legible colour system for exactly this, and a local reader
 * identifies a purple leg as North East before reading a single word - so this
 * is comprehension first and colour second, which is the only kind of colour
 * decision worth making in an app that makes time claims.
 *
 * Buses are deliberately absent. SBS Transit and SMRT do not colour-code
 * services, so inventing a hue per service number would look like a system
 * while meaning nothing.
 */

export const LINE_COLORS: Record<string, string> = {
  NS: "#d42e12", // North South
  EW: "#009645", // East West
  CG: "#009645", // Changi Airport branch, an East West service
  NE: "#9900aa", // North East
  CC: "#fa9e0d", // Circle
  CE: "#fa9e0d", // Circle extension
  DT: "#005ec4", // Downtown
  TE: "#9d5b25", // Thomson-East Coast
  JR: "#0099aa", // Jurong Region, opening in stages
  CR: "#97c1e7", // Cross Island
  BP: "#748477", // Bukit Panjang LRT
  SW: "#748477", // Sengkang LRT, west loop
  SE: "#748477", // Sengkang LRT, east loop
  STC: "#748477", // Sengkang Town Centre
  PW: "#748477", // Punggol LRT, west loop
  PE: "#748477", // Punggol LRT, east loop
  PTC: "#748477", // Punggol Town Centre
};

/* Matched only when the short code is absent or unrecognised. OneMap returns
 * the long name in upper case ("DOWNTOWN LINE"), and the order here matters:
 * "EAST WEST" has to be tested before "EAST COAST" would match Thomson's. */
const BY_NAME: Array<[string, string]> = [
  ["NORTH SOUTH", LINE_COLORS.NS],
  ["EAST WEST", LINE_COLORS.EW],
  ["NORTH EAST", LINE_COLORS.NE],
  ["CIRCLE", LINE_COLORS.CC],
  ["DOWNTOWN", LINE_COLORS.DT],
  ["THOMSON", LINE_COLORS.TE],
  ["JURONG REGION", LINE_COLORS.JR],
  ["CROSS ISLAND", LINE_COLORS.CR],
  ["LRT", LINE_COLORS.BP],
];

/**
 * The line colour for a rail leg, or null when there is nothing to claim.
 *
 * Null is the ordinary answer for a bus, and for a rail line this table has
 * not heard of. The caller falls back to the app's own accent rather than
 * guessing a colour, because a wrong line colour is worse than no line colour:
 * it is a confident statement about which train you are on.
 */
export function lineColor(shortName?: string | null, longName?: string | null): string | null {
  const code = (shortName ?? "").trim().toUpperCase();
  if (code) {
    if (LINE_COLORS[code]) return LINE_COLORS[code];
    // A service can arrive as "NS1" or "EW24" rather than a bare line code.
    const prefix = code.match(/^([A-Z]{2,3})\d/)?.[1];
    if (prefix && LINE_COLORS[prefix]) return LINE_COLORS[prefix];
  }
  const name = (longName ?? "").trim().toUpperCase();
  if (name) {
    for (const [needle, color] of BY_NAME) {
      if (name.includes(needle)) return color;
    }
  }
  return null;
}
