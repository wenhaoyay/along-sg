"use client";

import { forwardRef } from "react";
import type { CatalogCategory } from "../DiscoveryPalette";
import { intentLabel, type Notice } from "./types";

type Props = {
  notice: Notice | null;
  /** The need text as it is now: a partial-match notice belongs to the text
   *  it was about, and disappears once that text is edited. */
  need: string;
  browsing: boolean;
  categories: CatalogCategory[];
  onKeep: () => void;
  onUseMentioned: () => void;
  onEditEndpoint: () => void;
  onContinuePartial: () => void;
  onEditRequest: () => void;
};

/** The one message the planner has before it can show a plan. */
export const NoticeLane = forwardRef<HTMLDivElement, Props>(function NoticeLane(
  {
    notice,
    need,
    browsing,
    categories,
    onKeep,
    onUseMentioned,
    onEditEndpoint,
    onContinuePartial,
    onEditRequest,
  },
  ref,
) {
  return (
    <div ref={ref} className="notice-lane">
      {notice?.kind === "clarify" && (
        <div className="notice" role="alert">
          <strong>A quick check</strong>
          <p>{notice.text}</p>
        </div>
      )}
      {notice?.kind === "conflict" && (
        <div className="notice conflict" role="alert">
          <strong>Your journey changed</strong>
          <p>{notice.text}</p>
          <div className="conflict-actions">
            <button type="button" onClick={onKeep}>
              Keep {notice.conflict.current_label}
            </button>
            {notice.conflict.mentioned_label && (
              <button type="button" onClick={onUseMentioned}>
                Use {notice.conflict.mentioned_label}
              </button>
            )}
            <button type="button" onClick={onEditEndpoint}>
              Edit {notice.conflict.endpoint === "origin" ? "From" : "To"}
            </button>
          </div>
        </div>
      )}
      {notice?.kind === "error" && (
        <div className="notice error" role="alert">
          <strong>That didn’t work</strong>
          <p>{notice.text}</p>
        </div>
      )}
      {notice?.kind === "partial" && notice.text === need && !browsing && (
        <div className="notice" role="alert">
          <strong>We found part of your request</strong>
          <p>
            Not resolved: {notice.missing.join(", ")}. Continue with{" "}
            {[...notice.intent.required_errands, ...notice.intent.optional_errands]
              .map((item) => intentLabel(categories, item))
              .join(" and ")}{" "}
            only?
          </p>
          <div className="conflict-actions">
            <button type="button" onClick={onContinuePartial}>
              Continue with matched errands
            </button>
            <button type="button" onClick={onEditRequest}>
              Edit request
            </button>
          </div>
        </div>
      )}
    </div>
  );
});
