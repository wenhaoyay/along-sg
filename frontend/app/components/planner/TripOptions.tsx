"use client";

import { Footprints, SlidersHorizontal, Zap } from "lucide-react";
import type { TripStyle } from "./types";

type Props = {
  style: TripStyle;
  onStyle: (style: TripStyle) => void;
  leaveMode: "now" | "later";
  onLeaveMode: (mode: "now" | "later") => void;
  leaveAt: string;
  onLeaveAt: (value: string) => void;
};

const STYLE_HINTS: Record<TripStyle, string> = {
  balanced: "Weigh extra time, walking and changes, and how sure we are of each place.",
  faster: "Give extra journey time more weight when comparing stops.",
  walking: "Give easier walks more weight when comparing stops.",
};

/** How to weigh the comparison, and when to leave. */
export function TripOptions({ style, onStyle, leaveMode, onLeaveMode, leaveAt, onLeaveAt }: Props) {
  return (
    <>
      <div className="trip-style" role="group" aria-label="Journey preference">
        <button
          type="button"
          aria-pressed={style === "balanced"}
          onClick={() => onStyle("balanced")}
        >
          <SlidersHorizontal size={14} aria-hidden="true" />
          Best overall
        </button>
        <button type="button" aria-pressed={style === "faster"} onClick={() => onStyle("faster")}>
          <Zap size={14} aria-hidden="true" />
          Faster
        </button>
        <button type="button" aria-pressed={style === "walking"} onClick={() => onStyle("walking")}>
          <Footprints size={14} aria-hidden="true" />
          Less walking
        </button>
      </div>
      <p className="preference-hint">{STYLE_HINTS[style]}</p>
      {/* The same segmented control as the preference above it. A native
          select here was smaller, differently styled and the only one on the
          page. */}
      <div className="departure-controls">
        <div className="trip-style departure-mode" role="group" aria-label="Departure">
          {(
            [
              ["now", "Leave now"],
              ["later", "Leave later"],
            ] as const
          ).map(([mode, label]) => (
            <button
              type="button"
              key={mode}
              aria-pressed={leaveMode === mode}
              onClick={() => {
                onLeaveMode(mode);
                /* An empty time field met with the browser's own "Please fill
                 * out this field". Start from a sensible answer. */
                if (mode === "later" && !leaveAt) onLeaveAt(sgLocalInput(30));
              }}
            >
              {label}
            </button>
          ))}
        </div>
        {leaveMode === "later" && (
          <label>
            Singapore time (SGT)
            <input
              aria-label="Departure time in Singapore"
              type="datetime-local"
              value={leaveAt}
              min={sgLocalInput(0)}
              onChange={(event) => onLeaveAt(event.target.value)}
              required
            />
          </label>
        )}
      </div>
    </>
  );
}

/* A datetime-local value ("2026-10-02T14:05") for Singapore time, `ahead`
 * minutes from now and rounded up to five, whatever the device's own zone. */
export function sgLocalInput(ahead: number) {
  const at = new Date(Date.now() + ahead * 60_000);
  at.setUTCMinutes(Math.ceil(at.getUTCMinutes() / 5) * 5, 0, 0);
  const sg = new Date(at.getTime() + 8 * 60 * 60_000);
  return sg.toISOString().slice(0, 16);
}
