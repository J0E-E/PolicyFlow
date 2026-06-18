import { Eye, Headset, Key, Server } from "iconoir-react";
import type { Role } from "../api";

// One decorative glyph per persona for the role-switcher chips (Guide §2.4 — the
// "small key glyph" on the Tenant Admin chip, and an accent + glyph per role on
// the others). The glyph is always rendered `aria-hidden`; the always-present
// text label is what conveys the persona (Guide §7 — never by icon/color alone),
// so the icon is pure decoration.
//
// Icons come from `iconoir-react` (a deliberate, recorded reversal of TDD
// Decision 6's "no icon system" — real iconography recurs across the whole phase:
// the live bell §6.12, explainer icons §6.2, the PII lock glyph, state icons on
// stamps, field-mapping markers). Export names verified against iconoir-react
// 7.11: `Headset`, `Eye`, `Server` exist as named; the plan's `KeyRound` does
// NOT exist in this package, so the Tenant Admin glyph uses the closest match
// `Key` — which is exactly the Guide §2.4 literal "key glyph".
//
// The map is keyed by the runtime role wire strings (snake_case) from
// `api/types.ts::Role`, so a chip looks its icon up by the same value the
// `[data-persona]` theming scope uses.
export const PERSONA_ICONS: Record<Role, typeof Headset> = {
  agent: Headset,
  tenant_admin: Key,
  read_only: Eye,
  platform_admin: Server,
};
