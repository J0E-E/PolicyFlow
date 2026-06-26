// Tests for the masked + click-to-reveal Medicare ID control (P2.3 Epic 11). jsdom
// has no backend, so `../api` is mocked: revealMedicareId returns the plaintext.

import { fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import MedicareReveal from "./MedicareReveal.tsx";

vi.mock("../api", () => ({
  revealMedicareId: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

import { revealMedicareId } from "../api";

const revealMedicareIdMock = vi.mocked(revealMedicareId);

beforeEach(() => {
  revealMedicareIdMock.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("MedicareReveal", () => {
  it("shows the masked value and a Reveal control", () => {
    render(<MedicareReveal id="m" applicationId="app-1" masked="•••-••-••••" />);
    expect(document.getElementById("m-value")!.textContent).toBe("•••-••-••••");
    expect(document.getElementById("m-reveal")).toBeInTheDocument();
  });

  it("reveals the plaintext on click and hides the Reveal control", async () => {
    revealMedicareIdMock.mockResolvedValue({ field: "medicare_id", value: "1EG4TE5MK73" });
    render(<MedicareReveal id="m" applicationId="app-1" masked="•••-••-••••" />);

    fireEvent.click(document.getElementById("m-reveal")!);

    await waitFor(() => {
      expect(document.getElementById("m-value")!.textContent).toBe("1EG4TE5MK73");
    });
    expect(document.getElementById("m-reveal")).not.toBeInTheDocument();
    expect(revealMedicareIdMock).toHaveBeenCalledWith("app-1");
  });
});
