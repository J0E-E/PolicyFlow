import StampTag from "../components/StampTag.tsx";
import type { Application } from "../api";

interface ApplicationSummaryProperties {
  /** Required so every rendered element is uniquely targetable (CLAUDE.md). */
  id: string;
  /** The application to summarize. */
  application: Application;
}

// The Draft Application summary (P2.3 Epic 5) on the opportunity detail page: the
// frozen carrier / product / coverage / premium snapshot copied from the selected
// quote, headed by the lifecycle status. A focused, read-only component (Frontend
// Philosophy); later epics (the product step, submit, the decision, the policy
// view) extend this surface. Tokens + design-system primitives only.
export default function ApplicationSummary({
  id,
  application,
}: ApplicationSummaryProperties) {
  return (
    <section id={id} className="application-summary" aria-labelledby={`${id}-heading`}>
      <div id={`${id}-header`} className="application-summary-header">
        <h2 id={`${id}-heading`} className="application-summary-heading">
          Application
        </h2>
        <StampTag id={`${id}-status`} status="neutral">
          {application.status}
        </StampTag>
      </div>
      <p id={`${id}-carrier`} className="application-summary-carrier">
        {`${application.carrier} · ${application.product_label}`}
      </p>
      <p id={`${id}-coverage`} className="application-summary-coverage">
        {`$${application.coverage_amount.toLocaleString()} coverage`}
      </p>
      <p id={`${id}-premium`} className="application-summary-premium">
        {`$${application.premium_monthly.toLocaleString()}/mo · $${application.premium_annual.toLocaleString()}/yr`}
      </p>
    </section>
  );
}
