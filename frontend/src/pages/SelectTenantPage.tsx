import { Link } from "react-router-dom";
import PageLayout from "../components/PageLayout.tsx";

// Tenant-selection route (`/select-tenant`). Static placeholder — no real
// tenant data or selection logic (that lands in P1.6). Headline + two flat
// bordered Cards naming the two seeded demo tenants, plus a Text back link
// to the landing page (Guide §3, §5).
export default function SelectTenantPage() {
  return (
    <PageLayout pageId="select-tenant">
      <div id="select-tenant-content" className="select-tenant-content">
        <h1 id="select-tenant-headline" className="select-tenant-headline">
          Select a tenant
        </h1>
        <p id="select-tenant-intro" className="select-tenant-intro">
          Two demo organizations are seeded for this walkthrough. Selection is
          not wired up yet — these are placeholders.
        </p>
        <ul id="select-tenant-card-list" className="tenant-card-list">
          <li
            id="select-tenant-card-item-sunshine"
            className="tenant-card-item"
          >
            <div id="select-tenant-card-sunshine" className="tenant-card">
              <h2
                id="select-tenant-card-sunshine-name"
                className="tenant-card-name"
              >
                Sunshine Senior Benefits
              </h2>
              <p
                id="select-tenant-card-sunshine-note"
                className="tenant-card-note"
              >
                Medicare and senior coverage. Placeholder — not yet selectable.
              </p>
            </div>
          </li>
          <li id="select-tenant-card-item-florida" className="tenant-card-item">
            <div id="select-tenant-card-florida" className="tenant-card">
              <h2
                id="select-tenant-card-florida-name"
                className="tenant-card-name"
              >
                Florida Family Planning
              </h2>
              <p
                id="select-tenant-card-florida-note"
                className="tenant-card-note"
              >
                Family and household coverage. Placeholder — not yet selectable.
              </p>
            </div>
          </li>
        </ul>
        <Link id="select-tenant-back-link" className="text-link" to="/">
          Back to landing
        </Link>
      </div>
    </PageLayout>
  );
}
