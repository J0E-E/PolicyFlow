import { useCallback, useState } from "react";
import { InfoCircle } from "iconoir-react";
import Button from "./Button.tsx";
import { useSession } from "../session";

// The graceful-expiry notice (P1.8 Epic 12) — a calm info Banner (Guide §6.5 / §4)
// shown when a visitor deep-links to a lead that 404s while their demo session is
// no longer active (expired or gone). Instead of a bare "not found", it explains
// that the demo data resets on a cadence and offers one click to a fresh session
// that preserves their agency — never a raw 404/500 (Guide §6.5).
//
// It is SELF-CONTAINED in the WorkspaceResetControl / DemoSessionCountdown idiom:
// it reads its identity and the `assumePersona` action straight from `useSession`,
// so the caller (LeadDetailPage) renders it without wiring any new prop. The action
// re-assumes the visitor's CURRENT persona — which mints a fresh demo session AND
// re-seeds the queue in one existing call — then hard-reloads to `/app/leads`, so
// the masthead countdown re-fetches and the guided stepper re-initializes for free.
//
// It is informational only (Guide §6.8): neutral surface tones, a left info icon,
// never the --state-error hue. A failure to re-assume stays on the page with an
// inline aria-live error so the visitor can retry, rather than trapping them.

const FRESH_SESSION_DESTINATION = "/app/leads";

export default function DemoSessionGate() {
  const { identity, assumePersona } = useSession();
  const [isStarting, setIsStarting] = useState<boolean>(false);
  const [hasError, setHasError] = useState<boolean>(false);

  // The current persona to re-assume. Platform Admin is tenantless — its
  // tenant_slug is null and the backend ignores the slug for that role, so an
  // empty string re-assumes cleanly (the RoleSwitcher / WorkspaceResetControl idiom).
  const currentTenantSlug = identity?.user.tenant_slug ?? "";
  const currentRole = identity?.user.role ?? null;

  const handleStartFreshSession = useCallback(async () => {
    if (currentRole === null) {
      return;
    }
    setHasError(false);
    setIsStarting(true);
    try {
      await assumePersona(currentTenantSlug, currentRole);
      // Hard reload so the masthead countdown re-fetches the fresh session and the
      // in-memory guided stepper re-initializes to step 1 (the live-refresh gap the
      // pure-local countdown left open closes here).
      window.location.assign(FRESH_SESSION_DESTINATION);
    } catch {
      // Stay on the page so the visitor can retry — never trap them behind a
      // failed re-assume.
      setIsStarting(false);
      setHasError(true);
    }
  }, [assumePersona, currentRole, currentTenantSlug]);

  return (
    <section
      id="demo-session-gate"
      className="demo-session-gate"
      role="status"
      aria-live="polite"
    >
      <div id="demo-session-gate-banner" className="demo-session-gate-banner">
        <span
          id="demo-session-gate-icon"
          className="demo-session-gate-icon"
          aria-hidden="true"
        >
          <InfoCircle width={20} height={20} />
        </span>
        <div id="demo-session-gate-body" className="demo-session-gate-body">
          <p
            id="demo-session-gate-message"
            className="demo-session-gate-message"
          >
            Your demo session ended. Demo data resets every 24 hours to keep the
            sandbox clean — your agency is preserved.
          </p>
          <p
            id="demo-session-gate-error"
            className="demo-session-gate-error"
            role="status"
            aria-live="polite"
          >
            {hasError
              ? "We couldn't start a fresh session. Please try again."
              : ""}
          </p>
        </div>
        <Button
          id="demo-session-gate-start-button"
          variant="filled"
          onClick={handleStartFreshSession}
          isPending={isStarting}
        >
          Start a fresh session
        </Button>
      </div>
    </section>
  );
}
