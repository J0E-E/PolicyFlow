import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import Button from "../components/Button.tsx";
import Card from "../components/Card.tsx";
import CheckboxGroup from "../components/CheckboxGroup.tsx";
import HouseholdPicker from "./HouseholdPicker.tsx";
import { useCapability, useSession } from "../session";
import {
  ApiError,
  convertLead,
  getConversionPrefill,
  getLead,
  listTenants,
} from "../api";
import type { HouseholdChoice, MaskedLead, Tenant } from "../api";

// The dedicated review-and-confirm convert screen at `/app/leads/:id/convert`
// (P2.1 Epic 6). It replaces Epic 5's minimal inline confirm: the agent lands here
// from the lead detail "Convert lead" affordance, reviews the contact details that
// will be carried onto the new customer, confirms or chooses the product lines to
// open opportunities for, and commits. A successful convert navigates to the now
// frozen lead detail.
//
// It renders inside the AppShell chrome, so it carries its own Guide §5 page header.
// Two reads back the page (mirroring the lead detail / intake pages): the lead via
// `getLead(:id)`, and the tenant via `listTenants()` for the product-line labels.
// The page is only usable for a lead that is actually convertible — `Qualified`, held
// by the caller, editable, and not a read-only seed row — so an ineligible lead shows
// a short notice with a way back instead of the form (the same guard the detail-page
// affordance applies, re-checked here because the route is reachable by URL).
//
// Only the new-household path ships here (the link-an-existing-household choice is a
// later epic), so the household mode is fixed to "new" and shown as a default note.

type TenantLoadState =
  | { kind: "loading" }
  | { kind: "loaded"; tenant: Tenant }
  | { kind: "not-found" }
  | { kind: "error" };

type LeadLoadState =
  | { kind: "loading" }
  | { kind: "loaded"; lead: MaskedLead }
  | { kind: "not-found" }
  | { kind: "error" };

function ConvertHeader() {
  return (
    <header id="convert-lead-header" className="agent-intake-header">
      <h1 id="convert-lead-title" className="agent-intake-title">
        Convert lead
      </h1>
      <hr id="convert-lead-rule" className="oxford-double-rule" />
    </header>
  );
}

function ConvertShell({ children }: { children: React.ReactNode }) {
  return (
    <div id="convert-lead-page" className="agent-intake-page">
      <ConvertHeader />
      {children}
    </div>
  );
}

