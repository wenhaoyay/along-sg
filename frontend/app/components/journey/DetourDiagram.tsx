"use client";

import { useState } from "react";
import { ShoppingBag } from "lucide-react";
import { inkOn } from "../../lineColors";
import { clockTime } from "./format";
import { RANK_LABELS, type RankKey, tradeoffCopy } from "./ranking";
import { directStrip, recommendationStrip, type Strip } from "./strips";
import { laterMinutes, optionTag, signed, travelMinutes } from "./figures";
import { type Recommendation, type Result } from "./types";

const VISIBLE_ROWS = 4;

type Props = {
  result: Result;
  /** Every routed option, already in the order the sort control asks for. */
  rows: Array<[string, Recommendation]>;
  selectedKey: string;
  selected: Recommendation;
  onSelect: (key: string) => void;
  onHover?: (key: string | null) => void;
  rankBy: RankKey;
  onRankChange: (rank: RankKey) => void;
};

/** The options as journeys on one time axis, with the direct trip as the
 *  yardstick. Picking a row makes it the plan.
 *
 *  The bars name themselves - a ride carries its line's code, a stop a bag -
 *  so there is no key, and no axis: the figure beside each row is the time,
 *  and the dashed line is where the direct trip arrives. */
export function DetourDiagram({
  result,
  rows,
  selectedKey,
  selected,
  onSelect,
  onHover,
  rankBy,
  onRankChange,
}: Props) {
  const [expanded, setExpanded] = useState(false);
  const direct = directStrip(result);
  const strips = rows.map(([key, item]) => [key, item, recommendationStrip(item)] as const);
  const visible = expanded ? strips : strips.slice(0, VISIBLE_ROWS);
  // The selected option stays on screen even when the sort pushes it down.
  if (!expanded && !visible.some(([key]) => key === selectedKey)) {
    const chosen = strips.find(([key]) => key === selectedKey);
    if (chosen) visible.push(chosen);
  }
  // One scale for every row, shown or not, so "Show all" never changes the
  // length of a bar you were already reading.
  const scale = Math.max(direct.total, ...strips.map(([, , strip]) => strip.total)) * 1.02;
  const directAt = (direct.total / scale) * 100;

  return (
    <section className="detour" aria-labelledby="detour-title">
      <div className="detour-head">
        <h2 id="detour-title" className="sr-only">
          Compared with going direct
        </h2>
        {rows.length > 1 && (
          <div className="detour-sort" role="group" aria-label="Sort options by">
            {(Object.keys(RANK_LABELS) as RankKey[]).map((key) => (
              <button
                type="button"
                key={key}
                aria-pressed={rankBy === key}
                onClick={() => onRankChange(key)}
              >
                {RANK_LABELS[key]}
              </button>
            ))}
          </div>
        )}
      </div>

      <div
        className="detour-rows"
        style={{ "--direct-at": `${directAt}%` } as React.CSSProperties}
        onMouseLeave={() => onHover?.(null)}
      >
        <div className="detour-row direct">
          <span className="detour-name">Direct</span>
          <span className="detour-figure">
            {Math.round(direct.total)} min
            {result.baseline.arrival_time ? ` · ${clockTime(result.baseline.arrival_time)}` : ""}
          </span>
          <Track strip={direct} scale={scale} />
        </div>
        {visible.map(([key, item, strip]) => {
          const travel = signed(travelMinutes(item));
          const later = Math.round(laterMinutes(item));
          const name = item.stops.map((stop) => stop.display_name).join(" then ");
          const trade = key === selectedKey ? null : tradeoffCopy(item, selected);
          const tag = optionTag(item);
          return (
            <button
              type="button"
              key={key}
              className={`detour-row option${key === selectedKey ? " selected" : ""}`}
              aria-pressed={key === selectedKey}
              onClick={() => onSelect(key)}
              onMouseEnter={() => onHover?.(key)}
              onFocus={() => onHover?.(key)}
              onBlur={() => onHover?.(null)}
            >
              <span className="detour-name">{name}</span>
              {/* The row's name is its own visible text plus what the bar
                  shows, said in words - an aria-label that rephrased the
                  figures did not contain what a voice user sees. */}
              <span className="detour-figure">
                {travel} min
                <span className="sr-only">{` extra travel, ${later} min later than going direct`}</span>
                {item.arrival_time ? (
                  <>
                    <span className="sr-only">, arrive</span>
                    {` · ${clockTime(item.arrival_time)}`}
                  </>
                ) : null}
              </span>
              <Track strip={strip} scale={scale} />
              {(tag || trade) && (
                <small className="detour-trade">
                  {tag && <em>{tag}</em>}
                  {trade}
                </small>
              )}
            </button>
          );
        })}
      </div>
      {strips.length > VISIBLE_ROWS && (
        <button type="button" className="detour-more" onClick={() => setExpanded(!expanded)}>
          {expanded ? "Show fewer" : `Show all ${strips.length}`}
        </button>
      )}
    </section>
  );
}

function Track({ strip, scale }: { strip: Strip; scale: number }) {
  return (
    <span className="detour-track" aria-hidden="true">
      {strip.pieces.map((piece, index) => {
        const width = ((piece.end - piece.start) / scale) * 100;
        return (
          <i
            key={index}
            className={`piece ${piece.kind}`}
            title={piece.title}
            style={
              {
                left: `${(piece.start / scale) * 100}%`,
                width: `${width}%`,
                "--piece-color": piece.color ?? undefined,
                "--piece-ink": piece.color ? inkOn(piece.color) : undefined,
              } as React.CSSProperties
            }
          >
            {piece.kind === "ride" && piece.code && width > 7 ? piece.code : null}
            {piece.kind === "stop" && width > 5 ? <ShoppingBag size={11} /> : null}
          </i>
        );
      })}
    </span>
  );
}
