// Tests for the per-lead EVENT TIMELINE ink console (P1.9 Epic 1, the tracer slice).
// jsdom has no backend, so `../api` is mocked: getLeadTimeline drives the console's
// single fetch on open. Covers: the console always renders (overline present), event
// rows render in the order the read returns (oldest-first), the always-present empty
// state, the error note, and the full-words relative-time label on a row.

import { render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import LeadTimeline from "./LeadTimeline.tsx";
import type { TimelineRow } from "../api";

vi.mock("../api", () => ({
  getLeadTimeline: vi.fn(),
}));

import { getLeadTimeline } from "../api";

const getLeadTimelineMock = vi.mocked(getLeadTimeline);

function makeRow(overrides: Partial<TimelineRow>): TimelineRow {
  return {
    kind: "event",
    status: "occurred",
    event_type: "lead.created",
    occurred_at: "2026-06-24T12:00:00Z",
    event_id: "00000000-0000-0000-0000-000000000001",
    correlation_id: "11111111-1111-1111-1111-111111111111",
    ...overrides,
  };
}

beforeEach(() => {
  getLeadTimelineMock.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("LeadTimeline", () => {
  it("renders the event rows in the order the read returns (oldest-first)", async () => {
    getLeadTimelineMock.mockResolvedValue([
      makeRow({
        event_type: "lead.created",
        event_id: "00000000-0000-0000-0000-00000000000a",
      }),
      makeRow({
        event_type: "lead.qualified",
        event_id: "00000000-0000-0000-0000-00000000000b",
      }),
    ]);

    render(<LeadTimeline id="timeline" leadId="lead-1" />);

    await waitFor(() => {
      expect(document.getElementById("timeline-list")).toBeInTheDocument();
    });

    // The console titled itself with the stamp overline.
    expect(document.getElementById("timeline-overline")).toBeInTheDocument();

    // Both rows render, in the order returned (oldest-first): created then qualified.
    const eventTypeNodes = Array.from(
      document.querySelectorAll(".lead-timeline-event-type"),
    ).map((node) => node.textContent);
    expect(eventTypeNodes).toEqual(["lead.created", "lead.qualified"]);

    // The neutral OCCURRED stamp is present (a fact, not a state signal).
    const firstStamp = document.getElementById(
      "timeline-row-00000000-0000-0000-0000-00000000000a-status-label",
    );
    expect(firstStamp?.textContent).toBe("Occurred");

    // The mono event_id is shown verbatim.
    expect(
      document.getElementById(
        "timeline-row-00000000-0000-0000-0000-00000000000a-event-id",
      )?.textContent,
    ).toBe("00000000-0000-0000-0000-00000000000a");
  });

  it("shows the always-present empty note when the lead has no events", async () => {
    getLeadTimelineMock.mockResolvedValue([]);

    render(<LeadTimeline id="timeline" leadId="lead-1" />);

    await waitFor(() => {
      expect(document.getElementById("timeline-empty")).toBeInTheDocument();
    });
    // The console still renders (its overline) — never hidden on empty.
    expect(document.getElementById("timeline-overline")).toBeInTheDocument();
    expect(document.getElementById("timeline-empty")?.textContent).toBe(
      "No events recorded for this lead yet.",
    );
    // No row list when empty.
    expect(document.getElementById("timeline-list")).not.toBeInTheDocument();
  });

  it("shows a calm error note when the fetch fails", async () => {
    getLeadTimelineMock.mockRejectedValue(new Error("boom"));

    render(<LeadTimeline id="timeline" leadId="lead-1" />);

    await waitFor(() => {
      expect(document.getElementById("timeline-error")).toBeInTheDocument();
    });
    expect(document.getElementById("timeline-overline")).toBeInTheDocument();
  });

  it("renders a full-words relative time with the absolute UTC on hover", async () => {
    // Far in the past so the relative bucket is stable regardless of when tests run.
    getLeadTimelineMock.mockResolvedValue([
      makeRow({
        occurred_at: "2020-01-01T00:00:00Z",
        event_id: "00000000-0000-0000-0000-00000000000c",
      }),
    ]);

    render(<LeadTimeline id="timeline" leadId="lead-1" />);

    await waitFor(() => {
      expect(document.getElementById("timeline-list")).toBeInTheDocument();
    });

    const timeNode = document.getElementById(
      "timeline-row-00000000-0000-0000-0000-00000000000c-time",
    );
    // A long-past event reads in full-words "N days ago", and the hover title is the
    // fixed-width UTC stamp.
    expect(timeNode?.textContent).toMatch(/days ago$/);
    expect(timeNode?.getAttribute("title")).toBe("2020-01-01 00:00:00 UTC");
  });
});
