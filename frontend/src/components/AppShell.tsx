import type { ReactNode } from "react";
import { useSession } from "../session";
import { useIdentityTheming } from "./useIdentityTheming.ts";
import Masthead from "./Masthead.tsx";

interface AppShellProperties {
  /** The routed content rendered into the shell's `<main>`. */
  children: ReactNode;
}

// The branded chrome wrapping every guarded `/app` surface (Guide §4 — "App shell
// is a fixed left nav + top masthead; content scrolls"). It runs the identity →
// data-attribute theming effect (so the whole document re-themes to the active
// tenant/persona) and renders the masthead above a `<main>` that holds the routed
// page. The left nav arrives in Epic 12; this epic stands up the masthead + main.
//
// The guard (RequireSession) only renders this on its signed-in branch, so
// `identity` is present here; a defensive null-guard renders just `<main>` so a
// stray null can never throw while the masthead awaits an identity.
export default function AppShell({ children }: AppShellProperties) {
  const { identity } = useSession();
  useIdentityTheming(identity);

  return (
    <div id="app-shell" className="app-shell">
      {identity && <Masthead identity={identity} />}
      <main id="app-shell-main" className="app-shell-main">
        {children}
      </main>
    </div>
  );
}
