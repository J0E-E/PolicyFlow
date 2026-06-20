import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { NavArrowRight } from "iconoir-react";
import Button from "../components/Button.tsx";
import Card from "../components/Card.tsx";
import StampTag from "../components/StampTag.tsx";
import { leadStatusStamp } from "../components/leadStatusStamp.ts";
import { useCapability, useSession } from "../session";
import { ApiError, getLead, listTenants } from "../api";
import type { MaskedLead, ProductLine, Tenant } from "../api";
import {
  leadOwnerLabel,
  leadProductLineLabels,
} from "./leadsListPresentation.ts";
import { leadDate, leadPreferredContactLabel } from "./leadDetailPresentation.ts";
import RevealableLeadField from "./RevealableLeadField.tsx";
import LeadActionsSection from "./LeadActionsSection.tsx";
import LeadDuplicatePanel from "./LeadDuplicatePanel.tsx";

// The authenticated lead detail page at `/app/leads/:id` (Epic 21). It renders
// INSIDE the AppShell chrome (masthead + left nav), so it carries its OWN Guide §5
// page header — a breadcrumb back to the list, a Besley headline of the lead's
// full name, the status stamp, and the lead id in mono over the Oxford double rule.
//
// Two reads back the page, each its own LoadState (mirroring LeadsListPage):
//   - The tenant list (filtered to the session slug) supplies the product-line
//     registry so the coverage labels resolve to human names.
//   - The lead itself via `getLead(:id)` — a 404 (missing / cross-tenant) is a
//     distinct not-found state, any other failure offers a Retry.
//
// Phase 1 is the view skeleton: the masked PII renders statically (the §6.4
// click-to-reveal affordance, the qualify/reject actions, and the duplicate panel
// land in later phases). Below the header sit single-column stacked Cards: a
// Contact card (the revealable PII + ZIP) and a Lead-details card (coverage /
// source / owner / preferred-contact / notes / dates, plus rejection_reason).

/** What the tenant resolution is doing (for the product-line labels). Mirrors
 *  LeadsListPage so loading / error / not-found / loaded each render once. */
type TenantLoadState =
  | { kind: "loading" }
  | { kind: "loaded"; tenant: Tenant }
  | { kind: "not-found" }
  | { kind: "error" };

/** What the lead fetch is doing. A 404 is its own state (the lead is missing or
 *  belongs to another tenant); any other failure is a retryable error. */
type LeadLoadState =
  | { kind: "loading" }
  | { kind: "loaded"; lead: MaskedLead }
  | { kind: "not-found" }
  | { kind: "error" };

