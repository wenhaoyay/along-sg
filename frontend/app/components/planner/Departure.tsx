"use client";

import { Clock3 } from "lucide-react";

type Mode = "now" | "later";

/** When to leave, beside the From label: two words, not a row of its own.
 *  The visible "Now" / "Later" are inside each button's name, as voice
 *  control needs. */
export function DepartureToggle({
  mode,
  onMode,
  at,
  onAt,
}: {
  mode: Mode;
  onMode: (mode: Mode) => void;
  at: string;
  onAt: (value: string) => void;
}) {
  return (
    <div className="departure-toggle" role="group" aria-label="Departure">
      <Clock3 size={13} aria-hidden="true" />
      {(["now", "later"] as const).map((value) => (
        <button
          type="button"
          key={value}
          aria-pressed={mode === value}
          aria-label={value === "now" ? "Leave now" : "Leave later"}
          onClick={() => {
            onMode(value);
            /* An empty time field met with the browser's own "Please fill
             * out this field". Start from a sensible answer. */
            if (value === "later" && !at) onAt(sgLocalInput(30));
          }}
        >
          {value === "now" ? "Now" : "Later"}
        </button>
      ))}
    </div>
  );
}

/** The departure time, under the journey once "Later" is chosen. */
export function DepartureTime({ at, onAt }: { at: string; onAt: (value: string) => void }) {
  return (
    <div className="departure-time">
      <input
        aria-label="Departure time in Singapore"
        type="datetime-local"
        value={at}
        min={sgLocalInput(0)}
        onChange={(event) => onAt(event.target.value)}
        required
      />
      <span aria-hidden="true">SGT</span>
    </div>
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
