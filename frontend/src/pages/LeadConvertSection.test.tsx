// Tests for the convert affordance (P2.1 Epic 5, routed in Epic 6). The section is a
// single "Convert lead" button that navigates to `/app/leads/:id/convert`. Rendered
// inside a MemoryRouter with a small location probe so the navigation target can be
// asserted without a real backend.

import { fireEvent, render } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";

import LeadConvertSection from "./LeadConvertSection.tsx";
import type { MaskedLead } from "../api";

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
    product_lines_of_interest: ["medicare_advantage"],
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

function LocationProbe() {
  const location = useLocation();
  return <span data-testid="location">{location.pathname}</span>;
}

describe("LeadConvertSection", () => {
  it("navigates to the convert route when Convert lead is clicked", () => {
    const { getByText, getByTestId } = render(
      <MemoryRouter initialEntries={["/app/leads/lead-1"]}>
        <LeadConvertSection lead={makeQualifiedLead()} />
        <LocationProbe />
      </MemoryRouter>,
    );

    expect(getByTestId("location").textContent).toBe("/app/leads/lead-1");

    fireEvent.click(getByText("Convert lead"));

    expect(getByTestId("location").textContent).toBe(
      "/app/leads/lead-1/convert",
    );
  });
});
