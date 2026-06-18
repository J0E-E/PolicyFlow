import type { Role } from "../api";
import { ROLE_LABELS } from "./roleLabels.ts";

interface PersonaIndicatorProperties {
  /** Required so the rendered chip is uniquely targetable (CLAUDE.md). */
  id: string;
  /** The active persona — selects both the label and the accent (via the
   *  ancestor `[data-persona]` scope the theming effect sets). */
  role: Role;
}

// A static chip in the masthead naming the active persona (Guide §2.4 — persona
// accent applied to role chrome only). It reads the persona accent tokens
// (`--persona-accent-container` / `--persona-on-accent-container`), which the
// theming effect's `[data-persona]` scope resolves to the right ramp, so flipping
// roles re-colors it for free. Kept deliberately small and non-interactive:
// Epic 11 turns this into the interactive role switcher (the four personas as
// selectable chips with the ~200ms accent animation).
export default function PersonaIndicator({
  id,
  role,
}: PersonaIndicatorProperties) {
  return (
    <span id={id} className="persona-indicator">
      <span id={`${id}-label`} className="persona-indicator-label">
        {ROLE_LABELS[role]}
      </span>
    </span>
  );
}
