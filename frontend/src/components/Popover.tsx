import { useCallback, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useFocusTrap } from "./useFocusTrap.ts";

interface PopoverProperties {
  /** Required so every rendered element is uniquely targetable (CLAUDE.md).
   *  Derives `${id}-trigger` (the button) and `${id}-surface` (the panel). */
  id: string;
  /** The trigger button's visible content — an icon, a label, or both. Consumers
   *  (Epic 19's explainer icon, Epic 20's "Simulated" stamp) supply their own. */
  trigger: ReactNode;
  /** The trigger's accessible name — required because the trigger is typically
   *  icon-only, so its visible content carries no readable text (Guide §7). */
  triggerLabel: string;
  /** Optional extra class on the trigger button so a consumer can style it
   *  (e.g. Epic 20's dashed "Simulated" stamp) on top of the base reset. */
  triggerClassName?: string;
  /** The panel's accessible name (its `aria-label`) — what a screen reader
   *  announces when focus moves into the open margin note. */
  surfaceLabel: string;
  /** The margin-note contents. */
  children: ReactNode;
}

// The anchored, focus-trapped "margin note" popover (Guide §6.2) — a
// self-contained primitive that owns BOTH the trigger button and the floating
// panel, plus the open/close state and the full keyboard/ARIA contract. It is
// non-modal (no scrim — it never blocks the workflow): focus moves into the
// panel on open, Tab is trapped inside it, and Esc / an outside mousedown /
// re-clicking the trigger all close it. The panel anchors below the trigger with
// plain CSS (in-tree, no portal, no edge-flip). Epics 19/20 wrap this primitive
// and supply only their own trigger look + contents. The hand-rolled focus trap
// (no new dependency, TDD Decision 6) lives in useFocusTrap.ts; styling lives in
// styles/popover.css.
export default function Popover({
  id,
  trigger,
  triggerLabel,
  triggerClassName,
  surfaceLabel,
  children,
}: PopoverProperties) {
  const [isOpen, setIsOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const surfaceRef = useRef<HTMLDivElement>(null);

  const triggerId = `${id}-trigger`;
  const surfaceId = `${id}-surface`;

  // Esc restores focus to the trigger; an outside mousedown leaves focus where
  // the user clicked. The trigger button is already focused after a toggle-close.
  const handleRequestClose = useCallback(
    (shouldRestoreFocusToTrigger: boolean) => {
      setIsOpen(false);
      if (shouldRestoreFocusToTrigger) {
        triggerRef.current?.focus();
      }
    },
    [],
  );

  useFocusTrap({
    isOpen,
    surfaceRef,
    triggerRef,
    onRequestClose: handleRequestClose,
  });

  const toggleOpen = useCallback(() => {
    setIsOpen((wasOpen) => !wasOpen);
  }, []);

  return (
    <span id={id} className="popover-root">
      <button
        id={triggerId}
        ref={triggerRef}
        type="button"
        className={
          triggerClassName ? `popover-trigger ${triggerClassName}` : "popover-trigger"
        }
        aria-haspopup="dialog"
        aria-expanded={isOpen}
        aria-controls={isOpen ? surfaceId : undefined}
        aria-label={triggerLabel}
        onClick={toggleOpen}
      >
        {trigger}
      </button>
      {isOpen && (
        <div
          id={surfaceId}
          ref={surfaceRef}
          className="popover-surface"
          role="dialog"
          aria-label={surfaceLabel}
          tabIndex={-1}
        >
          {children}
        </div>
      )}
    </span>
  );
}
