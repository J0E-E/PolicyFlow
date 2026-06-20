/** One choice in a select — the wire `value` plus its human `label`. */
export interface SelectOption {
  value: string;
  label: string;
}

interface SelectFieldProperties {
  /** Required so every rendered element is uniquely targetable (CLAUDE.md).
   *  The label is `${id}-label`, the select is `${id}` (matches the label's
   *  `htmlFor`), the error is `${id}-error`, the helper is `${id}-helper`. */
  id: string;
  /** The visible label above the select (Guide §5 label-above anatomy). */
  label: string;
  /** The controlled value — the empty string selects the placeholder option. */
  value: string;
  /** Called with the next value when the selection changes. */
  onChange: (value: string) => void;
  /** The selectable options (rendered in order, after the placeholder). */
  options: SelectOption[];
  /** The first, value-less option's label — e.g. "No preference". Selecting it
   *  sets the value back to the empty string. */
  placeholder: string;
  /** Marks the field required for the on-screen presence cue + `aria-required`. */
  isRequired?: boolean;
  /** The error message below the select; switches the field to its error state. */
  error?: string;
  /** Optional helper text below the select (hidden once an error shows). */
  helper?: string;
  /** Validate-on-blur trigger (Guide §5). */
  onBlur?: () => void;
}

// A native `<select>` field carrying the same Guide §5 anatomy as TextField —
// label above, helper/error below, error register + full ARIA. The first option
// is the value-less placeholder (e.g. "No preference"), so an untouched select
// reads as empty. Pure and controlled; styling lives in styles/form-field.css.
// Epic 19's agent intake form reuses it verbatim.
export default function SelectField({
  id,
  label,
  value,
  onChange,
  options,
  placeholder,
  isRequired = false,
  error,
  helper,
  onBlur,
}: SelectFieldProperties) {
  const labelId = `${id}-label`;
  const errorId = `${id}-error`;
  const helperId = `${id}-helper`;
  const hasError = error !== undefined && error !== "";
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
      <select
        id={id}
        className="form-field-input form-field-select"
        value={value}
        required={isRequired}
        aria-required={isRequired}
        aria-invalid={hasError}
        aria-describedby={describedBy}
        onChange={(changeEvent) => onChange(changeEvent.target.value)}
        onBlur={onBlur}
      >
        <option id={`${id}-option-placeholder`} value="">
          {placeholder}
        </option>
        {options.map((option) => (
          <option
            id={`${id}-option-${option.value}`}
            key={option.value}
            value={option.value}
          >
            {option.label}
          </option>
        ))}
      </select>
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
