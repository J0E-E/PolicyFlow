import type { MouseEventHandler, ReactNode } from "react";
import { buttonClassName } from "./buttonVariants.ts";
import type { ButtonVariant } from "./buttonVariants.ts";

interface ButtonProperties {
  /** Required so every rendered element is uniquely targetable (CLAUDE.md).
   *  The label span is `${id}-label`; the pending spinner is `${id}-spinner`. */
  id: string;
  /** One of the Guide's four variants (Guide §5). */
  variant: ButtonVariant;
  /** The button label. */
  children: ReactNode;
  /** Native button type. Defaults to "button" so a button inside a form never
   *  submits it by accident. */
  type?: "button" | "submit" | "reset";
  disabled?: boolean;
  /** While true the button shows an inline spinner and is non-interactive — the
   *  visible "working…" state for an in-flight action (Guide §5). */
  isPending?: boolean;
  onClick?: MouseEventHandler<HTMLButtonElement>;
}

// The reusable Button primitive: a real `<button>` carrying one of the Guide's
// four variants, the global focus ring (base.css), and an optional pending state
// (spinner + disabled). Navigation that should be a link uses `ButtonLink`
// instead. Kept small and focused (React philosophy); styling lives in
// styles/button.css and the variant-to-class mapping in buttonVariants.ts.
export default function Button({
  id,
  variant,
  children,
  type = "button",
  disabled = false,
  isPending = false,
  onClick,
}: ButtonProperties) {
  // A pending action is disabled too, so the click cannot fire mid-flight.
  const isDisabled = disabled || isPending;

  return (
    <button
      id={id}
      type={type}
      className={buttonClassName(variant)}
      disabled={isDisabled}
      aria-busy={isPending}
      onClick={onClick}
    >
      {isPending && (
        <span
          id={`${id}-spinner`}
          className="button-spinner"
          aria-hidden="true"
        />
      )}
      <span id={`${id}-label`} className="button-label">
        {children}
      </span>
    </button>
  );
}
