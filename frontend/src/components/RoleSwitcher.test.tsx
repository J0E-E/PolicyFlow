// Tests for the masthead role switcher. It is presentational + local UI state
// (home-tenant ref, in-flight, error) and takes `assumePersona` as a prop, so it
// renders in isolation with a stub — no provider/router. Covers: a tenant-scoped
// switch targets the home tenant; the home tenant is restored after a
// Platform-Admin round-trip (Platform Admin is tenantless); the Platform-Admin
// path; the active-chip no-op short-circuits; a switch in flight disables all
// chips; and a failure surfaces a message and re-enables the chips.

import { fireEvent, render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import RoleSwitcher from "./RoleSwitcher.tsx";

const switcherId = "switcher";

describe("RoleSwitcher", () => {
  it("renders one chip per persona in order", () => {
    render(
      <RoleSwitcher
        id={switcherId}
        assumePersona={vi.fn().mockResolvedValue(undefined)}
        currentRole="agent"
        currentTenantSlug="sunshine-senior-benefits"
      />,
    );

    expect(document.getElementById(`${switcherId}-agent`)).toBeInTheDocument();
    expect(
      document.getElementById(`${switcherId}-tenant_admin`),
    ).toBeInTheDocument();
    expect(document.getElementById(`${switcherId}-read_only`)).toBeInTheDocument();
    expect(
      document.getElementById(`${switcherId}-platform_admin`),
    ).toBeInTheDocument();
  });

  it("switches a tenant-scoped persona within the current (home) tenant", async () => {
    const assumePersona = vi.fn().mockResolvedValue(undefined);
    render(
      <RoleSwitcher
        id={switcherId}
        assumePersona={assumePersona}
        currentRole="agent"
        currentTenantSlug="sunshine-senior-benefits"
      />,
    );

    fireEvent.click(document.getElementById(`${switcherId}-tenant_admin`)!);

    await waitFor(() => {
      expect(assumePersona).toHaveBeenCalledWith(
        "sunshine-senior-benefits",
        "tenant_admin",
      );
    });
  });

  it("routes Platform Admin tenantlessly (its target slug is ignored downstream)", async () => {
    const assumePersona = vi.fn().mockResolvedValue(undefined);
    render(
      <RoleSwitcher
        id={switcherId}
        assumePersona={assumePersona}
        currentRole="agent"
        currentTenantSlug="sunshine-senior-benefits"
      />,
    );

    fireEvent.click(document.getElementById(`${switcherId}-platform_admin`)!);

    await waitFor(() => {
      expect(assumePersona).toHaveBeenCalledWith(
        // The current slug is passed through; assumePersona ignores it for
        // Platform Admin (resolves the global tenantless admin).
        "sunshine-senior-benefits",
        "platform_admin",
      );
    });
  });

  it("returns from Platform Admin to the remembered home tenant", async () => {
    const assumePersona = vi.fn().mockResolvedValue(undefined);
    const { rerender } = render(
      <RoleSwitcher
        id={switcherId}
        assumePersona={assumePersona}
        currentRole="agent"
        currentTenantSlug="florida-family-planning"
      />,
    );

    // Go to Platform Admin (tenantless).
    fireEvent.click(document.getElementById(`${switcherId}-platform_admin`)!);
    await waitFor(() => {
      expect(assumePersona).toHaveBeenCalledWith(
        "florida-family-planning",
        "platform_admin",
      );
    });

    // The session is now Platform Admin: re-identify with the tenantless props.
    rerender(
      <RoleSwitcher
        id={switcherId}
        assumePersona={assumePersona}
        currentRole="platform_admin"
        currentTenantSlug={null}
      />,
    );

    // Switch back to a tenant-scoped role — it lands back in the remembered home
    // tenant even though the current slug is now null.
    fireEvent.click(document.getElementById(`${switcherId}-agent`)!);
    await waitFor(() => {
      expect(assumePersona).toHaveBeenLastCalledWith(
        "florida-family-planning",
        "agent",
      );
    });
  });

  it("does not call assumePersona when the active persona is clicked", () => {
    const assumePersona = vi.fn().mockResolvedValue(undefined);
    render(
      <RoleSwitcher
        id={switcherId}
        assumePersona={assumePersona}
        currentRole="agent"
        currentTenantSlug="sunshine-senior-benefits"
      />,
    );

    fireEvent.click(document.getElementById(`${switcherId}-agent`)!);
    expect(assumePersona).not.toHaveBeenCalled();
  });

  it("disables all chips while a switch is in flight", async () => {
    // A never-settling promise holds the switcher in its in-flight state.
    const assumePersona = vi.fn().mockReturnValue(new Promise(() => {}));
    render(
      <RoleSwitcher
        id={switcherId}
        assumePersona={assumePersona}
        currentRole="agent"
        currentTenantSlug="sunshine-senior-benefits"
      />,
    );

    fireEvent.click(document.getElementById(`${switcherId}-tenant_admin`)!);

    await waitFor(() => {
      expect(document.getElementById(`${switcherId}-agent`)).toBeDisabled();
      expect(
        document.getElementById(`${switcherId}-tenant_admin`),
      ).toBeDisabled();
      expect(document.getElementById(`${switcherId}-read_only`)).toBeDisabled();
      expect(
        document.getElementById(`${switcherId}-platform_admin`),
      ).toBeDisabled();
    });
    // The live status announces the switch.
    expect(document.getElementById(`${switcherId}-message`)).toHaveTextContent(
      "Switching…",
    );
  });

  it("surfaces an error and re-enables the chips when the switch fails", async () => {
    const assumePersona = vi.fn().mockRejectedValue(new Error("denied"));
    render(
      <RoleSwitcher
        id={switcherId}
        assumePersona={assumePersona}
        currentRole="agent"
        currentTenantSlug="sunshine-senior-benefits"
      />,
    );

    fireEvent.click(document.getElementById(`${switcherId}-tenant_admin`)!);

    await waitFor(() => {
      expect(document.getElementById(`${switcherId}-message`)).toHaveTextContent(
        "Could not switch persona. Please try again.",
      );
    });
    // The chips are re-enabled so the visitor can try again.
    expect(
      document.getElementById(`${switcherId}-tenant_admin`),
    ).not.toBeDisabled();
  });
});
