// Tests for the issued-policy summary (P2.3 Epic 8 / P2.4 Epic 6). The status stamp
// is overlay-aware: an Active policy stamps success, a *Renewal Due* policy (the real
// write for a session-owned policy, or the derive-at-read overlay for a baseline one)
// stamps the attention (warning) hue — and the badge text always comes straight from
// `policy.status`. A focused component test, api-free (PolicySummary is pure props).

import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import PolicySummary from "./PolicySummary.tsx";
import type { Policy } from "../api";

function makePolicy(overrides: Partial<Policy> = {}): Policy {
  return {
    id: "policy-1",
    opportunity_id: "opp-1",
    application_id: "app-1",
    policy_number: "POL-SUN-2026-0A1B2C",
    status: "Active",
    carrier: "Humana",
    product_label: "Gold Plus HMO",
    coverage_amount: 7500,
    premium_monthly: 29,
    premium_annual: 348,
    issued_at: "2026-03-01T00:00:00+00:00",
    medicare_id_masked: null,
    ...overrides,
  };
}

describe("PolicySummary", () => {
  it("renders a Renewal Due policy with the attention badge carrying that text", () => {
    render(
      <PolicySummary
        id="policy-summary"
        policy={makePolicy({ status: "Renewal Due" })}
      />,
    );

    const stamp = document.getElementById("policy-summary-status")!;
    expect(stamp).toHaveTextContent("Renewal Due");
    // The attention (warning) hue, not the plain success of an active policy.
    expect(stamp).toHaveClass("stamp-tag-warning");
    expect(stamp).not.toHaveClass("stamp-tag-success");
  });

  it("renders an Active policy with the success badge", () => {
    render(<PolicySummary id="policy-summary" policy={makePolicy()} />);

    const stamp = document.getElementById("policy-summary-status")!;
    expect(stamp).toHaveTextContent("Active");
    expect(stamp).toHaveClass("stamp-tag-success");
  });
});
