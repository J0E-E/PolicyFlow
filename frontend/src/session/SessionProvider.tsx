// The session provider: the single component in this module. It restores the
// signed-in identity via `/me` once on mount, holds the session state, and
// exposes the `assumePersona` / `signOut` actions to every surface below it.
// It renders its children through a context provider and adds no DOM node of its
// own, so the project's "id on every element" rule does not apply here.

import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";

import {
  assumePersona as assumePersonaRequest,
  getCurrentIdentity,
  signOut as signOutRequest,
} from "../api";
import type { Identity, Role } from "../api";
import { SessionContext } from "./SessionContext";
import type { SessionStatus } from "./SessionContext";

interface SessionProviderProps {
  children: ReactNode;
}

/**
 * Provides the shared session state to its children. On mount it asks the
 * backend "who am I?" once; until that answer arrives the status is `loading`.
 * A successful `/me` moves to `signed-in` with the identity; **any** failure
 * (a clean 401, a 500, or no backend to reach in local dev) fail-closes to
 * `signed-out` with no identity.
 */
export function SessionProvider({ children }: SessionProviderProps) {
  const [status, setStatus] = useState<SessionStatus>("loading");
  const [identity, setIdentity] = useState<Identity | null>(null);

  useEffect(() => {
    // Ignore a late `/me` resolution after the provider unmounts (and ignore the
    // first of React StrictMode's double-invoked effects in development).
    let isActive = true;

    getCurrentIdentity()
      .then((restoredIdentity) => {
        if (!isActive) {
          return;
        }
        setIdentity(restoredIdentity);
        setStatus("signed-in");
      })
      .catch(() => {
        // Fail closed: any failure to confirm a session means signed out.
        if (!isActive) {
          return;
        }
        setIdentity(null);
        setStatus("signed-out");
      });

    return () => {
      isActive = false;
    };
  }, []);

  const assumePersona = useCallback(
    async (tenantSlug: string, role: Role): Promise<void> => {
      // Refresh identity from the call's own response body — it is the same
      // `Identity` shape `/me` returns, so there is no second round trip. A
      // failure propagates to the caller and leaves the session state unchanged.
      const assumedIdentity = await assumePersonaRequest(tenantSlug, role);
      setIdentity(assumedIdentity);
      setStatus("signed-in");
    },
    [],
  );

  const signOut = useCallback(async (): Promise<void> => {
    await signOutRequest();
    setIdentity(null);
    setStatus("signed-out");
  }, []);

  const capabilities = identity ? identity.capabilities : [];

  return (
    <SessionContext.Provider
      value={{ status, identity, capabilities, assumePersona, signOut }}
    >
      {children}
    </SessionContext.Provider>
  );
}
