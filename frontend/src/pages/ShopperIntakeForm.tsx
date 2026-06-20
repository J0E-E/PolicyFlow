import { useRef, useState } from "react";
import TextField from "../components/TextField.tsx";
import SelectField from "../components/SelectField.tsx";
import CheckboxGroup from "../components/CheckboxGroup.tsx";
import Button from "../components/Button.tsx";
import IntakeErrorSummary from "./IntakeErrorSummary.tsx";
import IntakeSuccessPanel from "./IntakeSuccessPanel.tsx";
import { shopperIntakePrefills } from "./shopperIntakePrefills.ts";
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
import { ApiError, submitPublicIntake } from "../api";
import type { Tenant } from "../api";

interface ShopperIntakeFormProperties {
  /** The loaded tenant (slug, display_name, product_lines) threaded down from
   *  ShopperSitePage → ShopperHomePage. The slug names the tenant on the public
   *  endpoint; the product lines drive the coverage-interests checkbox group. */
  tenant: Tenant;
}

// The three preferred-contact options the backend honors (schemas.py
// _ALLOWED_CONTACT_METHODS), labeled for a consumer.
const CONTACT_METHOD_OPTIONS = [
  { value: "email", label: "Email" },
  { value: "phone", label: "Phone call" },
  { value: "text", label: "Text message" },
];

// The input id each form field maps to — so the top error summary can link
// straight to the offending control (its href is `#${id}`).
const INPUT_ID_FOR_FIELD: Record<keyof ShopperIntakeFormValues, string> = {
  firstName: "shopper-intake-first-name",
  lastName: "shopper-intake-last-name",
  email: "shopper-intake-email",
  phone: "shopper-intake-phone",
  dateOfBirth: "shopper-intake-date-of-birth",
  zipCode: "shopper-intake-zip-code",
  streetAddress: "shopper-intake-street-address",
  preferredContactMethod: "shopper-intake-preferred-contact-method",
  notes: "shopper-intake-notes",
  productLines: "shopper-intake-product-lines",
};

