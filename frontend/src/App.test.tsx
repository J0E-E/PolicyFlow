import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "./App.tsx";

// Smoke test proving the frontend harness wires React + Testing Library + jsdom
// end-to-end against the real shell. <App> is wrapped in MemoryRouter because it
// renders <Routes> and needs a router context. The assertion anchors on the
// shared shell wordmark from PageLayout via the header's accessible "banner"
// role — a stable element, unlike the landing <h1> (page content changing in
// P1.6). Scoping with `within(header)` also avoids the duplicate "PolicyFlow"
// (it appears in both the header wordmark and the hero heading).
describe("App shell smoke test", () => {
  it("renders the shared shell wordmark in the header", () => {
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    );

    const header = screen.getByRole("banner");
    expect(within(header).getByText("PolicyFlow")).toBeInTheDocument();
  });
});
