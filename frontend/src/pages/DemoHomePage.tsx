import PageLayout from "../components/PageLayout.tsx";
import { useSession } from "../session";
import type { Role } from "../api";

// The walking-skeleton demo home behind the `/app` guard. It proves the whole
// access model end-to-end in the browser: a visitor who picked a tenant (which
// passwordlessly assumed Agent) lands here and sees exactly who they are signed
// in as. Un-branded on purpose — real chrome and content arrive in later epics.

// Human-readable label for each role, so the status line reads in plain words
// ("Agent", "Tenant Admin") rather than the wire value ("agent", "tenant_admin").
const ROLE_LABELS: Record<Role, string> = {
  agent: "Agent",
  tenant_admin: "Tenant Admin",
  read_only: "Read-Only",
  platform_admin: "Platform Admin",
};

export default function DemoHomePage() {
  const { identity } = useSession();

  // The route guard guarantees a signed-in identity before this renders, but the
  // session type is `Identity | null`; guard defensively so a stray null can
  // never throw.
  if (identity === null) {
    return (
      <PageLayout pageId="demo-home">
        <div id="demo-home-content" className="demo-home-content">
          <p id="demo-home-empty" className="demo-home-empty">
            No active session.
          </p>
        </div>
      </PageLayout>
    );
  }

  const roleLabel = ROLE_LABELS[identity.user.role];
  // The tenantless Platform Admin has no tenant name; everyone else shows their
  // tenant's display name (e.g. "Sunshine Senior Benefits").
  const tenantLabel =
    identity.user.tenant_name ?? "Platform — no tenant scope";

  return (
    <PageLayout pageId="demo-home">
      <div id="demo-home-content" className="demo-home-content">
        <h1 id="demo-home-title" className="demo-home-title">
          Demo home
        </h1>
        <p id="demo-home-status" className="demo-home-status">
          Signed in as{" "}
          <span id="demo-home-role" className="demo-home-role">
            {roleLabel}
          </span>{" "}
          ·{" "}
          <span id="demo-home-tenant" className="demo-home-tenant">
            {tenantLabel}
          </span>
        </p>
      </div>
    </PageLayout>
  );
}
