// Tests for the graceful-expiry notice (P1.8 Epic 12). The gate is a self-contained
// info Banner — it reads its identity + `assumePersona` straight from `useSession`,
// so it renders in isolation with the session mocked. Follows the suite's pattern —
// @testing-library/react + fireEvent (user-event is not a project dependency).
// Covers: the calm info-banner copy renders (never an error hue); the button
// re-assumes the CURRENT persona then hard-reloads to /app/leads; Platform Admin's
// null tenant_slug re-assumes with an empty string (the backend ignores the slug for
// that role); and a failed re-assume shows an inline aria-live error and stays put.

import { fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import DemoSessionGate from "./DemoSessionGate.tsx";
import type { Identity } from "../api";
import { useSession } from "../session";

vi.mock("../session", () => ({
  useSession: vi.fn(),
}));

const useSessionMock = vi.mocked(useSession);

const agentIdentity: Identity = {
  user: {
    id: "11111111-1111-1111-1111-111111111111",
    username: "agent.one@sunshine.example",
    role: "agent",
    tenant_id: "22222222-2222-2222-2222-222222222222",
    tenant_slug: "sunshine-senior-benefits",
    tenant_name: "Sunshine Senior Benefits",
  },
  capabilities: ["create_edit_records", "claim_leads_manage_tasks", "reveal_pii"],
};

const platformAdminIdentity: Identity = {
  user: {
    id: "33333333-3333-3333-3333-333333333333",
    username: "platform.admin@policyflow.example",
    role: "platform_admin",
    tenant_id: null,
    tenant_slug: null,
    tenant_name: null,
  },
  capabilities: [],
};

function sessionFor(identity: Identity, assumePersona = vi.fn()) {
  return {
    status: "signed-in" as const,
    identity,
    capabilities: identity.capabilities,
    assumePersona,
    signOut: vi.fn(),
  };
}

// jsdom does not implement navigation — swap window.location for an object whose
// assign() is observable, restoring the original after each test.
function stubLocationAssign() {
  const assign = vi.fn();
  const originalLocation = window.location;
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { ...originalLocation, assign },
  });
  return {
    assign,
    restore() {
      Object.defineProperty(window, "location", {
        configurable: true,
        value: originalLocation,
      });
    },
  };
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("DemoSessionGate", () => {
  it("renders the calm info banner with the reset explainer (never an error hue)", () => {
    useSessionMock.mockReturnValue(sessionFor(agentIdentity));
    render(<DemoSessionGate />);

    const gate = document.getElementById("demo-session-gate")!;
    expect(gate).toBeInTheDocument();
    expect(document.getElementById("demo-session-gate-icon")).toBeInTheDocument();
    expect(
      document.getElementById("demo-session-gate-message"),
    ).toHaveTextContent(
      "Your demo session ended. Demo data resets every 24 hours to keep the sandbox clean — your agency is preserved.",
    );
    // The action reads as itself the whole way through the flow.
    expect(
      document.getElementById("demo-session-gate-start-button-label"),
    ).toHaveTextContent("Start a fresh session");
    // No error in the steady state.
    expect(
      document.getElementById("demo-session-gate-error"),
    ).toHaveTextContent("");
  });

  it("re-assumes the current persona, then hard-reloads to /app/leads", async () => {
    const assumePersona = vi.fn().mockResolvedValue(undefined);
    useSessionMock.mockReturnValue(sessionFor(agentIdentity, assumePersona));
    const location = stubLocationAssign();

    try {
      render(<DemoSessionGate />);
      fireEvent.click(
        document.getElementById("demo-session-gate-start-button")!,
      );

      await waitFor(() => {
        expect(location.assign).toHaveBeenCalledWith("/app/leads");
      });
      expect(assumePersona).toHaveBeenCalledWith(
        "sunshine-senior-benefits",
        "agent",
      );
    } finally {
      location.restore();
    }
  });

  it("re-assumes a tenantless Platform Admin with an empty slug", async () => {
    const assumePersona = vi.fn().mockResolvedValue(undefined);
    useSessionMock.mockReturnValue(
      sessionFor(platformAdminIdentity, assumePersona),
    );
    const location = stubLocationAssign();

    try {
      render(<DemoSessionGate />);
      fireEvent.click(
        document.getElementById("demo-session-gate-start-button")!,
      );

      await waitFor(() => {
        expect(assumePersona).toHaveBeenCalledWith("", "platform_admin");
      });
      expect(location.assign).toHaveBeenCalledWith("/app/leads");
    } finally {
      location.restore();
    }
  });

  it("shows an inline error and stays on the page when the re-assume fails", async () => {
    const assumePersona = vi.fn().mockRejectedValue(new Error("mint failed"));
    useSessionMock.mockReturnValue(sessionFor(agentIdentity, assumePersona));
    const location = stubLocationAssign();

    try {
      render(<DemoSessionGate />);
      fireEvent.click(
        document.getElementById("demo-session-gate-start-button")!,
      );

      await waitFor(() => {
        expect(
          document.getElementById("demo-session-gate-error"),
        ).toHaveTextContent(
          "We couldn't start a fresh session. Please try again.",
        );
      });
      // Never trap the visitor — no navigation on failure, the gate stays mounted.
      expect(location.assign).not.toHaveBeenCalled();
      expect(document.getElementById("demo-session-gate")).toBeInTheDocument();
    } finally {
      location.restore();
    }
  });
});
