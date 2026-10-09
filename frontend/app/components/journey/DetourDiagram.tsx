"use client";

import { useState } from "react";
import { clockTime } from "./format";
import { RANK_LABELS, type RankKey, tradeoffCopy } from "./ranking";
import { directStrip, recommendationStrip, type Strip } from "./strips";
import { type Recommendation, type Result } from "./types";

const VISIBLE_ROWS = 4;

/* What makes an option a different kind of answer, said on its row. Without
 * it a +22 beside a +32 looked strictly better, when it was a 7-Eleven
 * standing in for the supermarket you asked for. */
const OPTION_TAG: Record<string, string> = {
  partial_option: "one errand only",
  easier_alternative: "easier alternative",
};

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
  note: string;
};

/** The options as journeys on one time axis, with the direct trip as the
 *  yardstick. Picking a row makes it the plan. */
export function DetourDiagram({
  result,
  rows,
  selectedKey,
  selected,
  onSelect,
  onHover,
  rankBy,
  onRankChange,
  note,
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
  const scale = Math.max(direct.total, ...visible.map(([, , strip]) => strip.total)) * 1.02;
  const directAt = (direct.total / scale) * 100;

  return (
    <section className="detour" aria-labelledby="detour-title">
      <div className="detour-head">
        <h2 id="detour-title">Compared with going direct</h2>
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
          const added = Math.round(item.incremental_detour_minutes);
          const name = item.stops.map((stop) => stop.display_name).join(" then ");
          const trade = key === selectedKey ? null : tradeoffCopy(item, selected);
          const tag = OPTION_TAG[item.match_classification];
          return (
            <button
              type="button"
              key={key}
              className={`detour-row option${key === selectedKey ? " selected" : ""}`}
              aria-pressed={key === selectedKey}
              aria-label={`${name}: ${added} min later than going direct${
                item.arrival_time ? `, arrive ${clockTime(item.arrival_time)}` : ""
              }${trade ? `. ${trade}` : ""}`}
              onClick={() => onSelect(key)}
              onMouseEnter={() => onHover?.(key)}
              onFocus={() => onHover?.(key)}
              onBlur={() => onHover?.(null)}
            >
              <span className="detour-name">{name}</span>
              <span className="detour-figure">
                +{added} min
                {item.arrival_time ? ` · ${clockTime(item.arrival_time)}` : ""}
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

      <div className="detour-foot">
        <ul className="detour-legend" aria-label="Diagram key">
          <li>
            <i className="ride" />
            Train or bus
          </li>
          <li>
            <i className="walk" />
            Walk
          </li>
          <li>
            <i className="wait" />
            Wait or change
          </li>
          <li>
            <i className="stop" />
            At your stops
          </li>
          <li>
            <i className="direct" />
            Direct arrives
          </li>
        </ul>
        {strips.length > VISIBLE_ROWS && (
          <button type="button" className="detour-more" onClick={() => setExpanded(!expanded)}>
            {expanded ? "Show fewer" : `Show all ${strips.length} routed options`}
          </button>
        )}
        <p className="precision-note">{note}</p>
      </div>
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
              } as React.CSSProperties
            }
          >
            {piece.kind === "ride" && piece.code && width > 7 ? piece.code : null}
          </i>
        );
      })}
    </span>
  );
}