// The public Shopper intake form (Guide §5 fields, §6.9 prefill row). It owns
// the form values, the validate-on-blur + validate-on-submit errors, the
// honeypot, the prefill buttons, the submit lifecycle, and the success / form-
// level-error states. The reusable field set (TextField / SelectField /
// CheckboxGroup) carries the per-field anatomy; this component arranges them
// into the three ACORD-numbered sections and wires submission to the public
// endpoint. On success the whole form is replaced by the confirmation panel.
export default function ShopperIntakeForm({
  tenant,
}: ShopperIntakeFormProperties) {
  const [values, setValues] = useState<ShopperIntakeFormValues>(
    emptyShopperIntakeValues,
  );
  // The honeypot value — kept out of `values` (it is never validated and never
  // shown), only read at submit time to fill the `website` field.
  const [honeypotValue, setHoneypotValue] = useState("");
  const [fieldErrors, setFieldErrors] = useState<ShopperIntakeFieldErrors>({});
  // A form-level (network / 429) failure message — keeps the entered data.
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSubmitted, setIsSubmitted] = useState(false);

  // The error summary takes focus on a failed submit (Guide §5/§7).
  const errorSummaryRef = useRef<HTMLDivElement>(null);

  const prefills = shopperIntakePrefills(tenant);
  const productLineOptions = tenant.product_lines.map((productLine) => ({
    value: productLine.key,
    label: productLine.label,
  }));

  // Update one text/select field's value.
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
  const applyPrefill = (buildValues: (tenant: Tenant) => ShopperIntakeFormValues) => {
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
      // The success body is always `{ ok: true }` (sanitized) — drive success
      // off the resolved call, never off any returned lead.
      await submitPublicIntake({
        tenant_slug: tenant.slug,
        website: honeypotValue,
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
      setIsSubmitted(true);
    } catch (error) {
      // A 429 (rate limited) or a network drop — a form-level message that keeps
      // the entered data so the visitor can simply retry.
      const isRateLimited = error instanceof ApiError && error.status === 429;
      setSubmitError(
        isRateLimited
          ? "Too many requests right now. Please wait a moment and try again."
          : "We couldn't send your request. Check your connection and try again.",
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  // Reset back to a fresh blank intake (from the success panel).
  const handleReset = () => {
    setValues(emptyShopperIntakeValues);
    setHoneypotValue("");
    setFieldErrors({});
    setSubmitError(null);
    setIsSubmitted(false);
  };

  if (isSubmitted) {
    return (
      <IntakeSuccessPanel
        tenantName={tenant.display_name}
        onReset={handleReset}
      />
    );
  }

  const hasErrors = Object.values(fieldErrors).some(
    (message) => message !== undefined,
  );

  return (
    <form
      id="shopper-intake-form"
      className="shopper-intake-form"
      onSubmit={handleSubmit}
      noValidate
    >
      {/* Prefill row — the two backed demo scenarios (Guide §6.9). */}
      <div id="shopper-intake-prefill-row" className="shopper-intake-prefill-row">
        <p
          id="shopper-intake-prefill-heading"
          className="shopper-intake-prefill-heading"
        >
          In a hurry? Start from a sample.
        </p>
        <div
          id="shopper-intake-prefill-buttons"
          className="shopper-intake-prefill-buttons"
        >
          {prefills.map((prefill) => (
            <div
              id={`shopper-intake-prefill-${prefill.id}`}
              key={prefill.id}
              className="shopper-intake-prefill"
            >
              <Button
                id={`shopper-intake-prefill-${prefill.id}-button`}
                variant="tonal"
                onClick={() => applyPrefill(prefill.buildValues)}
              >
                {prefill.label}
              </Button>
              <span
                id={`shopper-intake-prefill-${prefill.id}-outcome`}
                className="shopper-intake-prefill-outcome"
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

      {/* The honeypot: an off-screen `website` field a human never sees or fills
          (aria-hidden, tabIndex -1, autoComplete off — NOT display:none, so a bot
          that reads visibility still fills it). No client validation. */}
      <div
        id="shopper-intake-honeypot-wrapper"
        className="shopper-intake-honeypot"
        aria-hidden="true"
      >
        <label
          id="shopper-intake-honeypot-label"
          htmlFor="shopper-intake-website"
        >
          Website
        </label>
        <input
          id="shopper-intake-website"
          type="text"
          name="website"
          tabIndex={-1}
          autoComplete="off"
          value={honeypotValue}
          onChange={(changeEvent) => setHoneypotValue(changeEvent.target.value)}
        />
      </div>

      {/* 01 — About you */}
      <fieldset id="shopper-intake-section-about" className="shopper-intake-section">
        <legend
          id="shopper-intake-section-about-legend"
          className="shopper-intake-section-legend"
        >
          <span className="shopper-intake-section-number" aria-hidden="true">
            01
          </span>
          About you
        </legend>
        <div className="shopper-intake-section-fields">
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
      <fieldset id="shopper-intake-section-contact" className="shopper-intake-section">
        <legend
          id="shopper-intake-section-contact-legend"
          className="shopper-intake-section-legend"
        >
          <span className="shopper-intake-section-number" aria-hidden="true">
            02
          </span>
          How we'll reach you
        </legend>
        <div className="shopper-intake-section-fields">
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
      <fieldset id="shopper-intake-section-coverage" className="shopper-intake-section">
        <legend
          id="shopper-intake-section-coverage-legend"
          className="shopper-intake-section-legend"
        >
          <span className="shopper-intake-section-number" aria-hidden="true">
            03
          </span>
          Your coverage interests
        </legend>
        <div className="shopper-intake-section-fields">
          <CheckboxGroup
            id={INPUT_ID_FOR_FIELD.productLines}
            label="What are you interested in?"
            options={productLineOptions}
            selectedValues={values.productLines}
            onChange={(selected) => setFieldValue("productLines", selected)}
            onBlur={() => validateFieldOnBlur("productLines")}
            error={fieldErrors.productLines}
            isRequired
          />
          <TextField
            id={INPUT_ID_FOR_FIELD.notes}
            label="Anything else we should know?"
            value={values.notes}
            onChange={(value) => setFieldValue("notes", value)}
            maxLength={SHOPPER_INTAKE_MAX_LENGTHS.notes}
            helper="Optional"
          />
        </div>
      </fieldset>

      {submitError !== null && (
        <p
          id="shopper-intake-submit-error"
          className="shopper-intake-submit-error"
          role="alert"
        >
          {submitError}
        </p>
      )}

      <div id="shopper-intake-actions" className="shopper-intake-actions">
        <Button
          id="shopper-intake-submit"
          type="submit"
          variant="filled"
          isPending={isSubmitting}
        >
          Send my request
        </Button>
      </div>
    </form>
  );
}
