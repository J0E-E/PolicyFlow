import { createContext, useContext } from "react";
import type { GuidedDocketState } from "./useGuidedDocket.ts";

// A tiny context that shares ONE guided-docket state between the two places that act
// on it: the floating panel mounted shell-wide in AppShell, and the demo-home "Open
// the guided walkthrough" opener nested under it. AppShell holds the single
// useGuidedDocket() and provides it here, so the opener can open/focus the very same
// docket the panel renders — no duplicated or divergent progress state.
//
// No JSX lives in this module (just the context object + the reader hook), keeping it a
// clean Vite fast-refresh boundary; the provider component lives in AppShell.

export const GuidedDocketContext = createContext<GuidedDocketState | null>(null);

/**
 * Read the shared guided-docket state. Throws a clear error if used outside the
 * provider (AppShell), so a misplacement fails loudly rather than silently no-op-ing.
 */
export function useGuidedDocketContext(): GuidedDocketState {
  const state = useContext(GuidedDocketContext);
  if (state === null) {
    throw new Error(
      "useGuidedDocketContext must be used within the GuidedDocketContext provider (AppShell).",
    );
  }
  return state;
}
