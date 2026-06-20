import type { InputHTMLAttributes, ReactNode } from "react";

// Which native input types this field supports. `date` powers the
// date-of-birth control (emits `YYYY-MM-DD`); the rest are plain text-like
// inputs. Kept narrow so a consumer can't pass `checkbox`/`radio` (those have
// their own components).
type TextFieldInputType = "text" | "email" | "tel" | "date";

interface TextFieldProperties {
  /** Required so every rendered element is uniquely targetable (CLAUDE.md).
   *  The label is `${id}-label`, the input is `${id}` (so the label's `htmlFor`
   *  matches), the error is `${id}-error`, and the helper is `${id}-helper`. */
  id: string;
  /** The visible label above the input (Guide §5 label-above anatomy). */
  label: string;
  /** The controlled value. */
  value: string;
  /** Called with the next value on every keystroke. */
  onChange: (value: string) => void;
  /** Native input type (default "text"). */
  type?: TextFieldInputType;
  /** Marks the field required — adds the visual marker and `aria-required`. The
   *  server stays authoritative; this is the on-screen presence cue only. */
  isRequired?: boolean;
  /** The error message to show below the input. When present the field paints
   *  its `--state-error` state and wires `aria-invalid` + `aria-describedby`. */
  error?: string;
  /** Optional helper text below the input (e.g. a format hint). Hidden once an
   *  error shows — the error takes the describedby slot. */
  helper?: string;
  /** Called when focus leaves the input — the Guide's validate-on-blur trigger. */
  onBlur?: () => void;
  /** Native max length — the client mirror of the backend length caps. */
  maxLength?: number;
  /** Native autocomplete hint, passed straight to the input. */
  autoComplete?: InputHTMLAttributes<HTMLInputElement>["autoComplete"];
  /** Native input mode hint (e.g. "numeric" for zip) for on-screen keyboards. */
  inputMode?: InputHTMLAttributes<HTMLInputElement>["inputMode"];
  /** Optional trailing content rendered after the input (unused here; kept for
   *  Epic 19's reuse, e.g. an inline reveal control). */
  trailing?: ReactNode;
}

// A single text-like form field with the Guide §5 anatomy: label above, the
// input, then helper/error below. On error it switches to the `--state-error`
// register and wires the full ARIA contract (`aria-invalid`,
// `aria-describedby` → the error id). Pure and controlled; styling lives in
// styles/form-field.css. Epic 19's agent intake form reuses it verbatim.
export default function TextField({
  id,
  label,
  value,
  onChange,
  type = "text",
  isRequired = false,
  error,
  helper,
  onBlur,
  maxLength,
  autoComplete,
  inputMode,
  trailing,
}: TextFieldProperties) {
  const labelId = `${id}-label`;
  const errorId = `${id}-error`;
  const helperId = `${id}-helper`;
  const hasError = error !== undefined && error !== "";
  // The error replaces the helper in the describedby slot — never both, so a
  // screen reader hears the actionable message, not stale guidance.
  const describedBy = hasError
    ? errorId
    : helper !== undefined && helper !== ""
      ? helperId
      : undefined;

  return (
    <div
      id={`${id}-field`}
      className={hasError ? "form-field form-field-error" : "form-field"}
    >
      <label id={labelId} htmlFor={id} className="form-field-label">
        {label}
        {isRequired && (
          <span
            id={`${id}-required-marker`}
            className="form-field-required-marker"
            aria-hidden="true"
          >
            {" *"}
          </span>
        )}
      </label>
      <div id={`${id}-control`} className="form-field-control">
        <input
          id={id}
          className="form-field-input"
          type={type}
          value={value}
          required={isRequired}
          aria-required={isRequired}
          aria-invalid={hasError}
          aria-describedby={describedBy}
          maxLength={maxLength}
          autoComplete={autoComplete}
          inputMode={inputMode}
          onChange={(changeEvent) => onChange(changeEvent.target.value)}
          onBlur={onBlur}
        />
        {trailing}
      </div>
      {hasError ? (
        <p id={errorId} className="form-field-error-text" role="alert">
          {error}
        </p>
      ) : (
        helper !== undefined &&
        helper !== "" && (
          <p id={helperId} className="form-field-helper-text">
            {helper}
          </p>
        )
      )}
    </div>
  );
}
