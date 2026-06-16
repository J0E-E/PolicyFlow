import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { buttonClassName } from "./buttonVariants.ts";
import type { ButtonVariant } from "./buttonVariants.ts";

interface ButtonLinkProperties {
  /** Required so every rendered element is uniquely targetable (CLAUDE.md).
   *  The label span is `${id}-label`. */
  id: string;
  /** One of the Guide's four variants (Guide §5). */
  variant: ButtonVariant;
  /** The in-app route this navigates to (react-router). */
  to: string;
  /** The link label. */
  children: ReactNode;
}

// A button that is really navigation: renders a react-router `<Link>` styled
// exactly like `Button` (shared variant classes), for the case where a click
// should change route rather than run an action. No pending state — navigation
// does not pend. The global focus ring (base.css) covers the focus state. Kept a
// sibling of `Button` rather than a mode of it, so each stays small and the
// element it renders (`<a>` vs `<button>`) is unambiguous (React philosophy).
export default function ButtonLink({
  id,
  variant,
  to,
  children,
}: ButtonLinkProperties) {
  return (
    <Link id={id} className={buttonClassName(variant)} to={to}>
      <span id={`${id}-label`} className="button-label">
        {children}
      </span>
    </Link>
  );
}
