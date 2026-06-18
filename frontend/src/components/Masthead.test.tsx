// Tests for the app-shell masthead. The masthead is pure given an identity and an
// `assumePersona` (a stub here — AppShell threads the real one in), so it renders
// directly (no provider/router). These assert the two clusters, the tenant brand
// cluster, the role switcher (the active persona label now lives in a switcher
// chip), the Platform-Admin "OUTSIDE TENANT SCOPE" label, and — per the Guide §7
// accessibility checklist — that the inert affordances are disabled and properly
// labelled, not silently absent.

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Identity } from "../api";
import Masthead from "./Masthead.tsx";

// The switcher just needs a resolving stub; the switching behavior is covered by
// RoleSwitcher.test.tsx.
const assumePersonaStub = vi.fn().mockResolvedValue(undefined);

const agentIdentity: Identity = {
  user: {
    id: "11111111-1111-1111-1111-111111111111",
    username: "agent.one@sunshine.example",
    role: "agent",
    tenant_id: "22222222-2222-2222-2222-222222222222",
    tenant_slug: "sunshine-senior-benefits",
    tenant_name: "Sunshine Senior Benefits",
  },
  capabilities: [],
};

const platformAdminIdentity: Identity = {
  user: {
    id: "33333333-3333-3333-3333-333333333333",
    username: "platform.admin@example",
    role: "platform_admin",
    tenant_id: null,
    tenant_slug: null,
    tenant_name: null,
  },
  capabilities: [],
};

const tenantAdminIdentity: Identity = {
  user: {
    id: "44444444-4444-4444-4444-444444444444",
    username: "tenant.admin@sunshine.example",
    role: "tenant_admin",
    tenant_id: "22222222-2222-2222-2222-222222222222",
    tenant_slug: "sunshine-senior-benefits",
    tenant_name: "Sunshine Senior Benefits",
  },
  capabilities: [],
};

const readOnlyIdentity: Identity = {
  user: {
    id: "55555555-5555-5555-5555-555555555555",
    username: "read.only@sunshine.example",
    role: "read_only",
    tenant_id: "22222222-2222-2222-2222-222222222222",
    tenant_slug: "sunshine-senior-benefits",
    tenant_name: "Sunshine Senior Benefits",
  },
  capabilities: [],
};

describe("Masthead", () => {
  it("renders the left brand cluster: seal, wordmark, tenant name, switcher", () => {
    render(
      <Masthead identity={agentIdentity} assumePersona={assumePersonaStub} />,
    );

    expect(document.getElementById("app-masthead-wordmark")).toHaveTextContent(
      "PolicyFlow",
    );
    expect(document.getElementById("app-masthead-tenant-name")).toHaveTextContent(
      "Sunshine Senior Benefits",
    );
    // The active persona label now lives inside the role switcher (the active
    // chip is marked aria-pressed); there is no standalone persona indicator.
    const activeChip = document.getElementById(
      "app-masthead-role-switcher-agent",
    );
    expect(activeChip).toHaveAttribute("aria-pressed", "true");
    expect(
      document.getElementById("app-masthead-role-switcher-agent-label"),
    ).toHaveTextContent("Agent");

    // The seal points at the slug-named SVG so swapping art needs no code change.
    const seal = document.getElementById("app-masthead-seal");
    expect(seal).toHaveAttribute("src", "/seals/sunshine-senior-benefits.svg");
    // Decorative: empty alt + aria-hidden so the tenant name is not read twice.
    expect(seal).toHaveAttribute("alt", "");
    expect(seal).toHaveAttribute("aria-hidden", "true");
  });

  it("renders the static DEMO SESSION stamp placeholder", () => {
    render(
      <Masthead identity={agentIdentity} assumePersona={assumePersonaStub} />,
    );

    expect(
      document.getElementById("app-masthead-session-stamp"),
    ).toBeInTheDocument();
    // Natural-case in the DOM; CSS uppercases it (Stamp type).
    expect(
      document.getElementById("app-masthead-session-stamp-label"),
    ).toHaveTextContent("Demo session");
  });

  it("renders the notification bell as a disabled, labelled placeholder", () => {
    render(
      <Masthead identity={agentIdentity} assumePersona={assumePersonaStub} />,
    );

    const bell = screen.getByRole("button", { name: /notifications/i });
    expect(bell).toBe(document.getElementById("app-masthead-notifications-button"));
    expect(bell).toBeDisabled();
    expect(bell).toHaveAttribute("aria-disabled", "true");
  });

  it("renders the inert How it's built affordance, not a live link", () => {
    render(
      <Masthead identity={agentIdentity} assumePersona={assumePersonaStub} />,
    );

    const howItsBuilt = document.getElementById("app-masthead-how-its-built");
    expect(howItsBuilt).toHaveTextContent("How it's built");
    expect(howItsBuilt).toHaveAttribute("aria-disabled", "true");
    // Inert: it is not a real anchor with an href (Epic 21 wires it live).
    expect(howItsBuilt?.tagName).not.toBe("A");
    expect(howItsBuilt).not.toHaveAttribute("href");
  });

  it("omits the tenant brand cluster for the tenantless Platform Admin", () => {
    render(
      <Masthead
        identity={platformAdminIdentity}
        assumePersona={assumePersonaStub}
      />,
    );

    // No tenant scope: no seal, no tenant name (the masthead inverts to ink).
    expect(document.getElementById("app-masthead-seal")).toBeNull();
    expect(document.getElementById("app-masthead-tenant-name")).toBeNull();
    // The wordmark and the switcher still render; the active chip is Platform Admin.
    expect(document.getElementById("app-masthead-wordmark")).toBeInTheDocument();
    expect(
      document.getElementById("app-masthead-role-switcher-platform_admin"),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      document.getElementById("app-masthead-role-switcher-platform_admin-label"),
    ).toHaveTextContent("Platform Admin");
  });

  it("renders the OUTSIDE TENANT SCOPE label only for Platform Admin", () => {
    const { rerender } = render(
      <Masthead identity={agentIdentity} assumePersona={assumePersonaStub} />,
    );
    // A tenant-scoped persona has no platform-ops label.
    expect(document.getElementById("app-masthead-platform-ops")).toBeNull();

    rerender(
      <Masthead
        identity={platformAdminIdentity}
        assumePersona={assumePersonaStub}
      />,
    );
    expect(
      document.getElementById("app-masthead-platform-ops-label"),
    ).toHaveTextContent("PLATFORM OPERATIONS — OUTSIDE TENANT SCOPE");
  });

  it("shows the VIEW ONLY tag only for the Read-Only persona", () => {
    // Read-Only: the posture tag renders with its natural-case label (CSS
    // uppercases it) and an aria-hidden glyph.
    const { rerender } = render(
      <Masthead identity={readOnlyIdentity} assumePersona={assumePersonaStub} />,
    );
    expect(
      document.getElementById("app-masthead-view-only-label"),
    ).toHaveTextContent("View only");
    expect(
      document.getElementById("app-masthead-view-only-icon"),
    ).toHaveAttribute("aria-hidden", "true");

    // Absent for every other persona — the deliberate Guide §2.4 asymmetry.
    for (const identity of [
      agentIdentity,
      tenantAdminIdentity,
      platformAdminIdentity,
    ]) {
      rerender(
        <Masthead identity={identity} assumePersona={assumePersonaStub} />,
      );
      expect(document.getElementById("app-masthead-view-only")).toBeNull();
    }
  });
});
