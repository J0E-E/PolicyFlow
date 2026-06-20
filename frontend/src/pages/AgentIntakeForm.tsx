import { useRef, useState } from "react";
import TextField from "../components/TextField.tsx";
import SelectField from "../components/SelectField.tsx";
import CheckboxGroup from "../components/CheckboxGroup.tsx";
import Button from "../components/Button.tsx";
import IntakeErrorSummary from "./IntakeErrorSummary.tsx";
import AgentLeadCreatedPanel from "./AgentLeadCreatedPanel.tsx";
import { agentIntakePrefills } from "./agentIntakePrefills.ts";
import {
  emptyShopperIntakeValues,
  SHOPPER_INTAKE_MAX_LENGTHS,
  validateShopperIntakeField,
  validateShopperIntakeForm,
  VALIDATED_SHOPPER_INTAKE_FIELDS,
} from "./shopperIntakeValidation.ts";
import type {
  ShopperIntakeFieldErrors,
  ShopperIntakeFormValues,
} from "./shopperIntakeValidation.ts";
import { createLead } from "../api";
import type { MaskedLead, Tenant } from "../api";

interface AgentIntakeFormProperties {
  /** The agent's tenant (slug, display_name, product_lines), resolved by the
   *  page from the session. The product lines drive the coverage-interests
   *  checkbox group and the prefills. */
  tenant: Tenant;
}

// The three preferred-contact options the backend honors, labeled for display —
// the same set the Shopper form uses (schemas.py _ALLOWED_CONTACT_METHODS).
const CONTACT_METHOD_OPTIONS = [
  { value: "email", label: "Email" },
  { value: "phone", label: "Phone call" },
  { value: "text", label: "Text message" },
];

// The input id each form field maps to — so the top error summary can link
// straight to the offending control (its href is `#${id}`).
const INPUT_ID_FOR_FIELD: Record<keyof ShopperIntakeFormValues, string> = {
  firstName: "agent-intake-first-name",
  lastName: "agent-intake-last-name",
  email: "agent-intake-email",
  phone: "agent-intake-phone",
  dateOfBirth: "agent-intake-date-of-birth",
  zipCode: "agent-intake-zip-code",
  streetAddress: "agent-intake-street-address",
  preferredContactMethod: "agent-intake-preferred-contact-method",
  notes: "agent-intake-notes",
  productLines: "agent-intake-product-lines",
};

