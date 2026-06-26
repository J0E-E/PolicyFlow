import { useState } from "react";
import Button from "../components/Button.tsx";
import { ApiError, revealMedicareId } from "../api";

interface MedicareRevealProperties {
  /** Required so every rendered element is uniquely targetable (CLAUDE.md). */
  id: string;
  /** The application the Medicare ID belongs to — the reveal rides this id (the
   *  policy view reveals via its linked application). */
  applicationId: string;
  /** The masked Medicare ID shown until the agent reveals it. */
  masked: string;
}

// The masked + click-to-reveal Medicare ID control (P2.3 Epic 11). Shows the masked
// value with a Reveal button; on click it calls the audited reveal endpoint and
// swaps in the plaintext. A focused component (Frontend Philosophy) reused by the
// application and policy views. Tokens + design-system primitives only.
export default function MedicareReveal({
  id,
  applicationId,
  masked,
}: MedicareRevealProperties) {
  const [revealedValue, setRevealedValue] = useState<string | null>(null);
  const [isRevealing, setIsRevealing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reveal = () => {
    setError(null);
    setIsRevealing(true);
    revealMedicareId(applicationId)
      .then((result) => {
        setRevealedValue(result.value ?? "—");
        setIsRevealing(false);
      })
      .catch((caught: unknown) => {
        setError(
          caught instanceof ApiError
            ? caught.message
            : "We couldn't reveal the Medicare ID.",
        );
        setIsRevealing(false);
      });
  };

  return (
    <div id={id} className="medicare-reveal">
      <span id={`${id}-label`} className="medicare-reveal-label">
        Medicare ID
      </span>
      <span id={`${id}-value`} className="medicare-reveal-value">
        {revealedValue ?? masked}
      </span>
      {revealedValue === null && (
        <Button
          id={`${id}-reveal`}
          variant="outlined"
          isPending={isRevealing}
          onClick={reveal}
        >
          Reveal
        </Button>
      )}
      {error && (
        <p id={`${id}-error`} className="medicare-reveal-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
