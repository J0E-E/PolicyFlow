// Tests for the public Shopper intake form. jsdom has no backend, so `../api` is
// mocked: submitPublicIntake is driven per test, and ApiError is a real class so
// the form's `instanceof ApiError` 429 branch works. Uses fireEvent (no
// user-event dependency). Covers: render from the tenant, prefill, the happy
// submit + success panel, the validation-failure path (summary focused, no
// send), the honeypot field, and the 429 form-level error keeping the data.

import { fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ShopperIntakeForm from "./ShopperIntakeForm.tsx";
import type { Tenant } from "../api";

// The factory is hoisted above the file, so the mocked ApiError is defined
// inside it; the tests import that same class back from the mocked module so
// `new ApiError(...)` is recognised by the form's `instanceof ApiError` branch.
vi.mock("../api", () => ({
  submitPublicIntake: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.name = "ApiError";
      this.status = status;
    }
  },
}));

import { ApiError, submitPublicIntake } from "../api";

const submitPublicIntakeMock = vi.mocked(submitPublicIntake);

const tenant: Tenant = {
  slug: "sunshine-senior-benefits",
  display_name: "Sunshine Senior Benefits",
  brand_primary_color: "#9C4A1E",
  product_lines: [
    { key: "medicare_advantage", label: "Medicare Advantage" },
    { key: "final_expense", label: "Final Expense" },
  ],
};

// Fill the form with a valid identity by writing each control directly.
function fillValidForm() {
  fireEvent.change(document.getElementById("shopper-intake-first-name")!, {
    target: { value: "Margaret" },
  });
  fireEvent.change(document.getElementById("shopper-intake-last-name")!, {
    target: { value: "Chen" },
  });
  fireEvent.change(document.getElementById("shopper-intake-date-of-birth")!, {
    target: { value: "1956-03-12" },
  });
  fireEvent.change(document.getElementById("shopper-intake-email")!, {
    target: { value: "margaret.chen@example.com" },
  });
  fireEvent.change(document.getElementById("shopper-intake-phone")!, {
    target: { value: "(305) 555-0149" },
  });
  fireEvent.change(document.getElementById("shopper-intake-zip-code")!, {
    target: { value: "33134" },
  });
  fireEvent.click(
    document.getElementById("shopper-intake-product-lines-option-medicare_advantage")!,
  );
}

beforeEach(() => {
  submitPublicIntakeMock.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("ShopperIntakeForm rendering", () => {
  it("renders the three numbered sections and a product-line per tenant line", () => {
    render(<ShopperIntakeForm tenant={tenant} />);

    expect(document.getElementById("shopper-intake-section-about")).toBeInTheDocument();
    expect(document.getElementById("shopper-intake-section-contact")).toBeInTheDocument();
    expect(
      document.getElementById("shopper-intake-section-coverage"),
    ).toBeInTheDocument();
    // The checkbox group is built from tenant.product_lines.
    expect(
      document.getElementById(
        "shopper-intake-product-lines-option-medicare_advantage",
      ),
    ).toBeInTheDocument();
    expect(
      document.getElementById("shopper-intake-product-lines-option-final_expense"),
    ).toBeInTheDocument();
  });

  it("renders an off-screen honeypot website field (not display:none)", () => {
    render(<ShopperIntakeForm tenant={tenant} />);

    const honeypot = document.getElementById(
      "shopper-intake-website",
    ) as HTMLInputElement;
    expect(honeypot).toHaveAttribute("name", "website");
    expect(honeypot).toHaveAttribute("tabindex", "-1");
    // The wrapper is aria-hidden — a human never reaches it.
    expect(
      document.getElementById("shopper-intake-honeypot-wrapper"),
    ).toHaveAttribute("aria-hidden", "true");
  });
});

describe("ShopperIntakeForm prefill", () => {
  it("fills the form from the duplicate scenario (the Jordan Rivera bait)", () => {
    render(<ShopperIntakeForm tenant={tenant} />);

    fireEvent.click(
      document.getElementById("shopper-intake-prefill-duplicate-button")!,
    );

    expect(
      (document.getElementById("shopper-intake-email") as HTMLInputElement).value,
    ).toBe("jordan.rivera@example.com");
    expect(
      (document.getElementById("shopper-intake-phone") as HTMLInputElement).value,
    ).toBe("(407) 555-0188");
  });
});

describe("ShopperIntakeForm submission", () => {
  it("submits the sanitized body and shows the success panel", async () => {
    submitPublicIntakeMock.mockResolvedValue({ ok: true });
    render(<ShopperIntakeForm tenant={tenant} />);

    fillValidForm();
    fireEvent.click(document.getElementById("shopper-intake-submit")!);

    await waitFor(() => {
      expect(
        document.getElementById("shopper-intake-success"),
      ).toBeInTheDocument();
    });

    // The body carried the tenant slug, the honeypot field, and the trimmed data.
    expect(submitPublicIntakeMock).toHaveBeenCalledOnce();
    const body = submitPublicIntakeMock.mock.calls[0][0];
    expect(body.tenant_slug).toBe("sunshine-senior-benefits");
    expect(body.website).toBe("");
    expect(body.email).toBe("margaret.chen@example.com");
    expect(body.product_lines_of_interest).toEqual(["medicare_advantage"]);
    // The form itself is gone — replaced by the confirmation.
    expect(document.getElementById("shopper-intake-form")).not.toBeInTheDocument();
    expect(document.getElementById("shopper-intake-success-body")).toHaveTextContent(
      "Sunshine Senior Benefits",
    );
  });

  it("blocks submit on validation errors and focuses the summary, never sending", async () => {
    render(<ShopperIntakeForm tenant={tenant} />);

    // Submit the empty form.
    fireEvent.submit(document.getElementById("shopper-intake-form")!);

    await waitFor(() => {
      expect(
        document.getElementById("shopper-intake-error-summary"),
      ).toBeInTheDocument();
    });
    // The summary carries role="alert" and is focusable so submit can move focus.
    const summary = document.getElementById("shopper-intake-error-summary")!;
    expect(summary).toHaveAttribute("role", "alert");
    expect(summary).toHaveAttribute("tabindex", "-1");
    // Each required field is listed.
    expect(
      document.getElementById("shopper-intake-error-summary-link-email"),
    ).toBeInTheDocument();
    // Nothing was sent.
    expect(submitPublicIntakeMock).not.toHaveBeenCalled();
  });

  it("shows a form-level error on a 429 and keeps the entered data", async () => {
    submitPublicIntakeMock.mockRejectedValue(new ApiError(429, "rate limited"));
    render(<ShopperIntakeForm tenant={tenant} />);

    fillValidForm();
    fireEvent.click(document.getElementById("shopper-intake-submit")!);

    await waitFor(() => {
      expect(
        document.getElementById("shopper-intake-submit-error"),
      ).toBeInTheDocument();
    });
    expect(
      document.getElementById("shopper-intake-submit-error"),
    ).toHaveTextContent("Too many requests");
    // The form is still on screen with the data intact.
    expect(
      (document.getElementById("shopper-intake-email") as HTMLInputElement).value,
    ).toBe("margaret.chen@example.com");
  });

  it("shows a generic form-level error on a network failure", async () => {
    submitPublicIntakeMock.mockRejectedValue(new ApiError(0, "network request failed"));
    render(<ShopperIntakeForm tenant={tenant} />);

    fillValidForm();
    fireEvent.click(document.getElementById("shopper-intake-submit")!);

    await waitFor(() => {
      expect(
        document.getElementById("shopper-intake-submit-error"),
      ).toHaveTextContent("We couldn't send your request");
    });
  });
});
