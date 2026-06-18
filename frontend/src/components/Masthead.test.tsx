// Tests for the app-shell masthead. The masthead is pure given an identity, so
// it renders directly (no provider/router). These assert the two clusters, the
// tenant brand cluster, the persona indicator, and — per the Guide §7
// accessibility checklist — that the inert affordances are disabled and properly
// labelled, not silently absent.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Identity } from "../api";
import Masthead from "./Masthead.tsx";

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

describe("Masthead", () => {
  it("renders the left brand cluster: seal, wordmark, tenant name, persona", () => {
    render(<Masthead identity={agentIdentity} />);

    expect(document.getElementById("app-masthead-wordmark")).toHaveTextContent(
      "PolicyFlow",
    );
    expect(document.getElementById("app-masthead-tenant-name")).toHaveTextContent(
      "Sunshine Senior Benefits",
    );
    expect(document.getElementById("app-masthead-persona-label")).toHaveTextContent(
      "Agent",
    );

    // The seal points at the slug-named SVG so swapping art needs no code change.
    const seal = document.getElementById("app-masthead-seal");
    expect(seal).toHaveAttribute("src", "/seals/sunshine-senior-benefits.svg");
    // Decorative: empty alt + aria-hidden so the tenant name is not read twice.
    expect(seal).toHaveAttribute("alt", "");
    expect(seal).toHaveAttribute("aria-hidden", "true");
  });

  it("renders the static DEMO SESSION stamp placeholder", () => {
    render(<Masthead identity={agentIdentity} />);

    expect(
      document.getElementById("app-masthead-session-stamp"),
    ).toBeInTheDocument();
    // Natural-case in the DOM; CSS uppercases it (Stamp type).
    expect(
      document.getElementById("app-masthead-session-stamp-label"),
    ).toHaveTextContent("Demo session");
  });

  it("renders the notification bell as a disabled, labelled placeholder", () => {
    render(<Masthead identity={agentIdentity} />);

    const bell = screen.getByRole("button", { name: /notifications/i });
    expect(bell).toBe(document.getElementById("app-masthead-notifications-button"));
    expect(bell).toBeDisabled();
    expect(bell).toHaveAttribute("aria-disabled", "true");
  });

  it("renders the inert How it's built affordance, not a live link", () => {
    render(<Masthead identity={agentIdentity} />);

    const howItsBuilt = document.getElementById("app-masthead-how-its-built");
    expect(howItsBuilt).toHaveTextContent("How it's built");
    expect(howItsBuilt).toHaveAttribute("aria-disabled", "true");
    // Inert: it is not a real anchor with an href (Epic 21 wires it live).
    expect(howItsBuilt?.tagName).not.toBe("A");
    expect(howItsBuilt).not.toHaveAttribute("href");
  });

  it("omits the tenant brand cluster for the tenantless Platform Admin", () => {
    render(<Masthead identity={platformAdminIdentity} />);

    // No tenant scope: no seal, no tenant name (Epic 11 owns the inversion).
    expect(document.getElementById("app-masthead-seal")).toBeNull();
    expect(document.getElementById("app-masthead-tenant-name")).toBeNull();
    // The wordmark and persona indicator still render.
    expect(document.getElementById("app-masthead-wordmark")).toBeInTheDocument();
    expect(document.getElementById("app-masthead-persona-label")).toHaveTextContent(
      "Platform Admin",
    );
  });
});