export default function LeadDetailPage() {
  const { identity } = useSession();
  const canReveal = useCapability("reveal_pii");
  const canEdit = useCapability("create_edit_records");
  const { id: leadId } = useParams<{ id: string }>();
  const tenantSlug = identity?.user.tenant_slug ?? null;

  const [tenantLoad, setTenantLoad] = useState<TenantLoadState>({
    kind: "loading",
  });
  const [leadLoad, setLeadLoad] = useState<LeadLoadState>({ kind: "loading" });

  // Resolve the tenant once, for the product-line registry (the coverage labels).
  const loadTenant = useCallback(() => {
    setTenantLoad({ kind: "loading" });
    let isActive = true;
    listTenants()
      .then((tenants) => {
        if (!isActive) {
          return;
        }
        const tenant = tenants.find((candidate) => candidate.slug === tenantSlug);
        setTenantLoad(
          tenant === undefined
            ? { kind: "not-found" }
            : { kind: "loaded", tenant },
        );
      })
      .catch(() => {
        if (isActive) {
          setTenantLoad({ kind: "error" });
        }
      });
    return () => {
      isActive = false;
    };
  }, [tenantSlug]);

  useEffect(() => loadTenant(), [loadTenant]);

  // Fetch the lead. A 404 resolves to not-found (missing / cross-tenant); any
  // other failure is a retryable error.
  const loadLead = useCallback(() => {
    if (leadId === undefined) {
      setLeadLoad({ kind: "not-found" });
      return;
    }
    setLeadLoad({ kind: "loading" });
    let isActive = true;
    getLead(leadId)
      .then((lead) => {
        if (isActive) {
          setLeadLoad({ kind: "loaded", lead });
        }
      })
      .catch((error: unknown) => {
        if (!isActive) {
          return;
        }
        setLeadLoad(
          error instanceof ApiError && error.status === 404
            ? { kind: "not-found" }
            : { kind: "error" },
        );
      });
    return () => {
      isActive = false;
    };
  }, [leadId]);

  useEffect(() => loadLead(), [loadLead]);

  // Replace the loaded lead in place after an action returns the updated masked
  // lead (qualify / reject / resolve-duplicate). The header stamp, the actions
  // section, and the duplicate panel all re-derive from the new status — no refetch.
  const setLead = (updated: MaskedLead) => {
    setLeadLoad({ kind: "loaded", lead: updated });
  };

  // ---- Block the page until both reads land (labels need the tenant) ----

  if (tenantLoad.kind === "loading" || leadLoad.kind === "loading") {
    return (
      <div id="lead-detail-page" className="lead-detail-page">
        <p
          id="lead-detail-loading"
          className="lead-detail-status"
          role="status"
          aria-live="polite"
        >
          Loading…
        </p>
      </div>
    );
  }

  if (leadLoad.kind === "not-found") {
    return (
      <div id="lead-detail-page" className="lead-detail-page">
        <p id="lead-detail-not-found" className="lead-detail-status" role="status">
          We couldn't find that lead. It may have been removed, or it belongs to
          another agency.
        </p>
        <Link id="lead-detail-not-found-back" className="text-link" to="/app/leads">
          Back to leads
        </Link>
      </div>
    );
  }

  if (tenantLoad.kind === "error" || leadLoad.kind === "error") {
    const onRetry =
      leadLoad.kind === "error" ? loadLead : loadTenant;
    return (
      <div id="lead-detail-page" className="lead-detail-page">
        <div id="lead-detail-error" className="lead-detail-error">
          <p
            id="lead-detail-error-message"
            className="lead-detail-status"
            role="status"
            aria-live="polite"
          >
            We couldn't load this lead. Please try again.
          </p>
          <Button
            id="lead-detail-error-retry-button"
            variant="tonal"
            onClick={onRetry}
          >
            Retry
          </Button>
        </div>
      </div>
    );
  }

  if (tenantLoad.kind === "not-found") {
    return (
      <div id="lead-detail-page" className="lead-detail-page">
        <p id="lead-detail-tenant-not-found" className="lead-detail-status" role="status">
          We couldn't find your agency. Leads aren't available here.
        </p>
      </div>
    );
  }

  // ---- Loaded: header + stacked Contact / Lead-details cards ----

  const { lead } = leadLoad;
  const { tenant } = tenantLoad;

  return (
    <div id="lead-detail-page" className="lead-detail-page">
      <LeadDetailHeader lead={lead} />
      {/* The duplicate panel sits above the cards while the lead points at a
          matched prior lead. A `new` resolution clears the pointer, so it
          vanishes; `link` / `reject` keep it as a light resolved note. */}
      {lead.duplicate_of_lead_id !== null && (
        <LeadDuplicatePanel
          lead={lead}
          canEdit={canEdit}
          onLeadChange={setLead}
        />
      )}
      <div id="lead-detail-cards" className="lead-detail-cards">
        <ContactCard lead={lead} canReveal={canReveal} />
        <LeadDetailsCard lead={lead} productLines={tenant.product_lines} />
      </div>
      {/* Qualify / reject sit below the cards, but only for a Working lead a
          permitted user can transition (Guide §6 — status-gated actions). */}
      {canEdit && lead.status === "Working" && (
        <LeadActionsSection lead={lead} onLeadChange={setLead} />
      )}
    </div>
  );
}

// ---- Guide §5 page header: breadcrumb, Besley name, status stamp, mono id ----

function LeadDetailHeader({ lead }: { lead: MaskedLead }) {
  const statusStamp = leadStatusStamp(lead.status);
  const fullName = `${lead.first_name} ${lead.last_name}`;

  return (
    <header id="lead-detail-header" className="lead-detail-header">
      <nav
        id="lead-detail-breadcrumb"
        className="lead-detail-breadcrumb"
        aria-label="Breadcrumb"
      >
        <Link
          id="lead-detail-breadcrumb-leads"
          className="lead-detail-breadcrumb-link"
          to="/app/leads"
        >
          Leads
        </Link>
        <span
          id="lead-detail-breadcrumb-separator"
          className="lead-detail-breadcrumb-separator"
          aria-hidden="true"
        >
          <NavArrowRight width={14} height={14} />
        </span>
        <span
          id="lead-detail-breadcrumb-current"
          className="lead-detail-breadcrumb-current"
          aria-current="page"
        >
          {fullName}
        </span>
      </nav>
      <div id="lead-detail-header-row" className="lead-detail-header-row">
        <h1 id="lead-detail-title" className="lead-detail-title">
          {fullName}
        </h1>
        <StampTag id="lead-detail-status-stamp" status={statusStamp.status}>
          {statusStamp.label}
        </StampTag>
      </div>
      <p id="lead-detail-id" className="lead-detail-id">
        {lead.id}
      </p>
      <hr id="lead-detail-rule" className="oxford-double-rule" />
    </header>
  );
}

