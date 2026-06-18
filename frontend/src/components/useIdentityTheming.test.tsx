// Tests for the identity -> data-attribute theming effect. The effect is the one
// place `data-tenant` / `data-persona` get set on `document.documentElement`,
// from which the Guide's declarative tenant/persona theming flows. A tiny harness
// component runs the hook; we assert the attributes on the document root and that
// they are cleaned up on unmount.

import { render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { Identity } from "../api";
import { useIdentityTheming } from "./useIdentityTheming.ts";

function ThemingHarness({ identity }: { identity: Identity | null }) {
  useIdentityTheming(identity);
  return null;
}

const root = document.documentElement;

function makeIdentity(
  role: Identity["user"]["role"],
  tenantSlug: string | null,
): Identity {
  return {
    user: {
      id: "11111111-1111-1111-1111-111111111111",
      username: "user.one@example",
      role,
      tenant_id: tenantSlug === null ? null : "22222222-2222-2222-2222-222222222222",
      tenant_slug: tenantSlug,
      tenant_name: tenantSlug === null ? null : "Sunshine Senior Benefits",
    },
    capabilities: [],
  };
}

afterEach(() => {
  // Belt-and-suspenders: ensure no test leaks theming onto the shared root.
  root.removeAttribute("data-tenant");
  root.removeAttribute("data-persona");
});

describe("useIdentityTheming", () => {
  it("sets data-tenant and data-persona on the document root from the identity", () => {
    render(
      <ThemingHarness identity={makeIdentity("agent", "sunshine-senior-benefits")} />,
    );

    expect(root.getAttribute("data-tenant")).toBe("sunshine-senior-benefits");
    expect(root.getAttribute("data-persona")).toBe("agent");
  });

  it("uses the real wire slug and snake_case role string", () => {
    render(
      <ThemingHarness
        identity={makeIdentity("tenant_admin", "florida-family-planning")}
      />,
    );

    expect(root.getAttribute("data-tenant")).toBe("florida-family-planning");
    expect(root.getAttribute("data-persona")).toBe("tenant_admin");
  });

  it("omits data-tenant for the tenantless Platform Admin and sets only the persona", () => {
    render(<ThemingHarness identity={makeIdentity("platform_admin", null)} />);

    expect(root.hasAttribute("data-tenant")).toBe(false);
    expect(root.getAttribute("data-persona")).toBe("platform_admin");
  });

  it("removes both attributes on unmount", () => {
    const view = render(
      <ThemingHarness identity={makeIdentity("agent", "sunshine-senior-benefits")} />,
    );
    expect(root.getAttribute("data-tenant")).toBe("sunshine-senior-benefits");

    view.unmount();

    expect(root.hasAttribute("data-tenant")).toBe(false);
    expect(root.hasAttribute("data-persona")).toBe(false);
  });

  it("clears theming when identity becomes null", () => {
    const view = render(
      <ThemingHarness identity={makeIdentity("agent", "sunshine-senior-benefits")} />,
    );
    expect(root.getAttribute("data-tenant")).toBe("sunshine-senior-benefits");

    view.rerender(<ThemingHarness identity={null} />);

    expect(root.hasAttribute("data-tenant")).toBe(false);
    expect(root.hasAttribute("data-persona")).toBe(false);
  });
});
