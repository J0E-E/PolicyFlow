import { Link } from "react-router-dom";
import PageLayout from "../components/PageLayout.tsx";

// Landing route (`/`). Static editorial placeholder — copy is replaced in P1.6.
// Besley Display hero, Public Sans subtitle, an Oxford double rule beneath the
// title, and one Tonal button through to tenant selection (Guide §3, §4, §5).
export default function LandingPage() {
  return (
    <PageLayout pageId="landing">
      <div id="landing-content" className="landing-content">
        <h1 id="landing-hero-title" className="landing-hero-title">
          PolicyFlow
        </h1>
        <hr id="landing-oxford-rule" className="oxford-double-rule" />
        <p id="landing-subtitle" className="landing-subtitle">
          An event-driven insurance operations platform. Choose a demo tenant to
          begin exploring leads, policies, and the engineering behind them.
        </p>
        <Link
          id="landing-select-tenant-button"
          className="button-tonal"
          to="/select-tenant"
        >
          Select a tenant
        </Link>
      </div>
    </PageLayout>
  );
}
