// The intake form's two prefill scenarios (Guide §6.9 prefill row, slimmed to the
// two backed scenarios — see the Epic 18 plan note). Each fills the form with a
// ready identity so a demo visitor can submit one click and watch the pipeline
// react, without typing a whole form.
//
// CROSS-EPIC CONTRACT — do not change lightly:
//  - "Typical lead" identities are chosen distinct from every seeded lead, so the
//    submission stays a clean, non-duplicate lead. Keep them out of any future seed.
//  - "Try a duplicate scenario" submits the Jordan Rivera bait — the SAME email +
//    phone seeded into both tenants (core/app/seed.py JORDAN_RIVERA_BAIT_*), so the
//    matcher flags it as a duplicate. Mirror those values exactly.
// Both pick the product line per tenant (the typical lead a chosen key; the
// duplicate the tenant's FIRST registry key, matching the seed's bait line).

import type { ShopperIntakeFormValues } from "./shopperIntakeValidation.ts";
import type { Tenant } from "../api";

/** A prefill scenario the visitor can apply with one button. */
export interface ShopperIntakePrefill {
  /** Stable id fragment for the button (`shopper-intake-prefill-${id}`). */
  id: string;
  /** The button's visible label. */
  label: string;
  /** The one-line expected-outcome sublabel under the button (Guide §6.9). */
  outcome: string;
  /** Build the form values for this tenant — the duplicate scenario needs the
   *  tenant's first product-line key, so the values are a function of the tenant. */
  buildValues: (tenant: Tenant) => ShopperIntakeFormValues;
}

// The Jordan Rivera duplicate bait — mirrors core/app/seed.py JORDAN_RIVERA_BAIT_*
// so the submitted email + phone match a seeded lead and the matcher flags it.
// Exported so the agent intake form's prefill row (Epic 19's agentIntakePrefills)
// reuses the SAME identity rather than duplicating the bait constants.
export const JORDAN_RIVERA_BAIT_EMAIL = "jordan.rivera@example.com";
export const JORDAN_RIVERA_BAIT_PHONE = "(407) 555-0188";

// The clean "Typical lead" identity per tenant. Emails/phones are distinct from
// every seeded lead, so the submission stays a non-duplicate. Exported so Epic
// 19's agent prefills reuse the same identities (agent copy, same data).
export const TYPICAL_LEADS: Record<string, ShopperIntakeFormValues> = {
  "sunshine-senior-benefits": {
    firstName: "Margaret",
    lastName: "Chen",
    email: "margaret.chen@example.com",
    phone: "(305) 555-0149",
    dateOfBirth: "1956-03-12",
    zipCode: "33134",
    streetAddress: "88 Coral Way",
    preferredContactMethod: "email",
    notes: "",
    productLines: ["medicare_advantage"],
  },
  "florida-family-planning": {
    firstName: "Daniel",
    lastName: "Brooks",
    email: "daniel.brooks@example.com",
    phone: "(813) 555-0151",
    dateOfBirth: "1988-07-22",
    zipCode: "33606",
    streetAddress: "410 Bayshore Blvd",
    preferredContactMethod: "phone",
    notes: "",
    productLines: ["term_life"],
  },
};

// The duplicate-scenario identity shared by both tenants — only the product line
// differs (the tenant's first registry key, matching the bait's seeded line).
// Exported so Epic 19's agent prefills build the same duplicate identity.
export function buildDuplicateValues(tenant: Tenant): ShopperIntakeFormValues {
  const firstProductLineKey = tenant.product_lines[0]?.key;
  return {
    firstName: "Jordan",
    lastName: "Rivera",
    email: JORDAN_RIVERA_BAIT_EMAIL,
    phone: JORDAN_RIVERA_BAIT_PHONE,
    dateOfBirth: "1958-06-15",
    zipCode: "32801",
    streetAddress: "742 Marina Bay Drive",
    preferredContactMethod: "email",
    notes: "",
    productLines: firstProductLineKey ? [firstProductLineKey] : [],
  };
}

/**
 * The prefill scenarios for a tenant. Returns only the scenarios whose data
 * exists for this tenant — the "Typical lead" appears only when a clean identity
 * is on file for the slug; the duplicate scenario is universal (its identity is
 * tenant-independent bar the product line).
 */
export function shopperIntakePrefills(tenant: Tenant): ShopperIntakePrefill[] {
  const prefills: ShopperIntakePrefill[] = [];

  const typicalLead = TYPICAL_LEADS[tenant.slug];
  if (typicalLead) {
    prefills.push({
      id: "typical-lead",
      label: "Use a typical lead",
      outcome: "Creates a clean new lead in the queue.",
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
