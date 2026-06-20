// Tests for the authenticated agent intake form. jsdom has no backend, so
// `../api` is mocked: createLead is driven per test, and ApiError is a real class
// so a rejected create is recognised. The form's created-lead panel renders a
// react-router <Link>, so the form is wrapped in a MemoryRouter. Uses fireEvent
// (no user-event dependency). Covers: render from the tenant, prefill, the happy
// submit → AgentLeadCreatedPanel showing the created masked lead, the
// validation-failure path (summary focused, no send), and a submit error that
// keeps the entered data.

import { fireEvent, render, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AgentIntakeForm from "./AgentIntakeForm.tsx";
import type { MaskedLead, Tenant } from "../api";

vi.mock("../api", () => ({
  createLead: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.name = "ApiError";
      this.status = status;
    }
  },
}));

import { ApiError, createLead } from "../api";

const createLeadMock = vi.mocked(createLead);

const tenant: Tenant = {
  slug: "sunshine-senior-benefits",
  display_name: "Sunshine Senior Benefits",
  brand_primary_color: "#9C4A1E",
  product_lines: [
    { key: "medicare_advantage", label: "Medicare Advantage" },
    { key: "final_expense", label: "Final Expense" },
  ],
};

// The masked lead the agent endpoint returns on a successful create. The
// email/phone arrive pre-masked; age_band carries the usable value.
const createdLead: MaskedLead = {
  id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
  first_name: "Margaret",
  last_name: "Chen",
  email: "m•••••@example.com",
  phone: "(•••) •••-0149",
  date_of_birth: "****-**-**",
  age_band: "65-74",
  zip_code: "33134",
  street_address: "***",
  product_lines_of_interest: ["medicare_advantage"],
  preferred_contact_method: "email",
  notes: null,
  rejection_reason: null,
  lead_source: "agent_entered",
  status: "Working",
  owner_user_id: "11111111-1111-1111-1111-111111111111",
  owner_username: "agent.one@sunshine.example",
  duplicate_of_lead_id: null,
  duplicate_resolution: null,
  created_at: "2026-06-20T12:00:00Z",
  updated_at: "2026-06-20T12:00:00Z",
};

function renderForm() {
  return render(
    <MemoryRouter>
      <AgentIntakeForm tenant={tenant} />
    </MemoryRouter>,
  );
}

// Fill the form with a valid identity by writing each control directly.
function fillValidForm() {
  fireEvent.change(document.getElementById("agent-intake-first-name")!, {
    target: { value: "Margaret" },
  });
  fireEvent.change(document.getElementById("agent-intake-last-name")!, {
    target: { value: "Chen" },
  });
  fireEvent.change(document.getElementById("agent-intake-date-of-birth")!, {
    target: { value: "1956-03-12" },
  });
  fireEvent.change(document.getElementById("agent-intake-email")!, {
    target: { value: "margaret.chen@example.com" },
  });
  fireEvent.change(document.getElementById("agent-intake-phone")!, {
    target: { value: "(305) 555-0149" },
  });
  fireEvent.change(document.getElementById("agent-intake-zip-code")!, {
    target: { value: "33134" },
  });
  fireEvent.click(
    document.getElementById("agent-intake-product-lines-option-medicare_advantage")!,
  );
}

