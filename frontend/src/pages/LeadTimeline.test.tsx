// Tests for the per-lead EVENT TIMELINE ink console (P1.9 Epics 1 + 2). jsdom has no
// backend, so `../api` is mocked: getLeadTimeline drives the console's single fetch on
// open. Covers: the console always renders (overline present), event rows render in the
// order the read returns (oldest-first), the always-present empty state, the error note,
// the full-words relative-time label on a row, and (Epic 2) reaction sibling rows —
// indented siblings with the correct bright stamp/hue per status, the fan-out, and the
// spinner on `processing`.

import { render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import LeadTimeline from "./LeadTimeline.tsx";
import type { TimelineEventRow, TimelineReactionRow } from "../api";

vi.mock("../api", () => ({
  getLeadTimeline: vi.fn(),
}));

import { getLeadTimeline } from "../api";

const getLeadTimelineMock = vi.mocked(getLeadTimeline);

function makeRow(overrides: Partial<TimelineEventRow>): TimelineEventRow {
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

function makeReactionRow(
  overrides: Partial<TimelineReactionRow>,
): TimelineReactionRow {
  return {
    kind: "reaction",
    status: "pending",
    consumer_name: "enrichment.stub",
    event_type: "lead.created",
    occurred_at: null,
    event_id: "00000000-0000-0000-0000-000000000001",
    correlation_id: "11111111-1111-1111-1111-111111111111",
    result_summary: null,
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

  it("renders reaction rows as indented siblings under their parent event", async () => {
    // lead.created fans out to enrichment.stub then sync.logger (binding order). The
    // read returns the event followed by its two reaction siblings.
    getLeadTimelineMock.mockResolvedValue([
      makeRow({ event_id: "00000000-0000-0000-0000-0000000000aa" }),
      makeReactionRow({
        event_id: "00000000-0000-0000-0000-0000000000aa",
        consumer_name: "enrichment.stub",
        status: "processing",
      }),
      makeReactionRow({
        event_id: "00000000-0000-0000-0000-0000000000aa",
        consumer_name: "sync.logger",
        status: "done",
      }),
    ]);

    render(<LeadTimeline id="timeline" leadId="lead-1" />);

    await waitFor(() => {
      expect(document.getElementById("timeline-list")).toBeInTheDocument();
    });

    // Both consumers render as reaction siblings, named in mono, in binding order.
    const consumerNodes = Array.from(
      document.querySelectorAll(".lead-timeline-reaction-consumer"),
    ).map((node) => node.textContent);
    expect(consumerNodes).toEqual(["enrichment.stub", "sync.logger"]);

    // Each reaction carries its mono `└─` connector (aria-hidden decoration).
    const connector = document.getElementById(
      "timeline-reaction-00000000-0000-0000-0000-0000000000aa-enrichment.stub-connector",
    );
    expect(connector?.textContent).toBe("└─");
    expect(connector?.getAttribute("aria-hidden")).toBe("true");
  });

  it("stamps each reaction status with its label and hue, spinner on processing", async () => {
    getLeadTimelineMock.mockResolvedValue([
      makeRow({ event_id: "00000000-0000-0000-0000-0000000000bb" }),
      makeReactionRow({
        event_id: "00000000-0000-0000-0000-0000000000bb",
        consumer_name: "enrichment.stub",
        status: "processing",
      }),
      makeReactionRow({
        event_id: "00000000-0000-0000-0000-0000000000bb",
        consumer_name: "sync.logger",
        status: "done",
      }),
    ]);

    render(<LeadTimeline id="timeline" leadId="lead-1" />);

    await waitFor(() => {
      expect(document.getElementById("timeline-list")).toBeInTheDocument();
    });

    const enrichmentStampId =
      "timeline-reaction-00000000-0000-0000-0000-0000000000bb-enrichment.stub-status";
    const syncStampId =
      "timeline-reaction-00000000-0000-0000-0000-0000000000bb-sync.logger-status";

    // `processing` → the blue `pending` hue, "Processing" label, and a spinner.
    const enrichmentStamp = document.getElementById(enrichmentStampId);
    expect(enrichmentStamp?.className).toContain("stamp-tag-pending");
    expect(
      document.getElementById(`${enrichmentStampId}-label`)?.textContent,
    ).toBe("Processing");
    expect(
      document.getElementById(`${enrichmentStampId}-spinner`),
    ).toBeInTheDocument();

    // `done` → the green `success` hue, "Done" label, and NO spinner.
    const syncStamp = document.getElementById(syncStampId);
    expect(syncStamp?.className).toContain("stamp-tag-success");
    expect(document.getElementById(`${syncStampId}-label`)?.textContent).toBe(
      "Done",
    );
    expect(document.getElementById(`${syncStampId}-spinner`)).toBeNull();
  });

  it("stamps a pending reaction with the calm neutral hue and no spinner", async () => {
    getLeadTimelineMock.mockResolvedValue([
      makeRow({ event_id: "00000000-0000-0000-0000-0000000000cc" }),
      makeReactionRow({
        event_id: "00000000-0000-0000-0000-0000000000cc",
        consumer_name: "sync.logger",
        status: "pending",
      }),
    ]);

    render(<LeadTimeline id="timeline" leadId="lead-1" />);

    await waitFor(() => {
      expect(document.getElementById("timeline-list")).toBeInTheDocument();
    });

    const stampId =
      "timeline-reaction-00000000-0000-0000-0000-0000000000cc-sync.logger-status";
    // `pending` → neutral grey (information is not a signal, Guide §2.2), no spinner.
    expect(document.getElementById(stampId)?.className).toContain(
      "stamp-tag-neutral",
    );
    expect(document.getElementById(`${stampId}-label`)?.textContent).toBe(
      "Pending",
    );
    expect(document.getElementById(`${stampId}-spinner`)).toBeNull();
  });

  it("renders a single sync.logger reaction for a non-created lead event", async () => {
    // lead.assigned matches no enrichment routing key → only the `#` sync logger reacts.
    getLeadTimelineMock.mockResolvedValue([
      makeRow({
        event_type: "lead.assigned",
        event_id: "00000000-0000-0000-0000-0000000000dd",
      }),
      makeReactionRow({
        event_type: "lead.assigned",
        event_id: "00000000-0000-0000-0000-0000000000dd",
        consumer_name: "sync.logger",
        status: "done",
      }),
    ]);

    render(<LeadTimeline id="timeline" leadId="lead-1" />);

    await waitFor(() => {
      expect(document.getElementById("timeline-list")).toBeInTheDocument();
    });

    const consumerNodes = Array.from(
      document.querySelectorAll(".lead-timeline-reaction-consumer"),
    ).map((node) => node.textContent);
    expect(consumerNodes).toEqual(["sync.logger"]);
  });
});
