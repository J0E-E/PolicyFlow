import { CheckCircle } from "iconoir-react";
import Button from "../components/Button.tsx";

interface IntakeSuccessPanelProperties {
  /** The tenant's display name, woven into the confirmation copy. */
  tenantName: string;
  /** Reset the form back to a fresh blank intake. */
  onReset: () => void;
}

// The post-submit confirmation that replaces the form on success (Guide §2.2
// success register, §5). A `--state-success` framed panel with a check icon, a
// reassuring title + body naming the tenant, and a "Submit another request"
// reset. Shown on the real-create path (the server returns `{ ok: true }`);
// because the public endpoint is sanitized, there is nothing lead-specific to
// show — just the confirmation. Styling lives in styles/shopper-intake.css.
export default function IntakeSuccessPanel({
  tenantName,
  onReset,
}: IntakeSuccessPanelProperties) {
  return (
    <div
      id="shopper-intake-success"
      className="shopper-intake-success"
      role="status"
      aria-live="polite"
    >
      <span
        id="shopper-intake-success-icon"
        className="shopper-intake-success-icon"
        aria-hidden="true"
      >
        <CheckCircle width={28} height={28} />
      </span>
      <h2
        id="shopper-intake-success-title"
        className="shopper-intake-success-title"
      >
        Thanks — your request is in.
      </h2>
      <p
        id="shopper-intake-success-body"
        className="shopper-intake-success-body"
      >
        A licensed {tenantName} agent will review your details and reach out
        soon. No obligation.
      </p>
      <Button
        id="shopper-intake-success-reset"
        variant="tonal"
        onClick={onReset}
      >
        Submit another request
      </Button>
    </div>
  );
}
