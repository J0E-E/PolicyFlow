// The single lead-status → Stamp mapping (Epic 20). A pure function — no JSX, no
// React — so it is unit-testable on its own and stays a clean Vite fast-refresh
// boundary, mirroring navSections.ts. Both the leads list (Epic 20) and the
// created-lead panel (Epic 19, folded onto this) render the lead's status as a
// `StampTag`, and this is the one place the status → (hue, label) decision lives.
//
// The hue choices follow Guide §2.2 ("the only hues that signal"): a brand-new
// lead is neutral (information, not a signal), a Working lead is pending (an open
// thread someone owns), a Qualified lead is success, a Rejected lead is error.

import type { LeadStatus } from "../api";
import type { StampStatus } from "./StampTag.tsx";

/** The Stamp presentation for one lead status: which hue it carries and the
 *  human label shown inside the stamp (natural case — the Stamp CSS uppercases). */
export interface LeadStatusStamp {
  /** The StampTag `status` hue (Guide §2.2). */
  status: StampStatus;
  /** The label rendered inside the stamp. */
  label: string;
}

// The fixed status → stamp table. A plain record keyed by the LeadStatus union,
// so adding a backend status is a compile error here until it is mapped.
const LEAD_STATUS_STAMPS: Record<LeadStatus, LeadStatusStamp> = {
  New: { status: "neutral", label: "New" },
  Working: { status: "pending", label: "Working" },
  Qualified: { status: "success", label: "Qualified" },
  Rejected: { status: "error", label: "Rejected" },
};

/**
 * Map a lead's lifecycle status to its Stamp presentation (hue + label). Pure and
 * total over the `LeadStatus` union. `New → neutral`, `Working → pending`,
 * `Qualified → success`, `Rejected → error`.
 */
export function leadStatusStamp(status: LeadStatus): LeadStatusStamp {
  return LEAD_STATUS_STAMPS[status];
}
