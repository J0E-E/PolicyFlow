import { forwardRef } from "react";
import { WarningTriangle } from "iconoir-react";
import type {
  ShopperIntakeFieldErrors,
  ShopperIntakeFormValues,
} from "./shopperIntakeValidation.ts";

interface IntakeErrorSummaryProperties {
  /** The field errors to list — order follows the entries passed in. */
  errors: ShopperIntakeFieldErrors;
  /** The field order to list errors in (form order), plus each field's input id
   *  so the summary's links jump straight to the offending control. */
  fieldOrder: (keyof ShopperIntakeFormValues)[];
  inputIdForField: Record<keyof ShopperIntakeFormValues, string>;
}

// The top-of-form error summary shown on a failed submit (Guide §5, §7). Focus
// moves to it (the parent holds the ref and focuses on submit) so a keyboard or
// screen-reader user is taken straight to what to fix; each row links to the
// offending field by id. A solid-border `--state-error` panel — distinct from
// the dashed "Simulated" border (Guide §6.3). Styling lives in
// styles/shopper-intake.css.
const IntakeErrorSummary = forwardRef<
  HTMLDivElement,
  IntakeErrorSummaryProperties
>(function IntakeErrorSummary({ errors, fieldOrder, inputIdForField }, ref) {
  const listedFields = fieldOrder.filter((field) => errors[field] !== undefined);
  const errorCount = listedFields.length;

  return (
    <div
      id="shopper-intake-error-summary"
      ref={ref}
      className="shopper-intake-error-summary"
      role="alert"
      tabIndex={-1}
    >
      <p
        id="shopper-intake-error-summary-title"
        className="shopper-intake-error-summary-title"
      >
        <span
          id="shopper-intake-error-summary-icon"
          className="shopper-intake-error-summary-icon"
          aria-hidden="true"
        >
          <WarningTriangle width={18} height={18} />
        </span>
        {errorCount === 1
          ? "Fix 1 field to continue."
          : `Fix ${errorCount} fields to continue.`}
      </p>
      <ul
        id="shopper-intake-error-summary-list"
        className="shopper-intake-error-summary-list"
      >
        {listedFields.map((field) => (
          <li
            id={`shopper-intake-error-summary-item-${field}`}
            key={field}
            className="shopper-intake-error-summary-item"
          >
            <a
              id={`shopper-intake-error-summary-link-${field}`}
              className="shopper-intake-error-summary-link"
              href={`#${inputIdForField[field]}`}
            >
              {errors[field]}
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
});

export default IntakeErrorSummary;
