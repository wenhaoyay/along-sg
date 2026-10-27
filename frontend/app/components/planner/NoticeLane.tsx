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

/** The one message the planner has before it can show a plan. Each is its
 *  sentence and its actions; the titles over them ("A quick check", "That
 *  didn't work") said nothing the sentence did not. */
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
          <p>{notice.text}</p>
        </div>
      )}
      {notice?.kind === "conflict" && (
        <div className="notice conflict" role="alert">
          <p>{notice.text || notice.conflict.reason}</p>
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
          <p>{notice.text}</p>
        </div>
      )}
      {notice?.kind === "partial" && notice.text === need && !browsing && (
        <div className="notice" role="alert">
          <p>No match for {notice.missing.map((term) => `“${term}”`).join(" or ")}.</p>
          <div className="conflict-actions">
            <button type="button" onClick={onContinuePartial}>
              Continue with{" "}
              {[...notice.intent.required_errands, ...notice.intent.optional_errands]
                .map((item) => intentLabel(categories, item))
                .join(" and ")}
            </button>
            <button type="button" onClick={onEditRequest}>
              Edit
            </button>
          </div>
        </div>
      )}
    </div>
  );
});
