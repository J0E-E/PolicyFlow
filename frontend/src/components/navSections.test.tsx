// Tests for the declarative nav model's gating predicate — the JSX-free core the
// rail filters on. These pin the gate semantics (always / capability / role) and
// the model's shape (one live item, the rest inert, "How it's built" omitted) so a
// later epic flipping an item live or adding a section gets a clear regression
// signal.

import { describe, expect, it } from "vitest";

import { NAV_SECTIONS, isSectionVisible } from "./navSections.ts";

describe("isSectionVisible", () => {
  it("always-gated items show regardless of role/capabilities", () => {
    expect(isSectionVisible({ always: true }, "platform_admin", [])).toBe(true);
    expect(isSectionVisible({ always: true }, "agent", [])).toBe(true);
  });

  it("capability gates check the session's capability list", () => {
    expect(
      isSectionVisible({ capability: "view_dashboards" }, "agent", [
        "view_dashboards",
      ]),
    ).toBe(true);
    expect(
      isSectionVisible({ capability: "view_dashboards" }, "agent", [
        "view_tenant_records",
      ]),
    ).toBe(false);
  });

  it("role gates match the active role exactly (Outbox is Tenant-Admin-only)", () => {
    expect(isSectionVisible({ role: "tenant_admin" }, "tenant_admin", [])).toBe(
      true,
    );
    expect(isSectionVisible({ role: "tenant_admin" }, "read_only", [])).toBe(
      false,
    );
  });
});

describe("NAV_SECTIONS model", () => {
  // The live items as of P2.4 (Epic 14): Demo home, Leads, Households,
  // Opportunities, and Tasks (in render order — Households sits between Leads and
  // Opportunities). Each carries a real route and false `comingLater`; every other
  // section stays inert.
  const LIVE_ROUTES: Record<string, string> = {
    "demo-home": "/app",
    leads: "/app/leads",
    households: "/app/households",
    opportunities: "/app/opportunities",
    tasks: "/app/tasks",
  };

  it("has exactly the live items Demo home, Leads, Households, Opportunities, and Tasks", () => {
    const live = NAV_SECTIONS.filter((section) => !section.comingLater);
    expect(live.map((section) => section.key)).toEqual([
      "demo-home",
      "leads",
      "households",
      "opportunities",
      "tasks",
    ]);
    for (const section of live) {
      expect(section.to).toBe(LIVE_ROUTES[section.key]);
    }
    // Demo home is the one always-shown item; Leads is capability-gated.
    const demoHome = live.find((section) => section.key === "demo-home");
    expect(demoHome?.gate).toEqual({ always: true });
  });

  it("marks every non-live item coming-later with no route", () => {
    for (const section of NAV_SECTIONS) {
      if (section.key in LIVE_ROUTES) continue;
      expect(section.comingLater).toBe(true);
      expect(section.to).toBeUndefined();
    }
  });

  it("omits 'How it's built' (the masthead carries that placeholder)", () => {
    const labels = NAV_SECTIONS.map((section) => section.label.toLowerCase());
    expect(labels.some((label) => label.includes("how it's built"))).toBe(false);
  });
});