// ---- Contact card: the four revealable PII fields + ZIP (Guide §6.4) ----

function ContactCard({
  lead,
  canReveal,
}: {
  lead: MaskedLead;
  canReveal: boolean;
}) {
  return (
    <Card id="lead-detail-contact-card" title="Contact">
      <dl id="lead-detail-contact-list" className="lead-detail-list">
        <RevealableLeadField
          id="lead-detail-email"
          label="Email"
          leadId={lead.id}
          field="email"
          maskedValue={lead.email}
          canReveal={canReveal}
        />
        <RevealableLeadField
          id="lead-detail-phone"
          label="Phone"
          leadId={lead.id}
          field="phone"
          maskedValue={lead.phone}
          canReveal={canReveal}
        />
        <RevealableLeadField
          id="lead-detail-date-of-birth"
          label="Date of birth"
          leadId={lead.id}
          field="date_of_birth"
          maskedValue={lead.date_of_birth}
          canReveal={canReveal}
        />
        {/* Street address: revealable when on file; an absent one (null) shows a
            plain "Not provided" with no lock and no reveal control (Guide §6.4). */}
        {lead.street_address === null ? (
          <DetailRow id="lead-detail-street-address" label="Street address">
            <span
              id="lead-detail-street-address-absent"
              className="lead-detail-absent"
            >
              Not provided
            </span>
          </DetailRow>
        ) : (
          <RevealableLeadField
            id="lead-detail-street-address"
            label="Street address"
            leadId={lead.id}
            field="street_address"
            maskedValue={lead.street_address}
            canReveal={canReveal}
          />
        )}
        <DetailRow id="lead-detail-zip-code" label="ZIP code">
          {lead.zip_code}
        </DetailRow>
      </dl>
    </Card>
  );
}

// ---- Lead-details card: coverage / source / owner / preferences / notes / dates ----

function LeadDetailsCard({
  lead,
  productLines,
}: {
  lead: MaskedLead;
  productLines: ProductLine[];
}) {
  const preferredContact = leadPreferredContactLabel(
    lead.preferred_contact_method,
  );

  return (
    <Card id="lead-detail-details-card" title="Lead details">
      <dl id="lead-detail-details-list" className="lead-detail-list">
        <DetailRow id="lead-detail-coverage" label="Coverage interests">
          {leadProductLineLabels(lead, productLines)}
        </DetailRow>
        <DetailRow id="lead-detail-source" label="Source">
          {lead.lead_source === "public_form" ? "Public" : "Agent"}
        </DetailRow>
        <DetailRow id="lead-detail-owner" label="Owner">
          {leadOwnerLabel(lead.owner_username)}
        </DetailRow>
        <DetailRow id="lead-detail-preferred-contact" label="Preferred contact">
          {preferredContact ?? "No preference"}
        </DetailRow>
        <DetailRow id="lead-detail-age-band" label="Age band">
          {lead.age_band}
        </DetailRow>
        <DetailRow id="lead-detail-notes" label="Notes">
          {lead.notes ?? "—"}
        </DetailRow>
        {lead.rejection_reason !== null && (
          <DetailRow id="lead-detail-rejection-reason" label="Rejection reason">
            {lead.rejection_reason}
          </DetailRow>
        )}
        <DetailRow id="lead-detail-created" label="Created">
          {leadDate(lead.created_at)}
        </DetailRow>
        <DetailRow id="lead-detail-updated" label="Last updated">
          {leadDate(lead.updated_at)}
        </DetailRow>
      </dl>
    </Card>
  );
}

// ---- A labeled detail row (a dt/dd pair inside a definition list) ----

function DetailRow({
  id,
  label,
  children,
}: {
  id: string;
  label: string;
  children: ReactNode;
}) {
  return (
    <div id={`${id}-row`} className="lead-detail-row">
      <dt id={`${id}-label`} className="lead-detail-label">
        {label}
      </dt>
      <dd id={`${id}-content`} className="lead-detail-value">
        {children}
      </dd>
    </div>
  );
}
