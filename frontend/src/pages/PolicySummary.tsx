import StampTag from "../components/StampTag.tsx";
import type { StampStatus } from "../components/StampTag.tsx";
import MedicareReveal from "./MedicareReveal.tsx";
import type { Policy } from "../api";

interface PolicySummaryProperties {
  /** Required so every rendered element is uniquely targetable (CLAUDE.md). */
  id: string;
  /** The issued policy to summarize. */
  policy: Policy;
}

// Map the policy status to the Guide's signal hue: an active policy is success;
// a *Renewal Due* policy (real write for a session-owned policy, or the
// derive-at-read overlay for a baseline one — P2.4 Epic 6) reads as the attention
// hue so the renewal stands out. The status text itself always comes from
// `policy.status`, so the overlay's *Renewal Due* flows straight through.
function statusHue(status: string): StampStatus {
  return status === "Renewal Due" ? "warning" : "success";
}

// The issued-policy view (P2.3 Epic 8) on the opportunity detail page — the
// customer-visible end of the happy path: the human-readable policy number, the
// Active status, and the carrier / product / coverage / premium snapshot. A focused,
// read-only component (Frontend Philosophy); Epic 11 adds the masked Tenant-1
// Medicare ID. Tokens + design-system primitives only.
export default function PolicySummary({ id, policy }: PolicySummaryProperties) {
  return (
    <section id={id} className="policy-summary" aria-labelledby={`${id}-heading`}>
      <div id={`${id}-header`} className="policy-summary-header">
        <h2 id={`${id}-heading`} className="policy-summary-heading">
          Policy
        </h2>
        <StampTag id={`${id}-status`} status={statusHue(policy.status)}>
          {policy.status}
        </StampTag>
      </div>
      <p id={`${id}-number`} className="policy-summary-number">
        {policy.policy_number}
      </p>
      <p id={`${id}-carrier`} className="policy-summary-carrier">
        {`${policy.carrier} · ${policy.product_label}`}
      </p>
      <p id={`${id}-premium`} className="policy-summary-premium">
        {`$${policy.coverage_amount.toLocaleString()} coverage · $${policy.premium_annual.toLocaleString()}/yr`}
      </p>
      {policy.medicare_id_masked !== null && (
        <MedicareReveal
          id={`${id}-medicare`}
          applicationId={policy.application_id}
          masked={policy.medicare_id_masked}
        />
      )}
    </section>
  );
}