beforeEach(() => {
  createLeadMock.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("AgentIntakeForm rendering", () => {
  it("renders the three numbered sections and a checkbox per tenant product line", () => {
    renderForm();

    expect(document.getElementById("agent-intake-section-about")).toBeInTheDocument();
    expect(document.getElementById("agent-intake-section-contact")).toBeInTheDocument();
    expect(
      document.getElementById("agent-intake-section-coverage"),
    ).toBeInTheDocument();
    expect(
      document.getElementById(
        "agent-intake-product-lines-option-medicare_advantage",
      ),
    ).toBeInTheDocument();
    expect(
      document.getElementById("agent-intake-product-lines-option-final_expense"),
    ).toBeInTheDocument();
  });

  it("renders no honeypot field (authenticated route)", () => {
    renderForm();

    // The Shopper form's hidden honeypot must not exist on the agent route.
    expect(document.getElementById("agent-intake-website")).toBeNull();
    expect(document.getElementById("shopper-intake-website")).toBeNull();
  });
});

describe("AgentIntakeForm prefill", () => {
  it("fills the form from the duplicate scenario (the Jordan Rivera bait)", () => {
    renderForm();

    fireEvent.click(
      document.getElementById("agent-intake-prefill-duplicate-button")!,
    );

    expect(
      (document.getElementById("agent-intake-email") as HTMLInputElement).value,
    ).toBe("jordan.rivera@example.com");
    expect(
      (document.getElementById("agent-intake-phone") as HTMLInputElement).value,
    ).toBe("(407) 555-0188");
  });

  it("shows agent-correct outcome copy on the typical-lead prefill", () => {
    renderForm();

    expect(
      document.getElementById("agent-intake-prefill-typical-lead-outcome"),
    ).toHaveTextContent("Creates a Working lead assigned to you.");
  });
});

describe("AgentIntakeForm submission", () => {
  it("creates the lead and shows the created-lead panel with the masked lead", async () => {
    createLeadMock.mockResolvedValue(createdLead);
    renderForm();

    fillValidForm();
    fireEvent.click(document.getElementById("agent-intake-submit")!);

    await waitFor(() => {
      expect(
        document.getElementById("agent-intake-created"),
      ).toBeInTheDocument();
    });

    // The create body carried the trimmed agent data.
    expect(createLeadMock).toHaveBeenCalledOnce();
    const body = createLeadMock.mock.calls[0][0];
    expect(body.first_name).toBe("Margaret");
    expect(body.email).toBe("margaret.chen@example.com");
    expect(body.product_lines_of_interest).toEqual(["medicare_advantage"]);

    // The form itself is gone — replaced by the confirmation.
    expect(document.getElementById("agent-intake-form")).not.toBeInTheDocument();
    // The panel shows the created masked lead, a Working stamp, "owned by you",
    // and the product-line LABEL (not the key).
    expect(
      document.getElementById("agent-intake-created-name"),
    ).toHaveTextContent("Margaret Chen");
    expect(
      document.getElementById("agent-intake-created-email-value"),
    ).toHaveTextContent("m•••••@example.com");
    expect(
      document.getElementById("agent-intake-created-age-band-value"),
    ).toHaveTextContent("65-74");
    expect(
      document.getElementById("agent-intake-created-status-label"),
    ).toHaveTextContent("Working");
    expect(
      document.getElementById("agent-intake-created-ownership"),
    ).toHaveTextContent("Owned by you");
    expect(
      document.getElementById("agent-intake-created-product-lines-value"),
    ).toHaveTextContent("Medicare Advantage");
    // The back-to-demo-home link points at /app.
    expect(
      document.getElementById("agent-intake-created-home-link"),
    ).toHaveAttribute("href", "/app");
  });

  it("returns to a blank form from 'Create another lead'", async () => {
    createLeadMock.mockResolvedValue(createdLead);
    renderForm();

    fillValidForm();
    fireEvent.click(document.getElementById("agent-intake-submit")!);

    await waitFor(() => {
      expect(
        document.getElementById("agent-intake-created"),
      ).toBeInTheDocument();
    });

    fireEvent.click(
      document.getElementById("agent-intake-created-create-another")!,
    );

    // The form is back and blank.
    await waitFor(() => {
      expect(document.getElementById("agent-intake-form")).toBeInTheDocument();
    });
    expect(
      (document.getElementById("agent-intake-email") as HTMLInputElement).value,
    ).toBe("");
  });

  it("blocks submit on validation errors and focuses the summary, never sending", async () => {
    renderForm();

    fireEvent.submit(document.getElementById("agent-intake-form")!);

    await waitFor(() => {
      expect(
        document.getElementById("shopper-intake-error-summary"),
      ).toBeInTheDocument();
    });
    // The shared summary carries role="alert" and is focusable.
    const summary = document.getElementById("shopper-intake-error-summary")!;
    expect(summary).toHaveAttribute("role", "alert");
    expect(summary).toHaveAttribute("tabindex", "-1");
    // Each required field is listed, linking to the agent input id.
    const emailLink = document.getElementById(
      "shopper-intake-error-summary-link-email",
    )!;
    expect(emailLink).toHaveAttribute("href", "#agent-intake-email");
    // Nothing was sent.
    expect(createLeadMock).not.toHaveBeenCalled();
  });

  it("shows a form-level error on a failed create and keeps the entered data", async () => {
    createLeadMock.mockRejectedValue(new ApiError(422, "validation error"));
    renderForm();

    fillValidForm();
    fireEvent.click(document.getElementById("agent-intake-submit")!);

    await waitFor(() => {
      expect(
        document.getElementById("agent-intake-submit-error"),
      ).toHaveTextContent("We couldn't create the lead");
    });
    // The form is still on screen with the data intact.
    expect(document.getElementById("agent-intake-created")).toBeNull();
    expect(
      (document.getElementById("agent-intake-email") as HTMLInputElement).value,
    ).toBe("margaret.chen@example.com");
  });
});
