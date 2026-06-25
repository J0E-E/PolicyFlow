// Unit tests for the pure lead-status → Stamp map (Epic 20). These pin the four
// status → (hue, label) decisions so a later epic re-wiring a stamp (or adding a
// status) gets a clear regression signal. No rendering — the function is pure.

import { describe, expect, it } from "vitest";

import { leadStatusStamp } from "./leadStatusStamp.ts";
import type { LeadStatus } from "../api";

describe("leadStatusStamp", () => {
  it("maps New to a neutral stamp", () => {
    expect(leadStatusStamp("New")).toEqual({ status: "neutral", label: "New" });
  });

  it("maps Working to a pending stamp", () => {
    expect(leadStatusStamp("Working")).toEqual({
      status: "pending",
      label: "Working",
    });
  });

  it("maps Qualified to a success stamp", () => {
    expect(leadStatusStamp("Qualified")).toEqual({
      status: "success",
      label: "Qualified",
    });
  });

  it("maps Rejected to an error stamp", () => {
    expect(leadStatusStamp("Rejected")).toEqual({
      status: "error",
      label: "Rejected",
    });
  });

  it("maps Converted to a success stamp", () => {
    expect(leadStatusStamp("Converted")).toEqual({
      status: "success",
      label: "Converted",
    });
  });

  it("is total over every LeadStatus (no status returns undefined)", () => {
    const everyStatus: LeadStatus[] = [
      "New",
      "Working",
      "Qualified",
      "Rejected",
      "Converted",
    ];
    for (const status of everyStatus) {
      expect(leadStatusStamp(status)).toBeDefined();
    }
  });
});
