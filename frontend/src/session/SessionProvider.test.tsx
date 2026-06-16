// Tests for the session provider, its actions, and the capability helper. There
// is no backend under jsdom, so the `../api` module is mocked with `vi.mock` and
// each test drives the mocked client calls. A small harness component reads
// `useSession()` / `useCapability()` and prints the values into the DOM so the
// assertions can read the rendered status, identity, and capability answers.

import { render, screen, waitFor } from "@testing-library/react";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Identity } from "../api";
import { SessionProvider } from "./SessionProvider";
import { useSession } from "./SessionContext";
import { useCapability } from "./useCapability";

// Mock the API barrel: the provider imports `getCurrentIdentity`,
// `assumePersona`, and `signOut` from `../api`, and the tests control each.
vi.mock("../api", () => ({
  getCurrentIdentity: vi.fn(),
  assumePersona: vi.fn(),
  signOut: vi.fn(),
}));

// Import the mocked functions after the mock is registered so the tests and the
// provider share the same mock instances.
import { assumePersona, getCurrentIdentity, signOut } from "../api";

const getCurrentIdentityMock = vi.mocked(getCurrentIdentity);
const assumePersonaMock = vi.mocked(assumePersona);
const signOutMock = vi.mocked(signOut);

const agentIdentity: Identity = {
  user: {
    id: "11111111-1111-1111-1111-111111111111",
    username: "agent.one",
    role: "agent",
    tenant_id: "22222222-2222-2222-2222-222222222222",
    tenant_slug: "sunshine-senior-benefits",
    tenant_name: "Sunshine Senior Benefits",
  },
  capabilities: [
    "claim_leads_manage_tasks",
    "create_edit_records",
    "view_tenant_records",
  ],
};

const tenantAdminIdentity: Identity = {
  user: {
    id: "33333333-3333-3333-3333-333333333333",
    username: "admin.one",
    role: "tenant_admin",
    tenant_id: "22222222-2222-2222-2222-222222222222",
    tenant_slug: "sunshine-senior-benefits",
    tenant_name: "Sunshine Senior Benefits",
  },
  capabilities: ["view_audit_logs", "view_tenant_config"],
};

/** A harness that prints the session status, role, and capability list. */
function SessionReadout() {
  const { status, identity, capabilities } = useSession();
  return (
    <div>
      <span data-testid="status">{status}</span>
      <span data-testid="role">{identity ? identity.user.role : "none"}</span>
      <span data-testid="capabilities">{capabilities.join(",")}</span>
    </div>
  );
}

/** A harness that prints whether a single capability is held. */
function CapabilityReadout({
  capability,
}: {
  capability: Parameters<typeof useCapability>[0];
}) {
  const isAllowed = useCapability(capability);
  return <span data-testid="is-allowed">{String(isAllowed)}</span>;
}

beforeEach(() => {
  getCurrentIdentityMock.mockReset();
  assumePersonaMock.mockReset();
  signOutMock.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("restore-on-mount lifecycle", () => {
  it("starts in the loading state before /me resolves", () => {
    // A never-settling promise keeps the provider in its initial state.
    getCurrentIdentityMock.mockReturnValue(new Promise(() => {}));

    render(
      <SessionProvider>
        <SessionReadout />
      </SessionProvider>,
    );

    expect(screen.getByTestId("status")).toHaveTextContent("loading");
    expect(screen.getByTestId("role")).toHaveTextContent("none");
  });

  it("moves to signed-in and exposes the identity when /me succeeds", async () => {
    getCurrentIdentityMock.mockResolvedValue(agentIdentity);

    render(
      <SessionProvider>
        <SessionReadout />
      </SessionProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("status")).toHaveTextContent("signed-in");
    });
    expect(screen.getByTestId("role")).toHaveTextContent("agent");
    expect(screen.getByTestId("capabilities")).toHaveTextContent(
      "claim_leads_manage_tasks,create_edit_records,view_tenant_records",
    );
  });

  it("fail-closes to signed-out when /me returns a clean 401", async () => {
    getCurrentIdentityMock.mockRejectedValue(
      new ApiErrorLike(401, "not signed in"),
    );

    render(
      <SessionProvider>
        <SessionReadout />
      </SessionProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("status")).toHaveTextContent("signed-out");
    });
    expect(screen.getByTestId("role")).toHaveTextContent("none");
    expect(screen.getByTestId("capabilities")).toHaveTextContent("");
  });

  it("fail-closes to signed-out on a non-401 failure (500 / no backend)", async () => {
    // A 500, or in local dev no backend at all (network drop), is treated the
    // same as a 401: signed-out. Three states only, fail-closed.
    getCurrentIdentityMock.mockRejectedValue(
      new ApiErrorLike(0, "network request failed"),
    );

    render(
      <SessionProvider>
        <SessionReadout />
      </SessionProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("status")).toHaveTextContent("signed-out");
    });
    expect(screen.getByTestId("role")).toHaveTextContent("none");
  });
});

