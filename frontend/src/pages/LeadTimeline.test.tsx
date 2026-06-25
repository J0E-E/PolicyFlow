// Tests for the per-lead EVENT TIMELINE ink console (P1.9 Epics 1 + 2). jsdom has no
// backend, so `../api` is mocked: getLeadTimeline drives the console's single fetch on
// open. Covers: the console always renders (overline present), event rows render in the
// order the read returns (oldest-first), the always-present empty state, the error note,
// the full-words relative-time label on a row, and (Epic 2) reaction sibling rows —
// indented siblings with the correct bright stamp/hue per status, the fan-out, and the
// spinner on `processing`.

import { act, fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import LeadTimeline from "./LeadTimeline.tsx";
import type { TimelineEventRow, TimelineReactionRow } from "../api";

vi.mock("../api", () => ({
  getLeadTimeline: vi.fn(),
  // The real ApiError so `error instanceof ApiError` and `.status` work in the poll.
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

import { ApiError, getLeadTimeline } from "../api";

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

  it("renders the result summary as a sub-line on a reaction that carries one", async () => {
    // The done enrichment reaction carries its deterministic quality-score summary; it
    // renders verbatim as the indented mono sub-line under the consumer name (Epic 3).
    getLeadTimelineMock.mockResolvedValue([
      makeRow({ event_id: "00000000-0000-0000-0000-0000000000ee" }),
      makeReactionRow({
        event_id: "00000000-0000-0000-0000-0000000000ee",
        consumer_name: "enrichment.stub",
        status: "done",
        result_summary: "Quality score 73/100 · Medium",
      }),
    ]);

    render(<LeadTimeline id="timeline" leadId="lead-1" />);

    await waitFor(() => {
      expect(document.getElementById("timeline-list")).toBeInTheDocument();
    });

    const summary = document.getElementById(
      "timeline-reaction-00000000-0000-0000-0000-0000000000ee-enrichment.stub-summary",
    );
    expect(summary?.textContent).toBe("Quality score 73/100 · Medium");
  });

  it("omits the summary sub-line when the reaction has a null result_summary", async () => {
    // The sync logger yields no analytic result (null summary) even when done — the
    // sub-line is omitted entirely, the status stamp alone disambiguates the state.
    getLeadTimelineMock.mockResolvedValue([
      makeRow({ event_id: "00000000-0000-0000-0000-0000000000ff" }),
      makeReactionRow({
        event_id: "00000000-0000-0000-0000-0000000000ff",
        consumer_name: "sync.logger",
        status: "done",
        result_summary: null,
      }),
    ]);

    render(<LeadTimeline id="timeline" leadId="lead-1" />);

    await waitFor(() => {
      expect(document.getElementById("timeline-list")).toBeInTheDocument();
    });

    expect(
      document.getElementById(
        "timeline-reaction-00000000-0000-0000-0000-0000000000ff-sync.logger-summary",
      ),
    ).toBeNull();
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

  // Epic 6 — the per-row "Simulated" badge marks each canned consumer effect, and ONE
  // outbox explainer (console chrome) carries the mechanism story behind the reactions.
  describe("simulated badge + outbox explainer (Epic 6)", () => {
    it("carries a Simulated badge on each reaction row, none on event rows", async () => {
      getLeadTimelineMock.mockResolvedValue([
        makeRow({ event_id: "00000000-0000-0000-0000-0000000000a6" }),
        makeReactionRow({
          event_id: "00000000-0000-0000-0000-0000000000a6",
          consumer_name: "enrichment.stub",
          status: "done",
        }),
        makeReactionRow({
          event_id: "00000000-0000-0000-0000-0000000000a6",
          consumer_name: "sync.logger",
          status: "done",
        }),
      ]);

      render(<LeadTimeline id="timeline" leadId="lead-1" />);

      await waitFor(() => {
        expect(document.getElementById("timeline-list")).toBeInTheDocument();
      });

      // Each reaction row carries its own Simulated badge trigger (derived from the row id).
      expect(
        document.getElementById(
          "timeline-reaction-00000000-0000-0000-0000-0000000000a6-enrichment.stub-simulated-trigger",
        ),
      ).toBeInTheDocument();
      expect(
        document.getElementById(
          "timeline-reaction-00000000-0000-0000-0000-0000000000a6-sync.logger-simulated-trigger",
        ),
      ).toBeInTheDocument();

      // The event row carries NO badge — a console-level/event badge would wrongly imply
      // the real domain events are simulated. Exactly one badge per reaction (two total).
      expect(
        document.getElementById(
          "timeline-row-00000000-0000-0000-0000-0000000000a6-simulated-trigger",
        ),
      ).toBeNull();
      expect(
        document.querySelectorAll(".simulated-badge-trigger"),
      ).toHaveLength(2);
    });

    it("renders exactly one outbox explainer on the console, opening to its four sections", async () => {
      getLeadTimelineMock.mockResolvedValue([
        makeRow({ event_id: "00000000-0000-0000-0000-0000000000a7" }),
      ]);

      render(<LeadTimeline id="timeline" leadId="lead-1" />);

      await waitFor(() => {
        expect(document.getElementById("timeline-list")).toBeInTheDocument();
      });

      // Exactly one explainer, in the console header beside the overline, naming the surface.
      const trigger = document.getElementById("timeline-explainer-outbox-trigger");
      expect(trigger).toBeInTheDocument();
      expect(trigger?.getAttribute("aria-label")).toBe(
        "Explain: the event timeline",
      );
      expect(
        document.getElementById("timeline-header"),
      ).toContainElement(trigger);
      expect(document.querySelectorAll(".explainer-trigger")).toHaveLength(1);

      // It opens to the four fixed sections (PATTERN / HOW / REAL VS SIMULATED / CRM PARALLEL).
      act(() => {
        fireEvent.click(trigger as HTMLElement);
      });
      for (const section of ["pattern", "how", "realVsSimulated", "crmParallel"]) {
        expect(
          document.getElementById(
            `timeline-explainer-outbox-section-${section}`,
          ),
        ).toBeInTheDocument();
      }
    });

    it("renders the outbox explainer once in every load state (it is console chrome)", async () => {
      // Loaded-empty: the explainer is present even with no rows.
      getLeadTimelineMock.mockResolvedValue([]);
      const { unmount } = render(<LeadTimeline id="timeline" leadId="lead-1" />);
      await waitFor(() => {
        expect(document.getElementById("timeline-empty")).toBeInTheDocument();
      });
      expect(
        document.querySelectorAll(".explainer-trigger"),
      ).toHaveLength(1);
      unmount();

      // Errored: the explainer still renders once.
      getLeadTimelineMock.mockRejectedValue(new Error("boom"));
      render(<LeadTimeline id="timeline" leadId="lead-1" />);
      await waitFor(() => {
        expect(document.getElementById("timeline-error")).toBeInTheDocument();
      });
      expect(
        document.getElementById("timeline-explainer-outbox-trigger"),
      ).toBeInTheDocument();
      expect(
        document.querySelectorAll(".explainer-trigger"),
      ).toHaveLength(1);
    });
  });

  // Epic 4 — the watchable moment: the armed poll re-fetches on a 1500 ms cadence while a
  // reaction is still advancing, and idle-stops once every reaction is terminal.
  describe("live poll", () => {
    beforeEach(() => {
      vi.useFakeTimers();
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    // Flushes the pending fetch-promise microtask chain (and the React render it triggers)
    // without advancing the 1500 ms poll timer — used to settle the mount fetch.
    async function flushFetch() {
      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
      });
    }

    // Drives the fake timers and flushes the fetch promise microtasks together so a tick's
    // re-fetch settles before the assertion. Real timers stay off for the duration.
    async function advancePoll() {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1500);
      });
    }

    function reactionStamp(eventId: string, consumer: string): string {
      return `timeline-reaction-${eventId}-${consumer}-status`;
    }

    it("advances a reaction pending → processing → done across ticks, then idle-stops", async () => {
      const eventId = "00000000-0000-0000-0000-0000000000a1";
      const pending = [
        makeRow({ event_id: eventId }),
        makeReactionRow({
          event_id: eventId,
          consumer_name: "enrichment.stub",
          status: "pending",
        }),
      ];
      const processing = [
        makeRow({ event_id: eventId }),
        makeReactionRow({
          event_id: eventId,
          consumer_name: "enrichment.stub",
          status: "processing",
        }),
      ];
      const done = [
        makeRow({ event_id: eventId }),
        makeReactionRow({
          event_id: eventId,
          consumer_name: "enrichment.stub",
          status: "done",
        }),
      ];
      getLeadTimelineMock
        .mockResolvedValueOnce(pending)
        .mockResolvedValueOnce(processing)
        .mockResolvedValueOnce(done);

      render(<LeadTimeline id="timeline" leadId="lead-1" />);

      const stampId = reactionStamp(eventId, "enrichment.stub");

      // First fetch settles to `pending` (neutral) — the loop is armed. Flush the mount
      // fetch's microtasks without advancing the 1500 ms timer.
      await flushFetch();
      expect(document.getElementById(`${stampId}-label`)?.textContent).toBe(
        "Pending",
      );

      // Tick → the re-fetch lands `processing` (blue, spinner).
      await advancePoll();
      expect(document.getElementById(`${stampId}-label`)?.textContent).toBe(
        "Processing",
      );

      // Tick → the re-fetch lands `done` (green, terminal).
      await advancePoll();
      expect(document.getElementById(`${stampId}-label`)?.textContent).toBe(
        "Done",
      );

      const callsAtTerminal = getLeadTimelineMock.mock.calls.length;
      expect(callsAtTerminal).toBe(3);

      // Once terminal the loop idle-stops: further ticks issue no more fetches.
      await advancePoll();
      await advancePoll();
      expect(getLeadTimelineMock.mock.calls.length).toBe(callsAtTerminal);
    });

    it("does not poll again when the first fetch is already all-terminal", async () => {
      const eventId = "00000000-0000-0000-0000-0000000000a2";
      getLeadTimelineMock.mockResolvedValue([
        makeRow({ event_id: eventId }),
        makeReactionRow({
          event_id: eventId,
          consumer_name: "sync.logger",
          status: "done",
        }),
      ]);

      render(<LeadTimeline id="timeline" leadId="lead-1" />);

      await flushFetch();
      expect(document.getElementById("timeline-list")).toBeInTheDocument();
      expect(getLeadTimelineMock).toHaveBeenCalledTimes(1);

      // No reaction is in flight, so the loop never arms a second fetch.
      await advancePoll();
      await advancePoll();
      expect(getLeadTimelineMock).toHaveBeenCalledTimes(1);
    });

    it("re-arms the idle poll when the re-arm key changes (a qualify/reject)", async () => {
      const eventId = "00000000-0000-0000-0000-0000000000a3";
      const terminal = [
        makeRow({ event_id: eventId }),
        makeReactionRow({
          event_id: eventId,
          consumer_name: "sync.logger",
          status: "done",
        }),
      ];
      const reArmed = [
        makeRow({ event_id: eventId }),
        makeReactionRow({
          event_id: eventId,
          consumer_name: "sync.logger",
          status: "done",
        }),
        makeRow({
          event_type: "lead.qualified",
          event_id: "00000000-0000-0000-0000-0000000000b3",
        }),
        makeReactionRow({
          event_type: "lead.qualified",
          event_id: "00000000-0000-0000-0000-0000000000b3",
          consumer_name: "sync.logger",
          status: "pending",
        }),
      ];
      getLeadTimelineMock.mockResolvedValue(terminal);

      const { rerender } = render(
        <LeadTimeline id="timeline" leadId="lead-1" reArmKey="t0" />,
      );

      // The first key settles all-terminal → the loop idle-stops at one fetch.
      await flushFetch();
      expect(getLeadTimelineMock).toHaveBeenCalledTimes(1);
      await advancePoll();
      expect(getLeadTimelineMock).toHaveBeenCalledTimes(1);

      // A qualify bumps `updated_at` → the re-arm key changes, restarting the loop. The
      // re-fetch now carries a fresh pending reaction, so the loop keeps polling.
      getLeadTimelineMock.mockResolvedValue(reArmed);
      rerender(<LeadTimeline id="timeline" leadId="lead-1" reArmKey="t1" />);

      await flushFetch();
      expect(getLeadTimelineMock).toHaveBeenCalledTimes(2);
      // The new pending reaction keeps the loop armed across the next tick.
      await advancePoll();
      expect(getLeadTimelineMock).toHaveBeenCalledTimes(3);
    });

    it("stops the poll and fires onSessionExpired on a 404, showing its calm note", async () => {
      const eventId = "00000000-0000-0000-0000-0000000000a4";
      // First fetch arms the loop (a pending reaction); the next poll 404s (gone session).
      getLeadTimelineMock
        .mockResolvedValueOnce([
          makeRow({ event_id: eventId }),
          makeReactionRow({
            event_id: eventId,
            consumer_name: "enrichment.stub",
            status: "pending",
          }),
        ])
        .mockRejectedValueOnce(new ApiError(404, "Not found"));
      const onSessionExpired = vi.fn();

      render(
        <LeadTimeline
          id="timeline"
          leadId="lead-1"
          onSessionExpired={onSessionExpired}
        />,
      );

      // Mount fetch lands the pending reaction — armed.
      await flushFetch();
      expect(document.getElementById("timeline-list")).toBeInTheDocument();

      // Next tick 404s: the page is notified and the console falls back to its calm note.
      await advancePoll();
      expect(onSessionExpired).toHaveBeenCalledTimes(1);
      expect(document.getElementById("timeline-empty")?.textContent).toBe(
        "No events recorded for this lead yet.",
      );

      // The poll is stopped — no further fetches even though a reaction was mid-flight.
      const callsAfter404 = getLeadTimelineMock.mock.calls.length;
      await advancePoll();
      await advancePoll();
      expect(getLeadTimelineMock.mock.calls.length).toBe(callsAfter404);
    });

    it("keeps the retryable error note on a non-404 failure (no expiry signal)", async () => {
      getLeadTimelineMock.mockRejectedValue(new ApiError(500, "boom"));
      const onSessionExpired = vi.fn();

      render(
        <LeadTimeline
          id="timeline"
          leadId="lead-1"
          onSessionExpired={onSessionExpired}
        />,
      );

      await flushFetch();
      // A server error is the calm retryable error note, not an expiry — never the gate.
      expect(document.getElementById("timeline-error")).toBeInTheDocument();
      expect(onSessionExpired).not.toHaveBeenCalled();
    });
  });

  // Epic 7 — the named acceptance hardening. The per-slice tests above already prove the
  // mechanics (Epic 4's pending→processing→done poll, Epic 6's per-row badge + single
  // explainer). This block ties the two *frontend* TDD §8 acceptance criteria to named
  // end-to-end assertions, adding the one piece the slices don't already pin: the quality
  // score *appearing live* on the same tick the enrichment reaction flips to `done`, with
  // no manual refetch (#1's "watch the quality score appear"). It does not re-assert the
  // hue/spinner/label mechanics — those are owned above.
  describe("acceptance criteria (Epic 7)", () => {
    beforeEach(() => {
      vi.useFakeTimers();
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    // Settle the mount fetch's microtasks without advancing the 1500 ms poll timer.
    async function flushFetch() {
      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
      });
    }

    // Advance one poll tick and settle its re-fetch.
    async function advancePoll() {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1500);
      });
    }

    it("#1 live moment: the enrichment reaction reaches done and its quality score appears, no manual refetch", async () => {
      // The walkthrough payoff: a freshly created lead's enrichment reaction advances on a
      // live poll and, on the tick it flips to `done`, its deterministic quality-score
      // summary appears on screen — the viewer never refetches by hand.
      const eventId = "00000000-0000-0000-0000-0000000000e1";
      const summaryId = `timeline-reaction-${eventId}-enrichment.stub-summary`;
      const processing = [
        makeRow({ event_id: eventId }),
        makeReactionRow({
          event_id: eventId,
          consumer_name: "enrichment.stub",
          status: "processing",
          result_summary: null,
        }),
      ];
      const done = [
        makeRow({ event_id: eventId }),
        makeReactionRow({
          event_id: eventId,
          consumer_name: "enrichment.stub",
          status: "done",
          result_summary: "Quality score 73/100 · Medium",
        }),
      ];
      getLeadTimelineMock
        .mockResolvedValueOnce(processing)
        .mockResolvedValueOnce(done);

      render(<LeadTimeline id="timeline" leadId="lead-1" />);

      // Mount fetch: processing, no score yet. The loop is armed (a reaction is in flight).
      await flushFetch();
      expect(
        document.getElementById(
          `timeline-reaction-${eventId}-enrichment.stub-status-label`,
        )?.textContent,
      ).toBe("Processing");
      expect(document.getElementById(summaryId)).toBeNull();

      // One live tick later — no manual refetch — the reaction is `done` and the quality
      // score sub-line has appeared verbatim.
      await advancePoll();
      expect(
        document.getElementById(
          `timeline-reaction-${eventId}-enrichment.stub-status-label`,
        )?.textContent,
      ).toBe("Done");
      expect(document.getElementById(summaryId)?.textContent).toBe(
        "Quality score 73/100 · Medium",
      );
    });

    it("#4 every reaction row carries a Simulated badge and the console carries exactly one outbox explainer", async () => {
      // Both stub reactions are marked simulated (per-row), event rows are not, and the
      // mechanism story is carried by exactly one console-level explainer.
      const eventId = "00000000-0000-0000-0000-0000000000e4";
      getLeadTimelineMock.mockResolvedValue([
        makeRow({ event_id: eventId }),
        makeReactionRow({
          event_id: eventId,
          consumer_name: "enrichment.stub",
          status: "done",
          result_summary: "Quality score 73/100 · Medium",
        }),
        makeReactionRow({
          event_id: eventId,
          consumer_name: "sync.logger",
          status: "done",
        }),
      ]);

      render(<LeadTimeline id="timeline" leadId="lead-1" />);

      await flushFetch();
      expect(document.getElementById("timeline-list")).toBeInTheDocument();

      // One Simulated badge per reaction row (two), none on the event row.
      expect(
        document.querySelectorAll(".simulated-badge-trigger"),
      ).toHaveLength(2);
      expect(
        document.getElementById(`timeline-row-${eventId}-simulated-trigger`),
      ).toBeNull();

      // Exactly one outbox explainer, on the console header.
      expect(
        document.querySelectorAll(".explainer-trigger"),
      ).toHaveLength(1);
      expect(
        document.getElementById("timeline-explainer-outbox-trigger"),
      ).toBeInTheDocument();
    });
  });
});
