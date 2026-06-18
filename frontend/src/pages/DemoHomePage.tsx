import { useSession } from "../session";
import { ROLE_LABELS } from "../components/roleLabels.ts";

// The walking-skeleton demo home behind the `/app` guard. It proves the whole
// access model end-to-end in the browser: a visitor who picked a tenant (which
// passwordlessly assumed Agent) lands here and sees exactly who they are signed
// in as. Real chrome now comes from the surrounding AppShell (masthead +
// theming); this page renders only its content into the shell's `<main>`, so it
// carries no header of its own (no double header).

export default function DemoHomePage() {
  const { identity } = useSession();

  // The route guard guarantees a signed-in identity before this renders, but the
  // session type is `Identity | null`; guard defensively so a stray null can
  // never throw.
  if (identity === null) {
    return (
      <div id="demo-home-content" className="demo-home-content">
        <p id="demo-home-empty" className="demo-home-empty">
          No active session.
        </p>
      </div>
    );
  }

  const roleLabel = ROLE_LABELS[identity.user.role];
  // The tenantless Platform Admin has no tenant name; everyone else shows their
  // tenant's display name (e.g. "Sunshine Senior Benefits").
  const tenantLabel =
    identity.user.tenant_name ?? "Platform — no tenant scope";

  return (
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
  );
}