describe("session actions", () => {
  it("assumePersona moves signed-out -> signed-in with the new identity", async () => {
    getCurrentIdentityMock.mockRejectedValue(
      new ApiErrorLike(401, "not signed in"),
    );
    assumePersonaMock.mockResolvedValue(agentIdentity);

    let assumePersonaAction: (() => Promise<void>) | null = null;

    function ActionHarness() {
      const session = useSession();
      assumePersonaAction = () => session.assumePersona("sunshine", "agent");
      return <SessionReadout />;
    }

    render(
      <SessionProvider>
        <ActionHarness />
      </SessionProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("status")).toHaveTextContent("signed-out");
    });

    await act(async () => {
      await assumePersonaAction!();
    });

    expect(assumePersonaMock).toHaveBeenCalledWith("sunshine", "agent");
    expect(screen.getByTestId("status")).toHaveTextContent("signed-in");
    expect(screen.getByTestId("role")).toHaveTextContent("agent");
    expect(screen.getByTestId("capabilities")).toHaveTextContent(
      "claim_leads_manage_tasks,create_edit_records,view_tenant_records",
    );
  });

  it("assumePersona refreshes identity from its own response (no second /me)", async () => {
    getCurrentIdentityMock.mockResolvedValue(agentIdentity);
    assumePersonaMock.mockResolvedValue(tenantAdminIdentity);

    let assumePersonaAction: (() => Promise<void>) | null = null;

    function ActionHarness() {
      const session = useSession();
      assumePersonaAction = () =>
        session.assumePersona("sunshine", "tenant_admin");
      return <SessionReadout />;
    }

    render(
      <SessionProvider>
        <ActionHarness />
      </SessionProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("role")).toHaveTextContent("agent");
    });

    await act(async () => {
      await assumePersonaAction!();
    });

    // The new identity came from assumePersona's response, not a re-fetch:
    // getCurrentIdentity is still called exactly once (the mount restore).
    expect(getCurrentIdentityMock).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("role")).toHaveTextContent("tenant_admin");
  });

  it("signOut moves signed-in -> signed-out and clears the identity", async () => {
    getCurrentIdentityMock.mockResolvedValue(agentIdentity);
    signOutMock.mockResolvedValue();

    let signOutAction: (() => Promise<void>) | null = null;

    function ActionHarness() {
      const session = useSession();
      signOutAction = () => session.signOut();
      return <SessionReadout />;
    }

    render(
      <SessionProvider>
        <ActionHarness />
      </SessionProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("status")).toHaveTextContent("signed-in");
    });

    await act(async () => {
      await signOutAction!();
    });

    expect(signOutMock).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("status")).toHaveTextContent("signed-out");
    expect(screen.getByTestId("role")).toHaveTextContent("none");
    expect(screen.getByTestId("capabilities")).toHaveTextContent("");
  });
});

describe("useCapability helper", () => {
  it("returns true for a held capability and false otherwise", async () => {
    getCurrentIdentityMock.mockResolvedValue(agentIdentity);

    function CapabilityPair() {
      return (
        <div>
          <div data-testid="held">
            <CapabilityReadoutLabel capability="create_edit_records" />
          </div>
          <div data-testid="missing">
            <CapabilityReadoutLabel capability="reveal_pii" />
          </div>
        </div>
      );
    }

    render(
      <SessionProvider>
        <CapabilityPair />
      </SessionProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("held")).toHaveTextContent("true");
    });
    expect(screen.getByTestId("missing")).toHaveTextContent("false");
  });

  it("returns false while signed out (empty capability list)", async () => {
    getCurrentIdentityMock.mockRejectedValue(
      new ApiErrorLike(401, "not signed in"),
    );

    render(
      <SessionProvider>
        <CapabilityReadout capability="create_edit_records" />
      </SessionProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("is-allowed")).toHaveTextContent("false");
    });
  });
});

describe("useSession outside a provider", () => {
  it("throws a clear error when used without a SessionProvider", () => {
    // React logs the thrown render error; silence it so the test output is clean.
    const consoleErrorSpy = vi
      .spyOn(console, "error")
      .mockImplementation(() => {});

    expect(() => render(<SessionReadout />)).toThrow(
      "useSession must be used inside a SessionProvider",
    );

    consoleErrorSpy.mockRestore();
  });
});

/** A minimal stand-in for the client's `ApiError` (the provider only cares
 * that the rejection is an Error; it does not branch on the status). */
class ApiErrorLike extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** A label that prints "true"/"false" for one capability via the helper. */
function CapabilityReadoutLabel({
  capability,
}: {
  capability: Parameters<typeof useCapability>[0];
}) {
  return String(useCapability(capability));
}
