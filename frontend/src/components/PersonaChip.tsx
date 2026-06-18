import type { ReactNode } from "react";
import type { Role } from "../api";

interface PersonaChipProperties {
  /** Required so the rendered chip button is uniquely targetable (CLAUDE.md).
   *  The label span is `${id}-label`; the decorative icon is `${id}-icon`. */
  id: string;
  /** The persona this chip selects — drives the per-role accent color class. */
  role: Role;
  /** The human-readable persona name (e.g. "Tenant Admin"), the always-present
   *  text that conveys meaning (Guide §7 — never by icon/color alone). */
  label: string;
  /** The persona glyph, rendered `aria-hidden` (decoration only). */
  icon: ReactNode;
  /** True when this chip is the active persona — marked `aria-pressed` and
   *  short-circuited (the active chip is a no-op when clicked). */
  isActive: boolean;
  /** True while a switch is in flight — every chip disables so a second switch
   *  cannot start mid-flight. */
  isPending: boolean;
  /** Called with this chip's role when the visitor selects it. */
  onSelect: (role: Role) => void;
}

// One persona chip in the role switcher (Guide §2.4, §6.7 — personas as annotated
// chips: accent rule + name + glyph). A real `<button>` so it is keyboard- and
// screen-reader-operable for free. Each chip carries a per-role modifier class
// (`persona-chip-<role>`) that colors it from its OWN named persona ramp
// (`--persona-<role>-accent` / `-container` / `-on-container`), so all four
// accents are visible at rest — the switcher is a palette of choices, not a
// single themed indicator. The active chip is marked `aria-pressed="true"`.
//
// Presentational only: the home-tenant memory, the in-flight/error state, and the
// active-chip no-op all live in the parent RoleSwitcher. Styling lives in
// styles/persona-chip.css; the role string (underscores in `tenant_admin` /
// `read_only`) is a valid CSS class fragment.
export default function PersonaChip({
  id,
  role,
  label,
  icon,
  isActive,
  isPending,
  onSelect,
}: PersonaChipProperties) {
  return (
    <button
      id={id}
      type="button"
      className={`persona-chip persona-chip-${role}`}
      aria-pressed={isActive}
      disabled={isPending}
      onClick={() => onSelect(role)}
    >
      <span id={`${id}-icon`} className="persona-chip-icon" aria-hidden="true">
        {icon}
      </span>
      <span id={`${id}-label`} className="persona-chip-label">
        {label}
      </span>
    </button>
  );
}
