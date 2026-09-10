"use client";

import { createElement, useState } from "react";
import {
  Banknote,
  Cake,
  Coffee,
  CupSoda,
  Croissant,
  Flower2,
  Glasses,
  Hammer,
  Laptop,
  Package,
  PencilRuler,
  Pill,
  Printer,
  Scissors,
  Shirt,
  ShoppingBasket,
  ShoppingCart,
  Sofa,
  Store,
  Utensils,
  Wrench,
} from "lucide-react";

/**
 * The visual identity of one place: its brand mark where there is one, and a
 * glyph for what it sells where there is not.
 *
 * Idea 3 asked for pictures. OpenStreetMap has 20 of them across 21,280
 * elements, so this is what the free data actually supports - 16.4% of outlets
 * carry a brand logo through Wikidata, and the rest are hawker stalls and
 * single shops that will never have one.
 *
 * The glyph is therefore the design, not the failure case. Both branches
 * occupy the same box at the same size so a list of places does not jitter
 * between those that have a logo and those that do not, and neither branch
 * gets a border or a label that would read as "missing".
 */

type Props = {
  logoUrl?: string | null;
  categoryLabels: string[];
  name: string;
  size?: number;
};

// Matched on the human label the API already sends, longest key first so
// "bubble tea" is not swallowed by "tea" and "fast food" beats "food".
const GLYPHS: Array<[string, typeof Store]> = [
  ["bubble tea", CupSoda],
  ["convenience store", ShoppingBasket],
  ["household goods", Sofa],
  ["atm and banking", Banknote],
  ["parcel collection", Package],
  ["optical shops", Glasses],
  ["pet supplies", ShoppingBasket],
  ["fried chicken", Utensils],
  ["supermarket", ShoppingCart],
  ["electronics", Laptop],
  ["stationery", PencilRuler],
  ["restaurants", Utensils],
  ["fast food", Utensils],
  ["pharmacy", Pill],
  ["bakeries", Croissant],
  ["haircuts", Scissors],
  ["clothing", Shirt],
  ["florists", Flower2],
  ["printing", Printer],
  ["hardware", Hammer],
  ["dessert", Cake],
  ["repairs", Wrench],
  ["burgers", Utensils],
  ["coffee", Coffee],
];

function glyphFor(categoryLabels: string[]) {
  const haystack = categoryLabels.join(" ").toLowerCase();
  for (const [needle, Icon] of GLYPHS) {
    if (haystack.includes(needle)) return Icon;
  }
  return Store;
}

/* createElement rather than <Glyph />: a capitalised variable in JSX reads to
   React as a component defined during render, which would reset its state on
   every pass. These are static imports being selected between, not built. */
function renderGlyph(categoryLabels: string[], size: number) {
  return createElement(glyphFor(categoryLabels), {
    size: Math.round(size * 0.72),
    strokeWidth: 1.75,
  });
}

export default function PlaceMark({ logoUrl, categoryLabels, name, size = 22 }: Props) {
  // The URL that failed, rather than a boolean. A Commons file can be renamed
  // or deleted between one ingestion and the next, so a new URL has to be
  // retried - and deriving that from the value avoids resetting state in an
  // effect, which cascades a second render on every logo.
  const [brokenUrl, setBrokenUrl] = useState<string | null>(null);
  const usable = logoUrl && brokenUrl !== logoUrl;

  return (
    <span
      className="place-mark"
      style={{ width: size, height: size }}
      aria-hidden="true"
      data-testid="place-mark"
      data-kind={usable ? "logo" : "glyph"}
    >
      {usable ? (
        // A static export with no image optimiser, and next/image would need a
        // configured remote loader to reach Wikimedia at all.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={logoUrl}
          alt=""
          loading="lazy"
          decoding="async"
          onError={() => setBrokenUrl(logoUrl)}
          title={name}
        />
      ) : (
        renderGlyph(categoryLabels, size)
      )}
    </span>
  );
}