export default function ConvertLeadPage() {
  const { identity } = useSession();
  const canEdit = useCapability("create_edit_records");
  const { id: leadId } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const tenantSlug = identity?.user.tenant_slug ?? null;

  const [tenantLoad, setTenantLoad] = useState<TenantLoadState>({
    kind: "loading",
  });
  const [leadLoad, setLeadLoad] = useState<LeadLoadState>({ kind: "loading" });
  const [selectedProductLines, setSelectedProductLines] = useState<string[]>([]);
  const [householdMode, setHouseholdMode] = useState<"new" | "link">("new");
  const [linkedHouseholdId, setLinkedHouseholdId] = useState<string | null>(null);
  const [suggestedHousehold, setSuggestedHousehold] = useState<{
    id: string;
    name: string;
  } | null>(null);
  const [isConverting, setIsConverting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

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
          // Pre-select the lead's own product lines (the common case); the agent
          // can add or remove before committing.
          setSelectedProductLines(lead.product_lines_of_interest);
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

  // Duplicate pre-select (Epic 9): if this lead is flagged a duplicate of a converted
  // prior, the server resolves that prior's household; pre-select it in link mode (the
  // agent may still override). A null result or a failure leaves the new-household
  // default untouched.
  useEffect(() => {
    if (leadId === undefined) {
      return;
    }
    let isActive = true;
    getConversionPrefill(leadId)
      .then((prefill) => {
        if (isActive && prefill.preselected_household !== null) {
          setSuggestedHousehold(prefill.preselected_household);
          setHouseholdMode("link");
          setLinkedHouseholdId(prefill.preselected_household.id);
        }
      })
      .catch(() => {
        // Fall back to the new-household default — the suggestion is best-effort.
      });
    return () => {
      isActive = false;
    };
  }, [leadId]);

  const backToLead = `/app/leads/${leadId ?? ""}`;

  // Link mode needs a chosen household before it can commit; new mode never does.
  const isHouseholdChoiceIncomplete =
    householdMode === "link" && linkedHouseholdId === null;

  const commitConvert = () => {
    if (
      leadId === undefined ||
      selectedProductLines.length === 0 ||
      isHouseholdChoiceIncomplete
    ) {
      return;
    }
    const household: HouseholdChoice =
      householdMode === "link" && linkedHouseholdId !== null
        ? { mode: "link", household_id: linkedHouseholdId }
        : { mode: "new" };
    setErrorMessage(null);
    setIsConverting(true);
    convertLead(leadId, {
      household,
      product_lines: selectedProductLines,
    })
      .then(() => navigate(backToLead))
      .catch(() => {
        setErrorMessage("We couldn't convert this lead. Please try again.");
      })
      .finally(() => setIsConverting(false));
  };

  if (tenantLoad.kind === "loading" || leadLoad.kind === "loading") {
    return (
      <ConvertShell>
        <p
          id="convert-lead-loading"
          className="agent-intake-status"
          role="status"
          aria-live="polite"
        >
          Loading…
        </p>
      </ConvertShell>
    );
  }

  if (leadLoad.kind === "not-found") {
    return (
      <ConvertShell>
        <p id="convert-lead-not-found" className="agent-intake-status" role="status">
          We couldn't find that lead. It may have been removed, or it belongs to
          another agency.
        </p>
        <Link id="convert-lead-not-found-back" className="text-link" to="/app/leads">
          Back to leads
        </Link>
      </ConvertShell>
    );
  }

  if (tenantLoad.kind === "error" || leadLoad.kind === "error") {
    const onRetry = leadLoad.kind === "error" ? loadLead : loadTenant;
    return (
      <ConvertShell>
        <div id="convert-lead-error" className="agent-intake-error">
          <p
            id="convert-lead-error-message"
            className="agent-intake-status"
            role="status"
            aria-live="polite"
          >
            We couldn't load this lead. Please try again.
          </p>
          <Button id="convert-lead-error-retry-button" variant="tonal" onClick={onRetry}>
            Retry
          </Button>
        </div>
      </ConvertShell>
    );
  }

  if (tenantLoad.kind === "not-found") {
    return (
      <ConvertShell>
        <p id="convert-lead-tenant-not-found" className="agent-intake-status" role="status">
          We couldn't find your agency. Conversion isn't available here.
        </p>
      </ConvertShell>
    );
  }

  const { lead } = leadLoad;
  const { tenant } = tenantLoad;

  // Eligibility gate — the route is reachable by URL, so re-check the same conditions
  // the detail-page affordance uses: editable, Qualified, held by the caller, not a
  // read-only seed row. An ineligible lead shows a notice and a way back, never the form.
  const isHolder = identity?.user.id === lead.owner_user_id;
  const isEligible =
    canEdit && lead.status === "Qualified" && !lead.is_seed && isHolder;

  if (!isEligible) {
    return (
      <ConvertShell>
        <p id="convert-lead-ineligible" className="agent-intake-status" role="status">
          This lead can't be converted. Only a qualified lead you own can be
          converted.
        </p>
        <Link id="convert-lead-ineligible-back" className="text-link" to={backToLead}>
          Back to the lead
        </Link>
      </ConvertShell>
    );
  }

  const productLineOptions = tenant.product_lines.map((productLine) => ({
    value: productLine.key,
    label: productLine.label,
  }));
  const hasNoProductLine = selectedProductLines.length === 0;

  return (
    <ConvertShell>
      {errorMessage !== null && (
        <p id="convert-lead-commit-error" className="agent-intake-error" role="alert">
          {errorMessage}
        </p>
      )}

      <div id="convert-lead-body" className="convert-lead-body">
      <Card id="convert-lead-contact-card" title="Contact details">
        <p id="convert-lead-contact-intro" className="convert-lead-intro">
          These details will be carried onto the new contact. Email and phone stay
          masked here; the customer record keeps the encrypted values.
        </p>
        <dl id="convert-lead-contact-list" className="convert-lead-contact-list">
          <div className="convert-lead-contact-row">
            <dt id="convert-lead-contact-name-label">Name</dt>
            <dd id="convert-lead-contact-name">
              {lead.first_name} {lead.last_name}
            </dd>
          </div>
          <div className="convert-lead-contact-row">
            <dt id="convert-lead-contact-email-label">Email</dt>
            <dd id="convert-lead-contact-email">{lead.email}</dd>
          </div>
          <div className="convert-lead-contact-row">
            <dt id="convert-lead-contact-phone-label">Phone</dt>
            <dd id="convert-lead-contact-phone">{lead.phone}</dd>
          </div>
          <div className="convert-lead-contact-row">
            <dt id="convert-lead-contact-age-band-label">Age band</dt>
            <dd id="convert-lead-contact-age-band">{lead.age_band}</dd>
          </div>
          <div className="convert-lead-contact-row">
            <dt id="convert-lead-contact-zip-label">ZIP</dt>
            <dd id="convert-lead-contact-zip">{lead.zip_code}</dd>
          </div>
        </dl>
      </Card>

      <Card id="convert-lead-form-card" title="What to open">
        <HouseholdPicker
          mode={householdMode}
          selectedHouseholdId={linkedHouseholdId}
          suggestedHousehold={suggestedHousehold}
          onSelectNew={() => {
            setHouseholdMode("new");
            setLinkedHouseholdId(null);
          }}
          onSelectLinkMode={() => setHouseholdMode("link")}
          onSelectHousehold={(householdId) => {
            setHouseholdMode("link");
            setLinkedHouseholdId(householdId);
          }}
        />
        <CheckboxGroup
          id="convert-lead-product-lines"
          label="Open an opportunity for"
          options={productLineOptions}
          selectedValues={selectedProductLines}
          onChange={setSelectedProductLines}
          isRequired
          error={
            hasNoProductLine ? "Choose at least one product line." : undefined
          }
          helper="At least one. The lead's interests are pre-selected."
        />
        <div id="convert-lead-actions" className="convert-lead-actions">
          <Button
            id="convert-lead-commit-button"
            variant="filled"
            isPending={isConverting}
            disabled={hasNoProductLine || isHouseholdChoiceIncomplete}
            onClick={commitConvert}
          >
            Convert lead
          </Button>
          <Button
            id="convert-lead-cancel-button"
            variant="text"
            disabled={isConverting}
            onClick={() => navigate(backToLead)}
          >
            Cancel
          </Button>
        </div>
      </Card>
      </div>
    </ConvertShell>
  );
}