// The authenticated agent intake form (Guide §5 fields, §6.9 prefill row). It
// mirrors the public Shopper form's layout — the same three ACORD-numbered
// sections, the same 10-field set + required/optional split, the same shared
// validation — but follows the AGENT path: it submits to the authenticated
// `createLead` endpoint (no honeypot, no rate-limit handling), and on success
// replaces itself with the inline AgentLeadCreatedPanel showing the created
// masked lead. The reusable field set carries the per-field anatomy; this
// component arranges them and owns the validate-on-blur / on-submit lifecycle.
export default function AgentIntakeForm({ tenant }: AgentIntakeFormProperties) {
  const [values, setValues] = useState<ShopperIntakeFormValues>(
    emptyShopperIntakeValues,
  );
  const [fieldErrors, setFieldErrors] = useState<ShopperIntakeFieldErrors>({});
  // A form-level (validation-rejected / network) failure message — keeps the
  // entered data so the agent can fix and retry without re-typing.
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  // The created masked lead on a successful submit; non-null swaps the form for
  // the confirmation panel.
  const [createdLead, setCreatedLead] = useState<MaskedLead | null>(null);

  // The error summary takes focus on a failed submit (Guide §5/§7).
  const errorSummaryRef = useRef<HTMLDivElement>(null);

  const prefills = agentIntakePrefills(tenant);
  const productLineOptions = tenant.product_lines.map((productLine) => ({
    value: productLine.key,
    label: productLine.label,
  }));

  // Update one text/select/checkbox field's value.
  const setFieldValue = (
    field: keyof ShopperIntakeFormValues,
    value: string | string[],
  ) => {
    setValues((previous) => ({ ...previous, [field]: value }));
  };

  // Validate one field on blur, mirroring the backend rule. Always recomputes
  // from the latest values so the message clears once the field is fixed.
  const validateFieldOnBlur = (field: keyof ShopperIntakeFormValues) => {
    setFieldErrors((previous) => ({
      ...previous,
      [field]: validateShopperIntakeField(field, values),
    }));
  };

  // Apply a prefill scenario — fill the form, clear any errors, and reset the
  // form-level error so the new clean data starts fresh.
  const applyPrefill = (
    buildValues: (tenant: Tenant) => ShopperIntakeFormValues,
  ) => {
    setValues(buildValues(tenant));
    setFieldErrors({});
    setSubmitError(null);
  };

  const handleSubmit = async (formEvent: React.FormEvent<HTMLFormElement>) => {
    formEvent.preventDefault();
    setSubmitError(null);

    // Validate every rule-bearing field; on any error, show the inline errors +
    // the top summary and move focus to the summary (do not send).
    const nextErrors = validateShopperIntakeForm(values);
    setFieldErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) {
      // Focus after paint so the summary element exists.
      window.requestAnimationFrame(() => errorSummaryRef.current?.focus());
      return;
    }

    setIsSubmitting(true);
    try {
      // The agent endpoint returns the created MASKED lead — drive the
      // confirmation panel off it (the email/phone arrive pre-masked).
      const lead = await createLead({
        first_name: values.firstName.trim(),
        last_name: values.lastName.trim(),
        email: values.email.trim(),
        phone: values.phone.trim(),
        date_of_birth: values.dateOfBirth,
        zip_code: values.zipCode.trim(),
        product_lines_of_interest: values.productLines,
        street_address: values.streetAddress.trim() || null,
        preferred_contact_method: values.preferredContactMethod || null,
        notes: values.notes.trim() || null,
      });
      setCreatedLead(lead);
    } catch {
      // A 403 / 422 / network drop (all surface as an ApiError) — a single
      // generic form-level message that keeps the entered data so the agent can
      // correct it and retry. The agent route isn't rate-limited, so there is no
      // 429-specific copy; the message is the same whatever the cause.
      setSubmitError(
        "We couldn't create the lead. Check your connection and try again.",
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  // Reset back to a fresh blank intake (from the created-lead panel).
  const handleCreateAnother = () => {
    setValues(emptyShopperIntakeValues);
    setFieldErrors({});
    setSubmitError(null);
    setCreatedLead(null);
  };

  if (createdLead !== null) {
    return (
      <AgentLeadCreatedPanel
        lead={createdLead}
        productLines={tenant.product_lines}
        onCreateAnother={handleCreateAnother}
      />
    );
  }

  const hasErrors = Object.values(fieldErrors).some(
    (message) => message !== undefined,
  );

  return (
    <form
      id="agent-intake-form"
      className="agent-intake-form"
      onSubmit={handleSubmit}
      noValidate
    >
      {/* Prefill row — the two backed demo scenarios with agent copy (Guide §6.9). */}
      <div id="agent-intake-prefill-row" className="agent-intake-prefill-row">
        <p
          id="agent-intake-prefill-heading"
          className="agent-intake-prefill-heading"
        >
          In a hurry? Start from a sample.
        </p>
        <div
          id="agent-intake-prefill-buttons"
          className="agent-intake-prefill-buttons"
        >
          {prefills.map((prefill) => (
            <div
              id={`agent-intake-prefill-${prefill.id}`}
              key={prefill.id}
              className="agent-intake-prefill"
            >
              <Button
                id={`agent-intake-prefill-${prefill.id}-button`}
                variant="tonal"
                onClick={() => applyPrefill(prefill.buildValues)}
              >
                {prefill.label}
              </Button>
              <span
                id={`agent-intake-prefill-${prefill.id}-outcome`}
                className="agent-intake-prefill-outcome"
              >
                {prefill.outcome}
              </span>
            </div>
          ))}
        </div>
      </div>

      {hasErrors && (
        <IntakeErrorSummary
          ref={errorSummaryRef}
          errors={fieldErrors}
          fieldOrder={VALIDATED_SHOPPER_INTAKE_FIELDS}
          inputIdForField={INPUT_ID_FOR_FIELD}
        />
      )}

      {/* 01 — About you */}
      <fieldset id="agent-intake-section-about" className="agent-intake-section">
        <legend
          id="agent-intake-section-about-legend"
          className="agent-intake-section-legend"
        >
          <span className="agent-intake-section-number" aria-hidden="true">
            01
          </span>
          About you
        </legend>
        <div className="agent-intake-section-fields">
          <TextField
            id={INPUT_ID_FOR_FIELD.firstName}
            label="First name"
            value={values.firstName}
            onChange={(value) => setFieldValue("firstName", value)}
            onBlur={() => validateFieldOnBlur("firstName")}
            error={fieldErrors.firstName}
            isRequired
            maxLength={SHOPPER_INTAKE_MAX_LENGTHS.firstName}
            autoComplete="given-name"
          />
          <TextField
            id={INPUT_ID_FOR_FIELD.lastName}
            label="Last name"
            value={values.lastName}
            onChange={(value) => setFieldValue("lastName", value)}
            onBlur={() => validateFieldOnBlur("lastName")}
            error={fieldErrors.lastName}
            isRequired
            maxLength={SHOPPER_INTAKE_MAX_LENGTHS.lastName}
            autoComplete="family-name"
          />
          <TextField
            id={INPUT_ID_FOR_FIELD.dateOfBirth}
            label="Date of birth"
            type="date"
            value={values.dateOfBirth}
            onChange={(value) => setFieldValue("dateOfBirth", value)}
            onBlur={() => validateFieldOnBlur("dateOfBirth")}
            error={fieldErrors.dateOfBirth}
            isRequired
            autoComplete="bday"
          />
        </div>
      </fieldset>

      {/* 02 — How we'll reach you */}
      <fieldset id="agent-intake-section-contact" className="agent-intake-section">
        <legend
          id="agent-intake-section-contact-legend"
          className="agent-intake-section-legend"
        >
          <span className="agent-intake-section-number" aria-hidden="true">
            02
          </span>
          How we'll reach you
        </legend>
        <div className="agent-intake-section-fields">
          <TextField
            id={INPUT_ID_FOR_FIELD.email}
            label="Email address"
            type="email"
            value={values.email}
            onChange={(value) => setFieldValue("email", value)}
            onBlur={() => validateFieldOnBlur("email")}
            error={fieldErrors.email}
            isRequired
            maxLength={SHOPPER_INTAKE_MAX_LENGTHS.email}
            autoComplete="email"
          />
          <TextField
            id={INPUT_ID_FOR_FIELD.phone}
            label="Phone number"
            type="tel"
            value={values.phone}
            onChange={(value) => setFieldValue("phone", value)}
            onBlur={() => validateFieldOnBlur("phone")}
            error={fieldErrors.phone}
            isRequired
            maxLength={SHOPPER_INTAKE_MAX_LENGTHS.phone}
            autoComplete="tel"
          />
          <SelectField
            id={INPUT_ID_FOR_FIELD.preferredContactMethod}
            label="Preferred contact method"
            value={values.preferredContactMethod}
            onChange={(value) =>
              setFieldValue("preferredContactMethod", value)
            }
            options={CONTACT_METHOD_OPTIONS}
            placeholder="No preference"
          />
          <TextField
            id={INPUT_ID_FOR_FIELD.streetAddress}
            label="Street address"
            value={values.streetAddress}
            onChange={(value) => setFieldValue("streetAddress", value)}
            maxLength={SHOPPER_INTAKE_MAX_LENGTHS.streetAddress}
            autoComplete="street-address"
            helper="Optional"
          />
          <TextField
            id={INPUT_ID_FOR_FIELD.zipCode}
            label="ZIP code"
            value={values.zipCode}
            onChange={(value) => setFieldValue("zipCode", value)}
            onBlur={() => validateFieldOnBlur("zipCode")}
            error={fieldErrors.zipCode}
            isRequired
            inputMode="numeric"
            maxLength={SHOPPER_INTAKE_MAX_LENGTHS.zipCode}
            autoComplete="postal-code"
          />
        </div>
      </fieldset>

      {/* 03 — Your coverage interests */}
      <fieldset
        id="agent-intake-section-coverage"
        className="agent-intake-section"
      >
        <legend
          id="agent-intake-section-coverage-legend"
          className="agent-intake-section-legend"
        >
          <span className="agent-intake-section-number" aria-hidden="true">
            03
          </span>
          Your coverage interests
        </legend>
        <div className="agent-intake-section-fields">
          <CheckboxGroup
            id={INPUT_ID_FOR_FIELD.productLines}
            label="What are they interested in?"
            options={productLineOptions}
            selectedValues={values.productLines}
            onChange={(selected) => setFieldValue("productLines", selected)}
            onBlur={() => validateFieldOnBlur("productLines")}
            error={fieldErrors.productLines}
            isRequired
          />
          <TextField
            id={INPUT_ID_FOR_FIELD.notes}
            label="Anything else to note?"
            value={values.notes}
            onChange={(value) => setFieldValue("notes", value)}
            maxLength={SHOPPER_INTAKE_MAX_LENGTHS.notes}
            helper="Optional"
          />
        </div>
      </fieldset>

      {submitError !== null && (
        <p
          id="agent-intake-submit-error"
          className="agent-intake-submit-error"
          role="alert"
        >
          {submitError}
        </p>
      )}

      <div id="agent-intake-actions" className="agent-intake-actions">
        <Button
          id="agent-intake-submit"
          type="submit"
          variant="filled"
          isPending={isSubmitting}
        >
          Create lead
        </Button>
      </div>
    </form>
  );
}
