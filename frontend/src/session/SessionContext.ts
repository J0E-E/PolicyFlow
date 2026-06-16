// The shared session context: the types and the React context object that the
// `SessionProvider` fills and every authed surface reads. This file holds no
// JSX, so Vite's fast-refresh boundary stays clean (the provider component lives
// in `SessionProvider.tsx`).

import { createContext, useContext } from "react";

import type { Capability, Identity, Role } from "../api";

/**
 * The three states a session can be in. There is no fourth "error" state: a
 * failed `/me` that is not a clean 401 (a 500, or no backend to reach in local
 * dev) is treated the same as a 401 — `signed-out` — so the session model stays
 * fail-closed (if we cannot confirm a session, the visitor is not signed in).
 */
export type SessionStatus = "loading" | "signed-in" | "signed-out";

/**
 * Everything the session context exposes to the surfaces below the provider:
 * the current `status`, the signed-in `identity` (or `null`), the flat list of
 * `capabilities` the active role holds, and the two actions that change who is
 * signed in.
 */
export interface SessionContextValue {
  /** Where the session is in its lifecycle (`loading` until the first `/me`). */
  status: SessionStatus;
  /** The signed-in user's identity, or `null` while loading or signed out. */
  identity: Identity | null;
  /** The active role's capabilities, or an empty list when there is no identity. */
  capabilities: Capability[];
  /**
   * Switch to a seeded demo persona. On success the context refreshes its
   * identity from the call's own response body (no second `/me`). A failure
   * rejects to the caller and leaves the session state unchanged.
   */
  assumePersona: (tenantSlug: string, role: Role) => Promise<void>;
  /** Sign out, clearing the identity and moving the session to `signed-out`. */
  signOut: () => Promise<void>;
}

/**
 * The session context. It starts as `null` so `useSession` can detect — and
 * throw a clear error for — a read from outside a `SessionProvider`.
 */
export const SessionContext = createContext<SessionContextValue | null>(null);

/**
 * Read the current session from the nearest `SessionProvider`. Throws a clear
 * error when called outside a provider, so a misplaced consumer fails loudly
 * instead of silently reading a `null` context.
 */
export function useSession(): SessionContextValue {
  const session = useContext(SessionContext);
  if (session === null) {
    throw new Error("useSession must be used inside a SessionProvider");
  }
  return session;
}
