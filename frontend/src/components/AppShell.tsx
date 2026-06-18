import type { ReactNode } from "react";
import { useSession } from "../session";
import { useIdentityTheming } from "./useIdentityTheming.ts";
import Masthead from "./Masthead.tsx";
import LeftNav from "./LeftNav.tsx";
import Footer from "./Footer.tsx";

interface AppShellProperties {
  /** The routed content rendered into the shell's `<main>`. */
  children: ReactNode;
}

// The branded chrome wrapping every guarded `/app` surface (Guide §4 — "App shell
// is a fixed left nav + top masthead; content scrolls"). It runs the identity →
// data-attribute theming effect (so the whole document re-themes to the active
// tenant/persona) and lays out: the sticky masthead full-width on top, with a
// fixed-width left-nav rail beside the scrolling `<main>` below it.
//
// The guard (RequireSession) only renders this on its signed-in branch, so
// `identity` is present here; a defensive null-guard renders just `<main>` so a
// stray null can never throw while the chrome awaits an identity (the rail also
// reads the identity, so it lives inside the same guard).
export default function AppShell({ children }: AppShellProperties) {
  const { identity, capabilities, assumePersona } = useSession();
  useIdentityTheming(identity);

  return (
    <div id="app-shell" className="app-shell">
      {identity && (
        <Masthead identity={identity} assumePersona={assumePersona} />
      )}
      <div id="app-shell-body" className="app-shell-body">
        {identity && (
          <LeftNav role={identity.user.role} capabilities={capabilities} />
        )}
        <main id="app-shell-main" className="app-shell-main">
          {children}
        </main>
      </div>
      <Footer />
    </div>
  );
}
