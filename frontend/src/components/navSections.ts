import {
  Community,
  Folder,
  GraphUp,
  HandCash,
  HomeSimple,
  JournalPage,
  ListSelect,
  Network,
  Server,
  Strategy,
  User,
} from "iconoir-react";
import type { Capability, Role } from "../api";

// The declarative model for the left-nav rail (Guide §4 — "Left rail with section
// groups … Active item uses a --primary marker. Items are role-conditional").
// This file holds no JSX (just data + an icon component reference per item), so it
// stays a clean Vite fast-refresh boundary, mirroring roleLabels.ts / personaIcons.ts.
// The rail components (LeftNav / NavItem) read this list, filter by each item's gate
// against the session, and render the survivors.
//
// Some sections are LIVE — "Demo home" links to /app and "Leads" links to
// /app/leads (P1.7, Epic 20), each carrying the active marker when current; every
// other section is shown INERT with a "coming in a later step" hint, so the rail
// previews the app's real structure honestly without any dead links. As later
// phases land a real surface, that item's `comingLater` flips to false and it
// gains a real route (P1.7 did this for Leads when the list landed).
//
// "How it's built" is deliberately OMITTED from this list: the masthead already
// carries that inert placeholder (Epic 21 wires it live), so listing it here too
// would show the same coming-later affordance twice. A documented deviation from
// the Guide §4 literal nav list.

// Iconoir export names verified against iconoir-react 7.11 (the Epic 11 lesson —
// `KeyRound` did not exist there; we only use names confirmed present). Icons are
// rendered aria-hidden; the text label is what conveys each section (Guide §7 —
// never by icon/color alone), so the icon is pure decoration.
type NavIcon = typeof HomeSimple;

/**
 * How a nav item earns its place in the rail. Exactly one form per item:
 *   - `{ always: true }`     — always shown (the one live "Demo home" item).
 *   - `{ capability }`       — shown when the session holds that capability.
 *   - `{ role }`             — shown when the active role matches exactly (used for
 *                              "Outbox & integration health", which has no clean
 *                              single capability — Tenant Admin only).
 */
export type NavGate =
  | { always: true }
  | { capability: Capability }
  | { role: Role };

/** One section in the left-nav model. */
export interface NavSection {
  /** Stable key — drives the rendered element ids (`left-nav-item-<key>`). */
  key: string;
  /** The human label shown in the rail (carries the meaning; the icon is decorative). */
  label: string;
  /** The decorative iconoir glyph for the item (rendered aria-hidden). */
  icon: NavIcon;
  /** What admits the item into the rail for the current session. */
  gate: NavGate;
  /**
   * When true the item is inert — shown disabled with a "coming in a later step"
   * hint, never a link. The one live item ("Demo home") sets this false and is the
   * only real NavLink in the rail.
   */
  comingLater: boolean;
  /** The route the live item links to. Only set when `comingLater` is false. */
  to?: string;
}

// Order follows the Guide §4 nav list, with "Demo home" leading as the live entry
// point and the gated future sections after it. The gate determines who sees what:
//   Agent          = the 6 CRM sections + Dashboards
//   Tenant Admin   = + Audit Log + Outbox & integration health
//   Read-Only      = CRM sections + Dashboards + Audit Log
//   Platform Admin = ONLY Platform Health & DLQ (no tenant scope, no CRM caps)
// Every persona also gets the always-shown "Demo home".
export const NAV_SECTIONS: NavSection[] = [
  {
    key: "demo-home",
    label: "Demo home",
    icon: HomeSimple,
    gate: { always: true },
    comingLater: false,
    to: "/app",
  },
  {
    key: "leads",
    label: "Leads",
    icon: Strategy,
    gate: { capability: "view_tenant_records" },
    // Live as of P1.7 (Epic 20) — the leads list + queue + claim surface landed,
    // so this item links to /app/leads (the second live rail entry after Demo home).
    comingLater: false,
    to: "/app/leads",
  },
  {
    key: "contacts",
    label: "Contacts",
    icon: User,
    gate: { capability: "view_tenant_records" },
    comingLater: true,
  },
  {
    key: "households",
    label: "Households",
    icon: Community,
    gate: { capability: "view_tenant_records" },
    comingLater: true,
  },
  {
    key: "opportunities",
    label: "Opportunities",
    icon: HandCash,
    gate: { capability: "view_tenant_records" },
    // Live as of P2.2 (Epic 2) — the pipeline board landed, so this item links to
    // /app/opportunities (the third live rail entry after Demo home and Leads).
    comingLater: false,
    to: "/app/opportunities",
  },
  {
    key: "policies",
    label: "Policies",
    icon: Folder,
    gate: { capability: "view_tenant_records" },
    comingLater: true,
  },
  {
    key: "tasks",
    label: "Tasks",
    icon: ListSelect,
    gate: { capability: "view_tenant_records" },
    // Live as of P2.4 (Epic 11) — the task queue landed, so this item links to
    // /app/tasks (the fourth live rail entry after Demo home, Leads, and
    // Opportunities).
    comingLater: false,
    to: "/app/tasks",
  },
  {
    key: "dashboards",
    label: "Dashboards",
    icon: GraphUp,
    gate: { capability: "view_dashboards" },
    comingLater: true,
  },
  {
    key: "audit-log",
    label: "Audit Log",
    icon: JournalPage,
    gate: { capability: "view_audit_logs" },
    comingLater: true,
  },
  {
    key: "outbox",
    label: "Outbox & integration health",
    icon: Network,
    // No clean single capability for the outbox view — it is the Tenant Admin's
    // operational surface, so gate on the role directly (settled at plan time).
    gate: { role: "tenant_admin" },
    comingLater: true,
  },
  {
    key: "platform-health",
    label: "Platform Health & DLQ",
    icon: Server,
    gate: { capability: "platform_health_demo_controls" },
    comingLater: true,
  },
];

/**
 * Whether a section's gate admits it for the active session. Fail-closed: a
 * capability/role the session does not hold keeps the item out of the rail.
 */
export function isSectionVisible(
  gate: NavGate,
  role: Role,
  capabilities: Capability[],
): boolean {
  if ("always" in gate) {
    return true;
  }
  if ("role" in gate) {
    return role === gate.role;
  }
  return capabilities.includes(gate.capability);
}
