import { useCallback, useRef } from "react";
import { Xmark } from "iconoir-react";
import { useFocusTrap } from "./useFocusTrap.ts";
import {
  SCENARIO_CATEGORIES,
  SCENARIO_REFERENCE_INTRO,
} from "./scenarioReference.ts";
import ScenarioReferenceEntry from "./ScenarioReferenceEntry.tsx";

interface ScenarioReferencePanelProperties {
  /** Whether the modal is open — the single flag lifted into AppShell and shared
   *  with the two openers (the masthead help icon, the docket-header link). */
  isOpen: boolean;
  /** Close the modal — restores focus to whichever opener was used (AppShell owns
   *  the flag; this component restores focus to the captured opener element). */
  onClose: () => void;
}

// The scenario-reference modal (Guide §5 modal dialog, §6.9 catalog). UNLIKE the
// non-modal Epic 9 Popover, this is a true modal: a full-viewport scrim centring a
// paper dialog sheet (--surface-2 — the plan named --surface-4, which the Epic 6
// token set does not define; see the Epic 18 note — at --radius-lg + --elevation-3)
// that blocks the workspace while open. It honors the full Guide §7 dialog contract:
//   - role="dialog" + aria-modal + aria-labelledby (its title) + aria-describedby
//     (the intro), so a screen reader announces what it is on open.
//   - Focus moves into the dialog on open and Tab is trapped inside it (reusing the
//     Epic 9 useFocusTrap hook), so keyboard users cannot wander behind the scrim.
//   - Closes on Esc, the close button, OR a scrim (outside) click — and ALWAYS
//     restores focus to the opener that launched it (captured at open time), since a
//     modal must never strand focus on the scrim.
//   - prefers-reduced-motion is honored by the global rule in base.css (the enter
//     animation is opacity/transform; no per-component override).
//
// The catalog itself is pure data (scenarioReference.ts); each entry renders as an
// Epic 8 Card with a neutral Epic 8 StampTag marker. Every element gets a unique
// descriptive id (CLAUDE.md). Styling lives in styles/scenario-reference.css.
export default function ScenarioReferencePanel({
  isOpen,
  onClose,
}: ScenarioReferencePanelProperties) {
  const surfaceRef = useRef<HTMLDivElement>(null);
  // The element that opened the modal (the masthead help icon or the docket link).
  // Captured the first render the modal is open, restored to on any close — a modal
  // must return focus to its opener, whichever one it was (Guide §7).
  const openerRef = useRef<HTMLElement | null>(null);
  if (isOpen && openerRef.current === null) {
    openerRef.current = document.activeElement as HTMLElement | null;
  }

  // A modal always restores focus to its opener on close (the boolean the hook
  // passes is the non-modal popover semantic; here every close restores).
  const handleRequestClose = useCallback(() => {
    const opener = openerRef.current;
    openerRef.current = null;
    onClose();
    opener?.focus();
  }, [onClose]);

  // Reuse the Epic 9 focus trap: move focus into the dialog on open, cycle Tab
  // within it, close on Esc, and close on an outside (scrim) mousedown. `triggerRef`
  // is the captured opener so the hook's outside-click test ignores a click back on
  // it and Esc-restore targets it.
  useFocusTrap({
    isOpen,
    surfaceRef,
    triggerRef: openerRef,
    onRequestClose: handleRequestClose,
  });

  if (!isOpen) {
    return null;
  }

  return (
    <div
      id="scenario-reference-scrim"
      className="scenario-reference-scrim"
      // The scrim is the visual backdrop; a mousedown on it closes the modal (handled
      // by useFocusTrap's outside-click). It carries NO aria-hidden — that would hide
      // the dialog it wraps from assistive tech; it is simply a div with no role, so it
      // contributes nothing to the a11y tree without hiding its accessible child.
    >
      <div
        id="scenario-reference-dialog"
        ref={surfaceRef}
        className="scenario-reference-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="scenario-reference-title"
        aria-describedby="scenario-reference-intro"
        tabIndex={-1}
      >
        <header
          id="scenario-reference-header"
          className="scenario-reference-header"
        >
          <div
            id="scenario-reference-heading-group"
            className="scenario-reference-heading-group"
          >
            <h2
              id="scenario-reference-title"
              className="scenario-reference-title"
            >
              Scenario reference
            </h2>
            <p
              id="scenario-reference-intro"
              className="scenario-reference-intro"
            >
              {SCENARIO_REFERENCE_INTRO}
            </p>
          </div>
          <button
            id="scenario-reference-close"
            type="button"
            className="scenario-reference-close"
            onClick={handleRequestClose}
          >
            <Xmark
              width={20}
              height={20}
              aria-hidden="true"
              className="scenario-reference-close-icon"
            />
            <span
              id="scenario-reference-close-label"
              className="scenario-reference-visually-hidden"
            >
              Close the scenario reference
            </span>
          </button>
        </header>

        <div id="scenario-reference-body" className="scenario-reference-body">
          {SCENARIO_CATEGORIES.map((category) => (
            <section
              key={category.slug}
              id={`scenario-reference-category-${category.slug}`}
              className="scenario-reference-category"
              aria-labelledby={`scenario-reference-category-${category.slug}-title`}
            >
              <h3
                id={`scenario-reference-category-${category.slug}-title`}
                className="scenario-reference-category-title"
              >
                {category.title}
              </h3>
              <p
                id={`scenario-reference-category-${category.slug}-description`}
                className="scenario-reference-category-description"
              >
                {category.description}
              </p>
              <ul
                id={`scenario-reference-category-${category.slug}-list`}
                className="scenario-reference-entry-list"
              >
                {category.entries.map((entry) => (
                  <li
                    key={entry.slug}
                    id={`scenario-reference-entry-${entry.slug}`}
                    className="scenario-reference-entry-item"
                  >
                    <ScenarioReferenceEntry
                      id={`scenario-reference-entry-${entry.slug}-card`}
                      entry={entry}
                    />
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}
