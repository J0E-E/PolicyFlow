import { useEffect } from "react";
import type { RefObject } from "react";

/** The selector for elements a user can Tab to — used to find the trap's edges
 *  (first/last) inside the open surface. Excludes anything explicitly removed
 *  from the tab order (`tabindex="-1"`) and disabled controls. */
const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(", ");

interface FocusTrapOptions {
  /** Whether the surface is currently open — the effect only wires listeners
   *  while true, and tears them all down on close/unmount. */
  isOpen: boolean;
  /** The open surface container (the `role="dialog"`). Focus moves into it on
   *  open and Tab is trapped within its focusable contents. */
  surfaceRef: RefObject<HTMLElement>;
  /** The trigger button. Outside-click ignores clicks on it (the trigger owns
   *  its own toggle), and `onRequestClose` from Esc restores focus to it. */
  triggerRef: RefObject<HTMLElement>;
  /** Called when the surface should close itself — on Esc (focus returns to the
   *  trigger) or on a mousedown outside the root (focus follows the click). */
  onRequestClose: (shouldRestoreFocusToTrigger: boolean) => void;
}

/** Hand-rolled focus trap + dismissal for the non-modal margin-note surface (no
 *  new dependency, per TDD Decision 6). While open it: moves focus into the
 *  surface so the screen reader announces its label; cycles Tab within the
 *  surface's focusable elements (wrapping last→first and first→last); closes on
 *  Esc (restoring focus to the trigger) and on an outside mousedown (leaving
 *  focus where the user clicked). All listeners are removed on close/unmount. */
export function useFocusTrap({
  isOpen,
  surfaceRef,
  triggerRef,
  onRequestClose,
}: FocusTrapOptions): void {
  useEffect(() => {
    if (!isOpen) {
      return;
    }

    const surface = surfaceRef.current;
    if (!surface) {
      return;
    }

    // Move focus into the surface so its aria-label is announced. The container
    // itself is focusable (tabIndex={-1}) for the no-interior-controls case.
    surface.focus();

    const getFocusableElements = (): HTMLElement[] =>
      Array.from(surface.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));

    const handleKeyDown = (event: KeyboardEvent): void => {
      if (event.key === "Escape") {
        event.preventDefault();
        onRequestClose(true);
        return;
      }

      if (event.key !== "Tab") {
        return;
      }

      const focusableElements = getFocusableElements();

      // No interior controls — keep focus pinned on the container.
      if (focusableElements.length === 0) {
        event.preventDefault();
        surface.focus();
        return;
      }

      const firstElement = focusableElements[0];
      const lastElement = focusableElements[focusableElements.length - 1];
      const activeElement = document.activeElement;

      if (event.shiftKey) {
        // Shift+Tab off the first element (or the container) wraps to the last.
        if (activeElement === firstElement || activeElement === surface) {
          event.preventDefault();
          lastElement.focus();
        }
        return;
      }

      // Tab off the last element wraps to the first.
      if (activeElement === lastElement) {
        event.preventDefault();
        firstElement.focus();
      }
    };

    const handleOutsideMouseDown = (event: MouseEvent): void => {
      const target = event.target as Node | null;
      const trigger = triggerRef.current;

      // A click on the trigger is its own toggle — let the trigger handle it.
      if (trigger && target && trigger.contains(target)) {
        return;
      }

      // A click inside the surface stays open.
      if (target && surface.contains(target)) {
        return;
      }

      // Outside the root: close, but leave focus where the user clicked.
      onRequestClose(false);
    };

    surface.addEventListener("keydown", handleKeyDown);
    document.addEventListener("mousedown", handleOutsideMouseDown);

    return () => {
      surface.removeEventListener("keydown", handleKeyDown);
      document.removeEventListener("mousedown", handleOutsideMouseDown);
    };
  }, [isOpen, surfaceRef, triggerRef, onRequestClose]);
}
