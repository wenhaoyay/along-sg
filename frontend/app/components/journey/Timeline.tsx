"use client";

import { Bus, Footprints, ShoppingBag, TrainFront } from "lucide-react";
import { lineColor } from "../../lineColors";
import PlaceMark from "../PlaceMark";
import type { StopArrivals } from "../../useBusArrivals";
import { errandLines, hoursSummary, STATUS_WORD } from "./errands";
import { clockTime, dayIfNotToday, metres } from "./format";
import { NextBuses, isRail, rideDetail, serviceName } from "./RideLegs";
import { buildTimeline, shortStation, type TimelineItem, type TimelinePlace } from "./steps";
import { type Recommendation } from "./types";

type Props = {
  recommendation: Recommendation;
  originName: string;
  destinationName: string;
  arrivals: Record<string, StopArrivals>;
  activeStop?: number | null;
  onStopSelect?: (index: number) => void;
};

/** The plan, one step per row, with the clock down the left. */
export function Timeline({
  recommendation,
  originName,
  destinationName,
  arrivals,
  activeStop,
  onStopSelect,
}: Props) {
  const items = buildTimeline(recommendation, originName, destinationName);
  const numbered = recommendation.stops.length > 1;
  return (
    <ol className="timeline" aria-label="Your journey, step by step">
      {items.map((item, index) => (
        <Row
          key={index}
          item={item}
          numbered={numbered}
          arrivals={arrivals}
          active={item.kind === "place" && item.stopIndex === activeStop}
          onStopSelect={onStopSelect}
        />
      ))}
    </ol>
  );
}

function Clock({ time }: { time: string | null }) {
  return <time className="timeline-clock">{time ? clockTime(time) : ""}</time>;
}

function Row({
  item,
  numbered,
  arrivals,
  active,
  onStopSelect,
}: {
  item: TimelineItem;
  numbered: boolean;
  arrivals: Record<string, StopArrivals>;
  active: boolean;
  onStopSelect?: (index: number) => void;
}) {
  if (item.kind === "walk") {
    return (
      <li className="timeline-row walk">
        <Clock time={null} />
        <span className="timeline-rail" aria-hidden="true" />
        <p>
          <Footprints size={14} aria-hidden="true" />
          Walk {Math.max(1, Math.round(item.minutes))} min
          {item.metres >= 20 && <span className="timeline-meta"> · {metres(item.metres)}</span>}
        </p>
      </li>
    );
  }

  if (item.kind === "ride") {
    const { leg } = item;
    const from = shortStation(leg.from_name);
    const to = shortStation(leg.to_name);
    return (
      <li
        className="timeline-row ride ride-leg"
        style={
          {
            "--service-color":
              lineColor(leg.route_short_name, leg.route_long_name) ?? "var(--green)",
          } as React.CSSProperties
        }
      >
        <Clock time={item.time} />
        <span className="timeline-rail" aria-hidden="true" />
        <div>
          {item.changeAt && <p className="timeline-change">Change at {item.changeAt}</p>}
          <p>
            {isRail(leg) ? (
              <TrainFront size={13} aria-hidden="true" />
            ) : (
              <Bus size={13} aria-hidden="true" />
            )}
            <span className="service">{serviceName(leg)}</span>
            {from && to && (
              <span className="timeline-route">
                {from} → {to}
              </span>
            )}
          </p>
          <p className="timeline-meta">
            <span className="ride-detail">{rideDetail(leg)}</span>
            <NextBuses leg={leg} arrivals={arrivals} />
          </p>
        </div>
      </li>
    );
  }

  if (item.role !== "stop" || !item.stop) {
    return (
      <li className={`timeline-row endpoint ${item.role}`}>
        <Clock time={item.time} />
        <span className="timeline-rail" aria-hidden="true">
          <b>{item.role === "origin" ? "A" : "B"}</b>
        </span>
        <p className="timeline-endpoint">
          <strong>{item.name}</strong>
          <span className="timeline-meta">
            {item.role === "origin" ? "Leave" : "Arrive"}
            {item.time && dayIfNotToday(item.time) ? ` ${dayIfNotToday(item.time)}` : ""}
          </span>
        </p>
      </li>
    );
  }

  const stop = item.stop;
  const lines = errandLines(stop);
  const hours = hoursSummary(lines);
  const stopIndex = item.stopIndex ?? 0;
  return (
    <li className={`timeline-row stop ${active ? "selected-stop-card" : ""}`}>
      <Clock time={item.time} />
      <span className="timeline-rail" aria-hidden="true" />
      <div>
        <button
          type="button"
          className="stop-number"
          aria-label={`Highlight stop ${stopIndex + 1}: ${item.name}`}
          aria-pressed={active}
          onClick={() => onStopSelect?.(stopIndex)}
        >
          {numbered ? stopIndex + 1 : <ShoppingBag size={14} aria-hidden="true" />}
        </button>
        <p className="timeline-stop-name">
          <strong>{item.name}</strong>
          {item.dwellMinutes ? (
            <span className="timeline-meta">
              ~{Math.round(item.dwellMinutes)} min here
              {item.leaveTime ? ` · leave ${clockTime(item.leaveTime)}` : ""}
            </span>
          ) : null}
        </p>
        <ul className="errand-lines" aria-label="Your errands here">
          {lines.map((line) => (
            <li key={`${line.errand}-${line.shop}`}>
              <span className="errand-name">{line.errand}</span>
              <span className="errand-shop">
                <ShopMark stop={stop} name={line.shop} />
                {line.shop}
                <i className={`status-dot ${line.status}`} title={STATUS_WORD[line.status]} />
                <span className="sr-only">
                  , {STATUS_WORD[line.status] ?? "hours not confirmed"}
                </span>
              </span>
              {line.others > 0 && <span className="timeline-meta">+{line.others} more here</span>}
            </li>
          ))}
        </ul>
        {hours && <small className={`hours-status hours-${hoursClass(lines)}`}>{hours}</small>}
      </div>
    </li>
  );
}

function hoursClass(lines: Array<{ status: string }>) {
  const statuses = new Set(lines.map((line) => line.status));
  return statuses.size === 1 ? [...statuses][0] : "mixed";
}

/* The brand's own mark where the catalog has one, a glyph for what the place
 * sells where it does not - the same box either way. */
function ShopMark({ stop, name }: { stop: NonNullable<TimelinePlace["stop"]>; name: string }) {
  const business = stop.businesses.find((item) => item.display_name === name);
  return (
    <PlaceMark
      logoUrl={business?.logo_url}
      categoryLabels={business?.category_labels ?? []}
      name={name}
      size={16}
    />
  );
}
