// Tests for the intake prefill scenarios. The cross-epic contract: the duplicate
// scenario must submit the Jordan Rivera bait (mirroring app.seed.JORDAN_RIVERA_BAIT_*)
// so the matcher flags it, and the typical-lead identities are distinct from it.

import { describe, expect, it } from "vitest";

import { shopperIntakePrefills } from "./shopperIntakePrefills.ts";
import type { Tenant } from "../api";

const sunshine: Tenant = {
  slug: "sunshine-senior-benefits",
  display_name: "Sunshine Senior Benefits",
  brand_primary_color: "#9C4A1E",
  product_lines: [
    { key: "medicare_advantage", label: "Medicare Advantage" },
    { key: "final_expense", label: "Final Expense" },
  ],
};

const florida: Tenant = {
  slug: "florida-family-planning",
  display_name: "Florida Family Planning",
  brand_primary_color: "#0F6A72",
  product_lines: [{ key: "term_life", label: "Term Life" }],
};

describe("shopperIntakePrefills", () => {
  it("offers a typical lead and a duplicate scenario for a known tenant", () => {
    const ids = shopperIntakePrefills(sunshine).map((prefill) => prefill.id);
    expect(ids).toEqual(["typical-lead", "duplicate"]);
  });

  it("builds the duplicate scenario from the Jordan Rivera bait", () => {
    const duplicate = shopperIntakePrefills(sunshine).find(
      (prefill) => prefill.id === "duplicate",
    );
    const values = duplicate!.buildValues(sunshine);

    // The exact seeded bait email + phone — the matcher flags on these.
    expect(values.email).toBe("jordan.rivera@example.com");
    expect(values.phone).toBe("(407) 555-0188");
    // The duplicate uses the tenant's first registry key.
    expect(values.productLines).toEqual(["medicare_advantage"]);
  });

  it("picks each tenant's own typical-lead identity, distinct from the bait", () => {
    const sunshineTypical = shopperIntakePrefills(sunshine)
      .find((prefill) => prefill.id === "typical-lead")!
      .buildValues(sunshine);
    expect(sunshineTypical.email).toBe("margaret.chen@example.com");
    expect(sunshineTypical.email).not.toBe("jordan.rivera@example.com");

    const floridaTypical = shopperIntakePrefills(florida)
      .find((prefill) => prefill.id === "typical-lead")!
      .buildValues(florida);
    expect(floridaTypical.email).toBe("daniel.brooks@example.com");
    expect(floridaTypical.productLines).toEqual(["term_life"]);
  });
});
