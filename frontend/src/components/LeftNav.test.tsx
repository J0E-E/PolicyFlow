// Tests for the left-nav rail. LeftNav is pure given a role + capabilities
// (AppShell threads the session in), but it renders a live NavLink for "Demo home"
// so each render is wrapped in a MemoryRouter (the suite's router pattern; no
// @testing-library/user-event — not a project dependency). These assert, per the
// Guide §4 nav spec + §7 a11y checklist: the "Primary" landmark, each role seeing
// exactly its sections, Platform Admin seeing ONLY Platform Health & DLQ (+ Demo
// home), the future items being inert non-links, and "Demo home" being the one live
// /app link carrying the active marker.

import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import type { Capability, Role } from "../api";
import LeftNav from "./LeftNav.tsx";

// The capability sets the backend RBAC matrix returns per role (only the
// nav-relevant capabilities matter here — the rail reads no others).
const AGENT_CAPABILITIES: Capability[] = ["view_tenant_records", "view_dashboards"];
const TENANT_ADMIN_CAPABILITIES: Capability[] = [
  "view_tenant_records",
  "view_dashboards",
  "view_audit_logs",
];
const READ_ONLY_CAPABILITIES: Capability[] = [
  "view_tenant_records",
  "view_dashboards",
  "view_audit_logs",
];
const PLATFORM_ADMIN_CAPABILITIES: Capability[] = ["platform_health_demo_controls"];

function renderRail(
  role: Role,
  capabilities: Capability[],
  initialPath = "/app",
) {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <LeftNav role={role} capabilities={capabilities} />
    </MemoryRouter>,
  );
}

// The stable section keys, in render order (mirrors navSections.ts).
const ALL_KEYS = [
  "demo-home",
  "leads",
  "contacts",
  "households",
  "opportunities",
  "policies",
  "tasks",
  "dashboards",
  "audit-log",
  "outbox",
  "platform-health",
] as const;

function visibleKeys(): string[] {
  return ALL_KEYS.filter(
    (key) => document.getElementById(`left-nav-row-${key}`) !== null,
  );
}

describe("LeftNav", () => {
  it("is the Primary navigation landmark", () => {
    renderRail("agent", AGENT_CAPABILITIES);
    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(nav).toBe(document.getElementById("left-nav"));
  });

  it("shows the Agent sections: Demo home + 6 CRM + Dashboards", () => {
    renderRail("agent", AGENT_CAPABILITIES);
    expect(visibleKeys()).toEqual([
      "demo-home",
      "leads",
      "contacts",
      "households",
      "opportunities",
      "policies",
      "tasks",
      "dashboards",
    ]);
  });

  it("adds Audit Log + Outbox for Tenant Admin", () => {
    renderRail("tenant_admin", TENANT_ADMIN_CAPABILITIES);
    expect(visibleKeys()).toEqual([
      "demo-home",
      "leads",
      "contacts",
      "households",
      "opportunities",
      "policies",
      "tasks",
      "dashboards",
      "audit-log",
      "outbox",
    ]);
  });

  it("shows Read-Only: CRM + Dashboards + Audit Log, but NOT Outbox", () => {
    renderRail("read_only", READ_ONLY_CAPABILITIES);
    expect(visibleKeys()).toEqual([
      "demo-home",
      "leads",
      "contacts",
      "households",
      "opportunities",
      "policies",
      "tasks",
      "dashboards",
      "audit-log",
    ]);
    // Outbox is Tenant-Admin-only (gated on role), never Read-Only.
    expect(document.getElementById("left-nav-row-outbox")).toBeNull();
  });

  it("shows Platform Admin ONLY Platform Health & DLQ (plus Demo home)", () => {
    renderRail("platform_admin", PLATFORM_ADMIN_CAPABILITIES);
    expect(visibleKeys()).toEqual(["demo-home", "platform-health"]);
    // No tenant scope: none of the CRM / dashboards / audit / outbox sections.
    expect(document.getElementById("left-nav-row-leads")).toBeNull();
    expect(document.getElementById("left-nav-row-dashboards")).toBeNull();
    expect(document.getElementById("left-nav-row-audit-log")).toBeNull();
    expect(document.getElementById("left-nav-row-outbox")).toBeNull();
  });

  it("renders Demo home as the one live /app link with the active marker", () => {
    renderRail("agent", AGENT_CAPABILITIES, "/app");

    const demoHome = document.getElementById("left-nav-item-demo-home");
    // A real anchor to /app (not an inert span).
    expect(demoHome?.tagName).toBe("A");
    expect(demoHome).toHaveAttribute("href", "/app");
    // On the /app route it is the active item: --primary marker + aria-current.
    expect(demoHome).toHaveAttribute("aria-current", "page");
    expect(demoHome).toHaveClass("nav-item-active");
  });

  it("does not mark Demo home active when the route is elsewhere", () => {
    renderRail("agent", AGENT_CAPABILITIES, "/app/leads");
    const demoHome = document.getElementById("left-nav-item-demo-home");
    // `end` matching: /app is not active under a deeper child route.
    expect(demoHome).not.toHaveClass("nav-item-active");
    expect(demoHome).not.toHaveAttribute("aria-current");
  });

  it("renders every future section as an inert, non-link, dimmed item", () => {
    renderRail("agent", AGENT_CAPABILITIES);

    for (const key of ALL_KEYS) {
      // Demo home and Leads are the live links (P1.7, Epic 20) — not inert.
      if (key === "demo-home" || key === "leads") continue;
      const row = document.getElementById(`left-nav-row-${key}`);
      if (!row) continue; // not visible for this role — covered by the count tests
      const item = document.getElementById(`left-nav-item-${key}`);
      // Inert: not an anchor, no href, announced disabled, with a coming-later hint.
      expect(item?.tagName).not.toBe("A");
      expect(item).not.toHaveAttribute("href");
      expect(item).toHaveAttribute("aria-disabled", "true");
      expect(
        document.getElementById(`left-nav-item-${key}-hint`),
      ).toHaveTextContent("Coming in a later step");
    }
  });

  it("has the live Demo home link first in focus/DOM order, then Leads", () => {
    renderRail("agent", AGENT_CAPABILITIES);
    const nav = document.getElementById("left-nav")!;
    // The focusable controls in the rail are the live links (inert items are
    // non-focusable spans): Demo home leads, then Leads (P1.7, Epic 20), both in
    // the rail's DOM order (Guide §7 focus order).
    const links = within(nav).getAllByRole("link");
    expect(links).toHaveLength(2);
    expect(links[0]).toBe(document.getElementById("left-nav-item-demo-home"));
    expect(links[1]).toBe(document.getElementById("left-nav-item-leads"));
  });
});
