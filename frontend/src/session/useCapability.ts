// A one-line permission check over the server-returned capability matrix. A
// surface calls `useCapability("reveal_pii")` to ask "may the signed-in role do
// this?" without reaching into the identity itself.

import type { Capability } from "../api";
import { useSession } from "./SessionContext";

/**
 * Whether the signed-in role holds the given capability. Reads the flat
 * capability list the backend returned for the active identity, so the answer
 * always tracks the server's RBAC matrix. Returns `false` while loading or when
 * signed out (the capability list is empty), keeping the helper fail-closed.
 */
export function useCapability(capability: Capability): boolean {
  const { capabilities } = useSession();
  return capabilities.includes(capability);
}
