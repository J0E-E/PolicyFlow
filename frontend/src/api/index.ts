// Barrel for the API module: later epics import the client and its shared types
// from `../api` rather than reaching into individual files.

export { ApiError } from "./client";
export {
  assumePersona,
  getCurrentIdentity,
  listTenants,
  signOut,
} from "./client";
export type {
  Capability,
  Identity,
  IdentityUser,
  Role,
  Tenant,
} from "./types";
