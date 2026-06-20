import { useState } from "react";
import { Eye, Lock } from "iconoir-react";
import Button from "../components/Button.tsx";
import { revealLeadField } from "../api";
import type { RevealableField } from "../api";

// One revealable PII row on the lead detail page (Epic 21, Guide §6.4). The value
// renders MASKED by default (mono, behind a lock glyph). A holder of `reveal_pii`
// gets an inline "Unseal · audited" affordance — deliberately NOT a button: a
// dashed-underline + eye glyph, so the sensitive, logged nature of the action is
// felt before the click. Activating it opens a short inline confirm ("Reveal
// {field}? This is logged."); confirming calls the audited reveal endpoint and
// swaps the mask for the cleartext value plus an ochre "revealed — audited" marker.
//
// Deviations from the Guide §6.4 ideal, both forced by what exists today:
//   - The confirm is INLINE, not a modal Dialog — no Dialog component exists yet
//     (a reusable one is deferred to a later epic that needs it).
//   - The "revealed — audited" marker carries NO event id — the Epic 15 reveal
//     response is `{field, value}` only (no event id on the wire).
//
// Read-Only (no `reveal_pii`) sees the mask with NO control at all. An absent
// optional field (a `null` value, e.g. no street address on file) is the caller's
// responsibility — this component is only rendered for present, revealable fields.

/** The per-field reveal lifecycle. `confirming` shows the release-form confirm;
 *  `revealing` is the in-flight call; `revealed` holds the cleartext value. */
type RevealState =
  | { kind: "idle" }
  | { kind: "confirming" }
  | { kind: "revealing" }
  | { kind: "revealed"; value: string }
  | { kind: "error" };

interface RevealableLeadFieldProperties {
  /** The element id base (e.g. `lead-detail-email`); spans derive from it. */
  id: string;
  /** The row label (e.g. `Email`). */
  label: string;
  /** The lead whose field this reveals. */
  leadId: string;
  /** Which encrypted field this row unmasks. */
  field: RevealableField;
  /** The masked display string shown until (and unless) the value is revealed. */
  maskedValue: string;
  /** Whether the viewer holds `reveal_pii` — drives whether any control shows. */
  canReveal: boolean;
}

export default function RevealableLeadField({
  id,
  label,
  leadId,
  field,
  maskedValue,
  canReveal,
}: RevealableLeadFieldProperties) {
  const [revealState, setRevealState] = useState<RevealState>({ kind: "idle" });

  const confirmReveal = () => {
    setRevealState({ kind: "revealing" });
    revealLeadField(leadId, { field })
      .then((response) => {
        // An absent value (the field has no stored data) comes back as null — show
        // the same "Not provided" we'd show for a masked absent field, revealed.
        setRevealState({
          kind: "revealed",
          value: response.value ?? "Not provided",
        });
      })
      .catch(() => {
        setRevealState({ kind: "error" });
      });
  };

  return (
    <div id={`${id}-row`} className="lead-detail-row">
      <dt id={`${id}-label`} className="lead-detail-label">
        {label}
      </dt>
      <dd id={`${id}-content`} className="lead-detail-value">
        {revealState.kind === "revealed" ? (
          <span id={`${id}-revealed`} className="lead-detail-revealed">
            <span
              id={`${id}-revealed-value`}
              className="lead-detail-revealed-value"
            >
              {revealState.value}
            </span>
            <span
              id={`${id}-revealed-marker`}
              className="lead-detail-revealed-marker"
            >
              revealed — audited
            </span>
          </span>
        ) : (
          <span id={`${id}-masked`} className="lead-detail-masked">
            <span id={`${id}-lock`} className="lead-detail-lock" aria-hidden="true">
              <Lock width={14} height={14} />
            </span>
            <span id={`${id}-value`} className="lead-detail-masked-value">
              {maskedValue}
            </span>
          </span>
        )}

        {/* The §6.4 "Unseal · audited" affordance — only for reveal_pii holders,
            and only while the field is still masked (idle). */}
        {canReveal && revealState.kind === "idle" && (
          <button
            id={`${id}-unseal`}
            type="button"
            className="lead-detail-unseal"
            onClick={() => setRevealState({ kind: "confirming" })}
          >
            <span
              id={`${id}-unseal-icon`}
              className="lead-detail-unseal-icon"
              aria-hidden="true"
            >
              <Eye width={14} height={14} />
            </span>
            <span id={`${id}-unseal-label`} className="lead-detail-unseal-label">
              Unseal · audited
            </span>
          </button>
        )}

        {/* The inline confirm — a short "release form" (Guide §6.4). */}
        {revealState.kind === "confirming" && (
          <span id={`${id}-confirm`} className="lead-detail-confirm" role="group">
            <span id={`${id}-confirm-message`} className="lead-detail-confirm-message">
              Reveal {label.toLowerCase()}? This is logged.
            </span>
            <span id={`${id}-confirm-actions`} className="lead-detail-confirm-actions">
              <Button
                id={`${id}-confirm-button`}
                variant="filled"
                onClick={confirmReveal}
              >
                Reveal
              </Button>
              <Button
                id={`${id}-cancel-button`}
                variant="text"
                onClick={() => setRevealState({ kind: "idle" })}
              >
                Cancel
              </Button>
            </span>
          </span>
        )}

        {revealState.kind === "revealing" && (
          <span
            id={`${id}-revealing`}
            className="lead-detail-revealing"
            role="status"
            aria-live="polite"
          >
            Revealing…
          </span>
        )}

        {/* A failed reveal — non-destructive: the mask stays, retry is offered. */}
        {revealState.kind === "error" && (
          <span id={`${id}-reveal-error`} className="lead-detail-reveal-error" role="alert">
            <span id={`${id}-reveal-error-message`}>
              We couldn't reveal that field. Please try again.
            </span>
            <Button
              id={`${id}-reveal-retry-button`}
              variant="text"
              onClick={() => setRevealState({ kind: "confirming" })}
            >
              Try again
            </Button>
          </span>
        )}
      </dd>
    </div>
  );
}
