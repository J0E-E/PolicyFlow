import { NavLink } from "react-router-dom";
import type { NavSection } from "./navSections.ts";

interface NavItemProperties {
  /** Required base id; every rendered element derives a unique id from it. */
  id: string;
  /** The section this item renders (label, icon, live-or-inert flag, route). */
  section: NavSection;
}

// One row in the left-nav rail. Two shapes from the same section model:
//
//   LIVE  (section.comingLater === false) — a react-router NavLink to the section's
//         route. When that route is active it carries the --primary active marker
//         and `aria-current="page"` (Guide §4 "Active item uses a --primary marker").
//         Only "Demo home" is live in P1.6.
//
//   INERT (section.comingLater === true) — a non-link <span> with aria-disabled and
//         a "Coming in a later step" hint, so the section is announced as
//         present-but-unavailable rather than silently missing (Guide §7) — and is
//         never a dead link. This mirrors the masthead's inert-affordance pattern
//         (the disabled bell / "How it's built" placeholder).
//
// The icon is rendered aria-hidden; the text label carries the meaning (Guide §7 —
// never by icon/color alone). Every element gets a unique descriptive id (CLAUDE.md).
export default function NavItem({ id, section }: NavItemProperties) {
  const { label, icon: Icon, comingLater, to } = section;

  // Live item: a real NavLink. react-router sets aria-current + the active class
  // when its route matches, which paints the --primary marker.
  if (!comingLater && to) {
    return (
      <NavLink
        id={id}
        to={to}
        end
        className={({ isActive }) =>
          isActive ? "nav-item nav-item-link nav-item-active" : "nav-item nav-item-link"
        }
      >
        <span id={`${id}-icon`} className="nav-item-icon" aria-hidden="true">
          <Icon width={18} height={18} />
        </span>
        <span id={`${id}-label`} className="nav-item-label">
          {label}
        </span>
      </NavLink>
    );
  }

  // Inert item: a disabled, non-link row with an accessible name and a coming-later
  // hint. The hint id is wired as the item's description so assistive tech reads
  // "<label>, Coming in a later step, dimmed".
  return (
    <span
      id={id}
      className="nav-item nav-item-inert"
      aria-disabled="true"
      aria-describedby={`${id}-hint`}
    >
      <span id={`${id}-icon`} className="nav-item-icon" aria-hidden="true">
        <Icon width={18} height={18} />
      </span>
      <span id={`${id}-label`} className="nav-item-label">
        {label}
      </span>
      <span id={`${id}-hint`} className="nav-item-hint">
        Coming in a later step
      </span>
    </span>
  );
}
