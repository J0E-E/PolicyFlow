// Tests for the convert affordance (P2.1 Epic 5). jsdom has no backend, so `../api`
// is mocked: `convertLead` drives the action. The component shows a "Convert lead"
// primary button that reveals an inline confirm (explainer + Confirm/Cancel); a
// confirmed conversion calls `convertLead` with the lead's product lines and lifts the
// frozen lead via `onLeadChange`. Covers: the confirm reveal, the happy convert, the
// product-line body, and the inline error on failure.

import { fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import LeadConvertSection from "./LeadConvertSection.tsx";
import type { MaskedLead } from "../api";

vi.mock("../api", () => ({
  convertLead: vi.fn(),
}));

import { convertLead } from "../api";

const convertLeadMock = vi.mocked(convertLead);

function makeQualifiedLead(overrides: Partial<MaskedLead> = {}): MaskedLead {
  return {
    id: "lead-1",
    first_name: "Maria",
    last_name: "Lopez",
    email: "m•••@example.com",
    phone: "•••-•••-0149",
    date_of_birth: "****-**-**",
    age_band: "65-74",
    zip_code: "33134",
    street_address: "***",
    product_lines_of_interest: ["medicare_advantage", "final_expense"],
    preferred_contact_method: "email",
    notes: null,
    rejection_reason: null,
    lead_source: "public_form",
    status: "Qualified",
    owner_user_id: "agent-1",
    owner_username: "agent.one@sunshine.example",
    duplicate_of_lead_id: null,
    duplicate_resolution: null,
    created_at: "2026-06-18T14:30:00Z",
    updated_at: "2026-06-18T14:30:00Z",
    is_seed: false,
    is_session_record: false,
    ...overrides,
  };
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("LeadConvertSection", () => {
  it("reveals the inline confirm only after Convert lead is clicked", () => {
    const { queryByText, getByText } = render(
      <LeadConvertSection lead={makeQualifiedLead()} onLeadChange={vi.fn()} />,
    );

    // The explainer is hidden until the agent opens the confirm.
    expect(queryByText(/Converting creates a household/)).toBeNull();

    fireEvent.click(getByText("Convert lead"));

    expect(getByText(/Converting creates a household/)).toBeTruthy();
    expect(getByText("Confirm conversion")).toBeTruthy();
  });

  it("converts with the lead's product lines and lifts the frozen lead", async () => {
    const frozenLead = makeQualifiedLead({
      status: "Converted",
    });
    convertLeadMock.mockResolvedValue(frozenLead);
    const onLeadChange = vi.fn();

    const { getByText } = render(
      <LeadConvertSection lead={makeQualifiedLead()} onLeadChange={onLeadChange} />,
    );

    fireEvent.click(getByText("Convert lead"));
    fireEvent.click(getByText("Confirm conversion"));

    await waitFor(() => expect(onLeadChange).toHaveBeenCalledWith(frozenLead));
    expect(convertLeadMock).toHaveBeenCalledWith("lead-1", {
      household: { mode: "new" },
      product_lines: ["medicare_advantage", "final_expense"],
    });
  });

  it("shows an inline error and does not lift the lead when the convert fails", async () => {
    convertLeadMock.mockRejectedValue(new Error("boom"));
    const onLeadChange = vi.fn();

    const { getByText, findByRole } = render(
      <LeadConvertSection lead={makeQualifiedLead()} onLeadChange={onLeadChange} />,
    );

    fireEvent.click(getByText("Convert lead"));
    fireEvent.click(getByText("Confirm conversion"));

    const alert = await findByRole("alert");
    expect(alert.textContent).toMatch(/couldn't convert/);
    expect(onLeadChange).not.toHaveBeenCalled();
  });
});
