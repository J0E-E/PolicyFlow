// Unit tests for the lead-detail presentation helpers (P1.9 Epic 1 adds the two
// event-timeline timestamp helpers). These are pure and JSX-free, so they test on
// their own — no DOM, no mocks. The relative-time helper takes an injected `now` so
// the buckets are deterministic regardless of wall-clock.

import { describe, expect, it } from "vitest";

import {
  leadEventAbsoluteUtc,
  leadEventRelativeTime,
  leadPreferredContactLabel,
  reactionStatusStamp,
} from "./leadDetailPresentation.ts";

describe("leadPreferredContactLabel", () => {
  it("maps known methods to human labels and passes unknown values through", () => {
    expect(leadPreferredContactLabel("email")).toBe("Email");
    expect(leadPreferredContactLabel("phone")).toBe("Phone call");
    expect(leadPreferredContactLabel("text")).toBe("Text message");
    expect(leadPreferredContactLabel("carrier_pigeon")).toBe("carrier_pigeon");
    expect(leadPreferredContactLabel(null)).toBeNull();
  });
});

describe("leadEventRelativeTime", () => {
  const now = new Date("2026-06-24T12:00:00Z");

  it("reads 'just now' under a minute", () => {
    expect(leadEventRelativeTime("2026-06-24T11:59:30Z", now)).toBe("just now");
  });

  it("reads minutes, singular and plural", () => {
    expect(leadEventRelativeTime("2026-06-24T11:59:00Z", now)).toBe("1 minute ago");
    expect(leadEventRelativeTime("2026-06-24T11:45:00Z", now)).toBe("15 minutes ago");
  });

  it("reads hours, singular and plural", () => {
    expect(leadEventRelativeTime("2026-06-24T11:00:00Z", now)).toBe("1 hour ago");
    expect(leadEventRelativeTime("2026-06-24T10:00:00Z", now)).toBe("2 hours ago");
  });

  it("reads days, singular and plural", () => {
    expect(leadEventRelativeTime("2026-06-23T12:00:00Z", now)).toBe("1 day ago");
    expect(leadEventRelativeTime("2026-06-21T12:00:00Z", now)).toBe("3 days ago");
  });

  it("falls back to 'just now' for a future or unparseable timestamp", () => {
    expect(leadEventRelativeTime("2026-06-24T12:05:00Z", now)).toBe("just now");
    expect(leadEventRelativeTime("not-a-date", now)).toBe("just now");
  });
});

describe("reactionStatusStamp", () => {
  it("maps each derived status onto its frozen hue, label, and spinner flag", () => {
    // pending → calm neutral grey, no spinner (information is not a signal, Guide §2.2).
    expect(reactionStatusStamp("pending")).toEqual({
      status: "neutral",
      label: "Pending",
      isProcessing: false,
    });
    // processing → the blue `pending` hue + the inline spinner (the active affordance).
    expect(reactionStatusStamp("processing")).toEqual({
      status: "pending",
      label: "Processing",
      isProcessing: true,
    });
    // done → green success, no spinner.
    expect(reactionStatusStamp("done")).toEqual({
      status: "success",
      label: "Done",
      isProcessing: false,
    });
    // failed → red error, dormant this epic but present in the mapping.
    expect(reactionStatusStamp("failed")).toEqual({
      status: "error",
      label: "Failed",
      isProcessing: false,
    });
  });
});

describe("leadEventAbsoluteUtc", () => {
  it("formats a fixed-width UTC stamp, zero-padded", () => {
    expect(leadEventAbsoluteUtc("2026-06-24T09:05:03Z")).toBe(
      "2026-06-24 09:05:03 UTC",
    );
  });

  it("normalizes an offset timestamp to UTC", () => {
    // 14:30 at +02:00 is 12:30 UTC.
    expect(leadEventAbsoluteUtc("2026-06-24T14:30:00+02:00")).toBe(
      "2026-06-24 12:30:00 UTC",
    );
  });

  it("returns the input unchanged when it cannot be parsed", () => {
    expect(leadEventAbsoluteUtc("not-a-date")).toBe("not-a-date");
  });
});
