/** One checkbox in the group — the wire `value` plus its human `label`. */
export interface CheckboxOption {
  value: string;
  label: string;
}

interface CheckboxGroupProperties {
  /** Required so every rendered element is uniquely targetable (CLAUDE.md).
   *  The fieldset is `${id}`, the legend is `${id}-legend`, each checkbox is
   *  `${id}-option-${value}`, the error is `${id}-error`. */
  id: string;
  /** The group's visible label, rendered as the fieldset legend (Guide §5). */
  label: string;
  /** The options to render, in order. */
  options: CheckboxOption[];
  /** The currently selected values. */
  selectedValues: string[];
  /** Called with the next selected-values array when a box is toggled. */
  onChange: (selectedValues: string[]) => void;
  /** Marks the group required for the on-screen presence cue. */
  isRequired?: boolean;
  /** The error message below the group; switches it to its error state and
   *  wires `aria-describedby` on the fieldset. */
  error?: string;
  /** Optional helper text below the group (hidden once an error shows). */
  helper?: string;
  /** Validate-on-blur trigger — fired when focus leaves the whole group. */
  onBlur?: () => void;
}

// A grouped set of checkboxes built on a real `<fieldset>`/`<legend>` so the
// group is announced as one labeled unit. Carries the Guide §5 anatomy: legend
// above, helper/error below, the error register + ARIA on the fieldset. The
// blur fires only when focus leaves the whole group (not when moving box to
// box), so validate-on-blur doesn't flash mid-selection. Pure and controlled;
// styling lives in styles/form-field.css. Epic 19's agent intake form reuses it.
export default function CheckboxGroup({
  id,
  label,
  options,
  selectedValues,
  onChange,
  isRequired = false,
  error,
  helper,
  onBlur,
}: CheckboxGroupProperties) {
  const legendId = `${id}-legend`;
  const errorId = `${id}-error`;
  const helperId = `${id}-helper`;
  const hasError = error !== undefined && error !== "";
  const describedBy = hasError
    ? errorId
    : helper !== undefined && helper !== ""
      ? helperId
      : undefined;

  // Toggle one value in or out of the selection, preserving option order.
  const toggleValue = (value: string) => {
    const isSelected = selectedValues.includes(value);
    const nextValues = isSelected
      ? selectedValues.filter((selected) => selected !== value)
      : options
          .map((option) => option.value)
          .filter(
            (optionValue) =>
              selectedValues.includes(optionValue) || optionValue === value,
          );
    onChange(nextValues);
  };

  // Fire onBlur only when focus moves outside the fieldset — moving between the
  // group's own checkboxes keeps focus within `currentTarget`.
  const handleBlur = (blurEvent: React.FocusEvent<HTMLFieldSetElement>) => {
    if (
      onBlur &&
      !blurEvent.currentTarget.contains(blurEvent.relatedTarget as Node | null)
    ) {
      onBlur();
    }
  };

  return (
    <fieldset
      id={id}
      className={
        hasError ? "form-field checkbox-group form-field-error" : "form-field checkbox-group"
      }
      aria-describedby={describedBy}
      aria-invalid={hasError}
      onBlur={handleBlur}
    >
      <legend id={legendId} className="form-field-label checkbox-group-legend">
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
      </legend>
      <div id={`${id}-options`} className="checkbox-group-options">
        {options.map((option) => {
          const optionId = `${id}-option-${option.value}`;
          return (
            <label
              id={`${optionId}-label`}
              key={option.value}
              htmlFor={optionId}
              className="checkbox-group-option"
            >
              <input
                id={optionId}
                className="checkbox-group-input"
                type="checkbox"
                value={option.value}
                checked={selectedValues.includes(option.value)}
                onChange={() => toggleValue(option.value)}
              />
              <span
                id={`${optionId}-text`}
                className="checkbox-group-option-text"
              >
                {option.label}
              </span>
            </label>
          );
        })}
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
    </fieldset>
  );
}
