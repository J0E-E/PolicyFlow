// The agent intake form's two prefill scenarios (Guide §6.9 prefill row). Mirrors
// the SHAPE of shopperIntakePrefills.ts — a {id, label, outcome, buildValues}[]
// builder — but carries AGENT-correct outcome copy: the agent route is
// authenticated, so a typical lead is born Working and assigned to the entering
// agent (not a queue lead), while a duplicate still flags a possible match.
//
// CROSS-EPIC CONTRACT: the identities are NOT redefined here — they are the
// EXACT same data the Shopper prefills use, reused from shopperIntakePrefills.ts
// so the Jordan Rivera duplicate bait still matches a seeded lead and the
// "typical" identities stay distinct from every seed. Only the copy differs.

import type { ShopperIntakeFormValues } from "./shopperIntakeValidation.ts";
import {
  buildDuplicateValues,
  TYPICAL_LEADS,
} from "./shopperIntakePrefills.ts";
import type { Tenant } from "../api";

/** A prefill scenario the agent can apply with one button. */
export interface AgentIntakePrefill {
  /** Stable id fragment for the button (`agent-intake-prefill-${id}`). */
  id: string;
  /** The button's visible label. */
  label: string;
  /** The one-line expected-outcome sublabel under the button (Guide §6.9). */
  outcome: string;
  /** Build the form values for this tenant — the duplicate scenario needs the
   *  tenant's first product-line key, so the values depend on the tenant. */
  buildValues: (tenant: Tenant) => ShopperIntakeFormValues;
}

/**
 * The agent prefill scenarios for a tenant. Reuses the Shopper identities
 * verbatim (the typical identity per slug, the shared Jordan Rivera duplicate
 * bait) but pairs each with agent-correct outcome copy. The "typical" scenario
 * appears only when a clean identity is on file for the slug; the duplicate
 * scenario is universal (its identity is tenant-independent bar the product line).
 */
export function agentIntakePrefills(tenant: Tenant): AgentIntakePrefill[] {
  const prefills: AgentIntakePrefill[] = [];

  const typicalLead = TYPICAL_LEADS[tenant.slug];
  if (typicalLead) {
    prefills.push({
      id: "typical-lead",
      label: "Use a typical lead",
      outcome: "Creates a Working lead assigned to you.",
      buildValues: () => typicalLead,
    });
  }

  prefills.push({
    id: "duplicate",
    label: "Try a duplicate scenario",
    outcome: "Matches an existing lead — flags a possible duplicate.",
    buildValues: buildDuplicateValues,
  });

  return prefills;
}
