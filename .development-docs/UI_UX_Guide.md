# PolicyFlow — UI/UX Guide

> The design source of truth. CLAUDE.md directs every session to consult this before
> adding or changing frontend UI. Keep it practical: tokens, components, layout, and the
> PolicyFlow-specific UX patterns — enough to build consistently.

**Foundation:** Material Design 3 (MD3) token model and component semantics.
**Aesthetic:** **"Ledger & Ink"** — a beautifully typeset operational document system.
Insurance is a paper industry: policies, ledgers, ACORD forms, underwriting tables. The app
is light warm paper with iron-gall ink text, hairline rules, stamp-like status tags, and a
Clarendon display face that descends from 19th-century insurance certificates. Technical
surfaces (event timelines, traces, payloads, outbox, DLQ) invert to deep warm-ink console
panels — the engineering showcase is the only dark thing on screen, so it reads as the star
of every page. The whole must read as a serious operational platform for a regulated
industry: calm, credible, crafted.

**Anti-template guardrails — what this is explicitly *not*:** no dark chrome outside ink
consoles, no near-black-blue, no Inter or JetBrains Mono, no gradients, no glassmorphism or
backdrop blur, no glow shadows, no rounded-xl, no pill chips. If a change reintroduces one of
these it is wrong, even if it looks fine in isolation.

---

## 1. Design Principles

1. **Legible engineering.** The app explains itself (explainers, Simulated badges, "How it's
   built"). The UI must make the *real-vs-simulated* boundary and *which persona you are*
   unmistakable at a glance. Visual clarity is a product requirement here, not polish.
2. **Calm by default, loud on signal.** Neutral paper carries the work. Color is reserved for
   identity (tenant/persona), state (pending/success/failure), and risk (PII, ops actions).
3. **Async is visible.** Event-driven processing is the showcase — pending, enriching, retrying,
   and DLQ states are first-class visual states, never silent.
4. **Two-register color law.** Identity colors (tenant brand, persona accents) are deep and
   matte and never animate or signal state. State colors are the only hues that pulse, fill
   status tags, or mark success/failure. No tenant, persona, or state hue may sit within ~30°
   of a hue owned by another axis — check §2 before introducing any new color.
5. **Paper leads, ink shows the machine.** The app is light paper. Dark surfaces exist only as
   the bounded ink consoles (§2.1) reserved for machine views — which is exactly what makes
   the event-driven showcase the visual protagonist of every screen.
6. **One element, one `id`.** Every rendered element gets a unique, descriptive `id`
   (see CLAUDE.md → Frontend HTML IDs). This guide assumes that rule throughout.
7. **Small components.** Prefer many focused components over few large ones (see CLAUDE.md →
   React Philosophy).

---

## 2. Color System

Two identity axes are layered, not merged:

- **Tenant brand** → drives `primary` (the dominant theme). Seed-configurable; the two tenants
  must look visibly different.
- **Persona accent** → a separate semantic token applied only to **role chrome** (role
  switcher, the persona indicator, persona-scoped affordances). Flipping roles is unmistakable
  without overriding tenant identity.
- **Exception — Platform Admin** operates *outside* tenant scope. The masthead inverts to
  `--surface-ink`, tenant brand drains from the chrome (enforced in tokens, see §2.4), and the
  ops accent takes over — "you've left tenant context" is signaled structurally, not just by hue.

### 2.1 Paper & ink surfaces (light-first, theme-independent)

```css
:root {
  /* Surfaces — warm paper, layered by rule and tint, not glow */
  --surface-0: #F2EFE9;   /* app canvas — bond paper                    */
  --surface-1: #F9F7F2;   /* page panels                                */
  --surface-2: #FFFFFF;   /* cards, sheets                              */
  --surface-3: #F6F3EC;   /* hover wash, selected rows                  */
  --surface-4: #FFFFFF;   /* menus, dialogs — border + shadow, not tint */

  /* Inverted ink console — machine surfaces ONLY (see list below) */
  --surface-ink:        #23211C;  /* iron-gall ink — warm, never blue   */
  --surface-ink-raised: #2E2B25;  /* hover / raised rows on ink         */
  --on-ink:             #EFEAE0;  /* paper-toned text on ink            */
  --on-ink-variant:     #A9A294;  /* secondary text on ink              */
  --outline-ink:        #3E3A31;  /* hairlines on ink                   */

  /* Lines & text */
  --outline:            #DDD8CB;  /* hairline rules, borders, dividers  */
  --outline-strong:     #545044;  /* focused field borders              */
  --on-surface:         #21201A;  /* primary text — warm ink            */
  --on-surface-variant: #5C594F;  /* secondary text, labels, placeholders */
  --on-surface-muted:   #8B877A;  /* DISABLED text only — never placeholders */
}
```

The **ink console is not a dark theme** — it is a component register limited to an enumerated
set of machine surfaces: the per-record event timeline, the correlation trace view, the
payload/field-mapping viewer, the outbox raw view, and the DLQ. Everything else is paper.
A full dark theme is a future addition — author components against tokens, not raw hex.

### 2.2 Semantic state colors (theme-independent)

States are deep "document inks" that pass AA as text on white, each with a tint container:

```css
:root {
  --state-success: #1E6F50;  --state-success-container: #DFEFE5;
  --state-pending: #2C5FA8;  --state-pending-container: #DFE9F6;  /* enriching, quoting, retrying */
  --state-warning: #8A5A00;  --state-warning-container: #F6E8C8;  /* cautions, Simulated stamp    */
  --state-error:   #A8222B;  --state-error-container:   #F9E2E0;  /* failures, declined, DLQ      */

  /* State brights — used ONLY on --surface-ink consoles (all ≥4.5:1 on ink) */
  --state-success-on-ink: #5BC48F;
  --state-pending-on-ink: #7FA9E8;
  --state-warning-on-ink: #D9A84E;
  --state-error-on-ink:   #E8707A;
}
```

- **Cobalt belongs exclusively to `pending`.** No persona or tenant may use a blue near it.
- **There is no `--state-info` hue.** Informational tags are deliberately neutral: `--surface-3`
  background, `--on-surface-variant` text, plus an icon. Information is not a signal.
- Calibrate the four on-ink brights to roughly equal perceived luminance — they should read
  as one coherent set of indicator lamps inside consoles.

### 2.3 Tenant brand tokens (seed-driven, set per tenant at runtime)

Seed config supplies each tenant's brand; the app sets these on a `data-tenant` scope.
Provide a tonal ramp per MD3. Seeds were chosen warm-vs-cool so the same screen reads as a
different tenant instantly (a demo requirement) — and at ≥30° hue distance from every state
and persona color (the §1.4 law).

| Token | Sunshine Senior Benefits | Florida Family Planning |
|---|---|---|
| `--primary` | `#9C4A1E` (sun-baked terracotta, ~6.1:1 on white) | `#0F6A72` (Gulf petrol, ~6.3:1 on white) |
| `--on-primary` | `#FFF8F3` | `#F2FAFA` |
| `--primary-container` | `#F6E2D4` | `#D6ECEA` |
| `--on-primary-container` | `#5C2A10` | `#07343A` |

Rules for any future seed value: the `primary`/`on-primary` pair must pass AA on paper
surfaces; the hue must keep ~30° distance from all `--state-*` and persona hues; the seed
supplies a ramp (per theme, once a dark theme exists), never a single hex. Brand appears in
the masthead wordmark and seal mark, the **3px letterhead rule** under the top bar, the
active-nav marker, primary buttons, and section rules — never on status tags.

### 2.4 Persona accent tokens

Applied to role chrome only (see §2 exception for Platform Admin). The persona axis is
reframed as **annotation colors** — the hands that write in the ledger:

| Persona | Accent ramp | Chrome treatment | Rationale |
|---|---|---|---|
| **Agent** | `#21201A` (the ink itself); container `#EAE7E0` | Filled ink role chip with paper text — the default working hand carries no borrowed hue | Frees cobalt to mean only "pending"; default chrome stays calm |
| **Tenant Admin** | `#6442B0` registrar violet (~7.1:1 on white); container `#E9E1F7`, on-container `#3A2370` | Accent + small key glyph on the role chip | Elevated control within the tenant |
| **Read-Only** | `#7B7669` warm gray (~4.5:1 on white); container `#ECE9E2`, on-container `#4A463C` | Muted chrome + a persistent **"VIEW ONLY"** lock tag on *every* screen (the tag, not the gray, is what distinguishes it from disabled UI) | Intentionally low-energy — look, don't touch |
| **Platform Admin** | `#A12568` ops magenta (~7.0:1 on white); on-ink variant `#D169A6` (~4.8:1 on ink); container `#F7DEEB`, on-container `#5E1038` | **Masthead inverts to `--surface-ink`** with a 3px magenta rule and the label "PLATFORM OPERATIONS — OUTSIDE TENANT SCOPE"; tenant brand drains from chrome | Outside tenant scope; magenta is owned by no tenant and no state (orange is deliberately forfeited — it cannot coexist with a warm tenant and an ochre warning) |

Enforce the brand-drain in tokens, not convention:

```css
[data-persona="platform-admin"] {
  --primary: var(--on-surface-variant);   /* tenant color cannot render in ops mode */
  --primary-container: var(--surface-3);
}
```

When the role switcher changes persona, animate the accent transition (200ms) so the change is
felt, not just seen. RBAC is server-enforced regardless of chrome — the color is a cue, never
the gate.

### 2.5 Contrast (verified pairs, not a blanket claim)

| Pair | Ratio |
|---|---|
| `--on-surface` on `--surface-0` | ~14:1 |
| `--on-surface-variant` on `--surface-2` | ~7:1 |
| State inks on white (`success/pending/warning/error`) | 5.9–7.2:1 |
| State brights on `--surface-ink` | 4.5–7.5:1 |
| Tenant primaries with `--on-primary` | ~6.1 / ~6.3:1 |
| `--persona-platform-admin-on-ink` on inverted masthead | ~4.8:1 |

- `--on-surface-muted` is **disabled-only** (it does not meet 4.5:1 everywhere); placeholders
  use `--on-surface-variant`.
- Never convey state by color alone — every state color pairs with an icon and/or text label
  (critical for status stamps and the Simulated stamp).
- Run a color-vision-deficiency simulation (deuteranopia/protanopia) over the warm adjacencies
  (terracotta vs warning ochre vs error carmine) before locking seed changes; the documented
  Sunshine fallback is a deeper sepia `#8C4F22`.

### 2.6 Data visualization (dashboards: funnel, integration health, platform health)

- **Categorical series** (funnel stages, product lines) use desaturated "ink" tones that cannot
  be confused with signal colors: `#46508C` indigo, `#5A6E3A` moss, `#7C4A66` plum, `#44606E`
  slate, `#8A6248` clay, `#5C594F` charcoal.
- **Sequential intensity** (queue depth, throughput) is **ink density**: tints of `#21201A` at
  10 / 25 / 45 / 70 / 100% — more ink = more volume, on theme and hue-free.
- **Success/failure series** (integration health) reuse `--state-success` / `--state-error` so
  chart semantics match chip semantics.
- The funnel uses the tenant's display stage labels with counts in mono tabular figures.

---

## 3. Typography

A typeset-document voice: a regulated-forms grotesque for UI, a Clarendon for display, a
typewriter-heritage mono for machine identity.

```css
:root {
  --font-display: "Besley", "Georgia", serif;            /* Display/Headline/entity names ONLY */
  --font-ui:      "Public Sans", "Segoe UI", system-ui, sans-serif;
  --font-mono:    "IBM Plex Mono", "Consolas", ui-monospace, monospace;
}
body { font-variant-numeric: tabular-nums; }  /* ledger-grade numerals everywhere */
```

- **Public Sans** (Google Fonts) — designed for the U.S. Web Design System: the typeface of
  regulated government forms. Bureaucratic credibility Inter does not have.
- **Besley** (Google Fonts) — a revival of Robert Besley's 1845 Clarendon, the letterforms of
  Victorian insurance certificates and ledgers. **Hard limit:** Display, Headline, and entity
  names on detail pages, weight ≤ 600 — above that it tips into wanted-poster territory.
- **IBM Plex Mono** — typewriter heritage; all machine identity: `event_id`, `correlation_id`,
  external CRM record IDs, `__c` API names, payloads.

| Role | Size / Line / Weight / Face | Use |
|---|---|---|
| Display | 32 / 40 / 600 Besley | Landing hero only |
| Headline | 24 / 32 / 600 Besley | Page titles, entity names |
| Title | 18 / 24 / 600 Public Sans | Card headers, dialog titles |
| Body L | 16 / 24 / 400 | Default body |
| Body M | 14 / 20 / 400 | Dense tables, secondary text |
| Label | 13 / 16 / 500 | Buttons, field labels |
| **Stamp** | 11 / 16 / 700, uppercase, +0.8px tracking | Status tags, section overlines ("SECTION 4 — QUOTES"), the Simulated stamp |
| Mono | 13 / 20 / 400 | IDs, payloads, mappings, event traces |

**Data typography:** numeric columns right-aligned; currency with consistent precision; fixed-
width date format. Use mono **wherever a value is machine identity** — this reinforces the
engineering-transparency story.

---

## 4. Spacing, Radius, Elevation, Motion

```css
:root {
  /* 4px base spacing scale */
  --space-1: 4px;  --space-2: 8px;  --space-3: 12px; --space-4: 16px;
  --space-5: 24px; --space-6: 32px; --space-7: 48px; --space-8: 64px;

  /* Radius — near-square document geometry */
  --radius-sm: 2px;     /* stamp tags, inputs       */
  --radius-md: 4px;     /* buttons, cards           */
  --radius-lg: 6px;     /* dialogs, large panels    */
  --radius-full: 999px; /* avatars ONLY — no pills  */

  /* Elevation — paper lies flat; shadow is earned only by transient layers */
  --elevation-1: 0 1px 0 rgba(33,31,26,.05);      /* resting card crease (+ 1px --outline border) */
  --elevation-2: 0 2px 8px rgba(33,31,26,.10);    /* menus, popovers                              */
  --elevation-3: 0 16px 40px rgba(33,31,26,.18);  /* dialogs                                      */
  --scrim:       rgba(35,33,28,.45);

  /* Interaction state layers (MD3) & disabled */
  --state-layer-hover:   .08;   /* of --on-surface over the surface */
  --state-layer-pressed: .12;
  --disabled-content-opacity: .38;
  --disabled-container-opacity: .12;

  /* Table density */
  --row-height-comfortable: 52px;
  --row-height-dense:       44px;   /* lead lists, pipeline, audit log, DLQ — with Body M */

  /* Z-index scale */
  --z-nav: 10; --z-banner: 20; --z-stepper: 30;
  --z-popover: 40; --z-dialog: 50; --z-toast: 60;

  /* Motion */
  --motion-fast:     120ms;  /* hover, press            */
  --motion-standard: 200ms;  /* enter/exit, role swap   */
  --motion-slow:     320ms;  /* dialogs, panels         */
  --easing-standard: cubic-bezier(.2, 0, 0, 1);

  /* Focus ring — editorial, tenant-agnostic, always AA */
  --focus-ring-color: #21201A;       /* on ink consoles: var(--on-ink) */
  --focus-ring-width: 2px;
  --focus-ring-offset: 2px;
}
```

- **Structure comes from rules, not shadows:** 1px hairlines (`--outline`) divide and border;
  the signature **Oxford double rule** (2px ink + 2px gap + 1px hairline) sits under every page
  title and above table footers. Resting cards are flat bordered paper.
- **Grid:** 12-column, max content width ~1280px, gutters `--space-4`. App shell is a fixed left
  nav + top masthead; content scrolls. Chrome breathes (`--space-6`/`--space-7` around page
  headers) against dense, well-ruled tables — the contrast is the look.
- **Banner coexistence:** the session indicator lives as a masthead tag (§6.5), not a banner;
  the ops banner supersedes other banners. Banners never stack more than two deep.
- Respect `prefers-reduced-motion` — drop transitions to opacity-only; disable skeleton shimmer.

---

## 5. Core Components

Build on MD3 semantics. Each gets a unique `id`; interactive ones expose proper ARIA.

| Component | Spec |
|---|---|
| **Button** | Filled (primary action, `--primary`), Tonal (`--primary-container`), Outlined, Text. Height 40px, radius `--radius-md`, Label type. Pending state shows inline spinner + disabled. |
| **Card** | `--surface-2`, 1px `--outline` border, `--radius-md`, `--elevation-1`, `--space-4` padding. Header (Title) + body + optional footer actions. The standard container for entity summaries. |
| **Text field** | `--surface-2` fill, `--outline` border → `--outline-strong` border + focus ring on focus. Label above, helper/error below. Error uses `--state-error`. Placeholder uses `--on-surface-variant`. |
| **Stamp tag** | Replaces pill chips for status. Near-square (`--radius-sm`), Stamp type, icon + uppercase label, state-container background with state-ink foreground — reads as a rubber stamp on a document (APPROVED, DECLINED, ENRICHING…). Filter chips may keep `--radius-sm` tonal form; nothing is a pill. |
| **Dialog** | `--surface-4`, `--radius-lg`, `--elevation-3`, scrim `--scrim`. Title / content / actions. Used for conversion, duplicate resolution, PII reveal confirm, DLQ replay/discard. |
| **Banner** | Full-width contextual strip (ops mode, graceful-expiry notice). Left status icon + message + optional action. See §4 coexistence rule. |
| **Snackbar / toast** | `--surface-ink`, `--on-ink` text, `--radius-md`, bottom-left, `--z-toast`; paired with the `aria-live` region announcing async completions; auto-dismiss ~6s (persists on hover/focus; honors reduced motion). |
| **Skeleton** | `--surface-3` blocks matching final layout; shimmer disabled under `prefers-reduced-motion`. |
| **Empty state** | A calm framed ledger note: icon, one-line explanation (`--on-surface-variant`), optional CTA. Required for every table/list. Isolation-proof variant: see §6.8. |
| **Data table** | Sticky header (Stamp-type column heads), `--outline` row dividers (no zebra), sortable headers, numeric columns right-aligned tabular-nums, row hover `--surface-3`, `--row-height-dense` for operational lists. Empty/loading/error states required. |
| **Page header** | Breadcrumb (entity graph is deep: Lead → Contact → Household → Opportunity → …), Headline in Besley, status stamp tag, entity ID in mono, Oxford double rule beneath. |
| **Pagination** | Bottom-right of tables, Body M, 25/50 page sizes, keyboard operable. Required wherever seed data exceeds a page. |
| **Form validation** | Validate on blur; error summary at top on submit (focus moves to it); server errors mapped to fields; inline errors in `--state-error` with icon. |
| **Nav** | Left rail with section groups (Leads, Contacts, Households, Opportunities, Policies, Tasks, Dashboards, How it's built). Active item uses a `--primary` marker. Items are role-conditional: Audit Log (Tenant Admin, Read-Only), Outbox & integration health (Tenant Admin), Platform Health & DLQ (Platform Admin). |
| **Popover / margin note** | Explainer and Simulated-stamp surfaces (§6). White sheet, 1px border, 2px ink rule down the left edge — a printed margin note. |

---

## 6. PolicyFlow-Specific UX Patterns

These encode the requirements doc's showcase surfaces. They are **required UX**, not optional.

### 6.1 Async / pending states
Any event-driven step (enrichment, quote, CRM sync, retry) shows an explicit pending state:
a labeled stamp tag ("ENRICHING…", "REQUESTING QUOTES…", "SYNCING…") with spinner, plus the
live **per-record event timeline** — an inverted ink console card titled with a stamp overline
("EVENT TIMELINE"). Vertical hairline (`--outline-ink`) with tick markers per event; event
names in Public Sans; every `event_id`/`correlation_id` in mono `--on-ink-variant`; statuses
as on-ink bright stamp tags. Sidecar reactions indent under their parent event with mono
box-drawing connectors (`└─`) — trace output bound into a policy file. New rows slide in
200ms (opacity-only under reduced motion), updating live (poll/websocket). Never show a blank
or a final state before the event resolves.

### 6.2 Explainer affordance
An info-icon (`id="explainer-<surface>-icon"`) on every showcase surface opens a dismissible
margin-note popover with labeled small-caps sections: **PATTERN**, **HOW POLICYFLOW DOES IT**
(names the real mechanism — outbox, schema-per-tenant isolation, blind index, envelope encryption, per-consumer retry,
set in mono), **REAL VS SIMULATED**, and — where the requirements specify it — **CRM PARALLEL**
(the real-world CRM equivalent, API names like `ConvertedContactId`, `StageName`, `__c` in
mono). Renders identically for every role; never blocks the workflow.

### 6.3 "Simulated" stamp
A consistent rectangular stamp — flask icon + "SIMULATED" in Stamp type, `--state-warning` on
`--state-warning-container` (on ink consoles: `--state-warning-on-ink`) — echoing the SPECIMEN
stamp on sample banknotes. **Border law: the Simulated stamp always uses a 1px *dashed* border;
real warnings use solid** — "dashed = not yet real" can never be confused with an actual
warning even in the same hue family. Appears on every mocked integration surface (quotes,
enrichment, CRM records & sync activity, carrier decisions, outbox). Its popover is an
"official notice" card with three ruled small-caps sections: **WHAT IS MOCKED / WHAT IS REAL /
THE ADAPTER SEAM** (mechanism and adapter names in mono). The demo must never present a
simulated surface as real, nor a real mechanism as mock.

### 6.4 PII masking & reveal
PII renders masked by default (`•••-••-1234`, mono) with a lock glyph. For Agent/Tenant Admin
an **"Unseal · audited"** control sits inline — dashed underline + eye icon, deliberately
unlike any button (it is a sensitive action, and the audit cost is visible *before* the
click). Revealing opens a brief confirm styled as a short release form, fires the audited
`pii.revealed` event, then shows the value with an ochre marginal marker "revealed — audited"
carrying the event id in mono. Read-Only sees the mask with **no reveal control at all**.
Mock Medicare ID is always masked for everyone.

### 6.5 Session indicator & graceful expiry
A masthead date-stamp tag with a **live mono countdown**: `DEMO SESSION · 22:41 REMAINING`
(tabular figures tick), with an explainer popover (sandboxing model). Session-created records
carry a small "YOUR SESSION" marginal tag on lists/detail. Session-scoped overlays (e.g. a
seeded policy shown as *Renewal Due*) are explicitly labeled as overlays. Expired/unknown
sessions resolve to a friendly notice with one-click fresh session — never a raw 404/500.

### 6.6 Guided stepper
A persistent, dismissible **docket** — a numbered table-of-contents overlay (01–21) tracking
walkthrough progress with checkmarks in tenant `--primary`, hairline rules between steps,
"next step" prompts, deep links, and a "what you're seeing / how it's built" note per step
linking to the relevant explainer. Deep-links to the intake prefill row (§6.9).

### 6.7 Role switcher
A visible control to flip Agent / Tenant Admin / Read-Only / Platform Admin — persona entries
as annotated chips (accent rule + name + glyph per §2.4). On switch, animate the persona
accent (200ms). Selecting Platform Admin inverts the masthead to `--surface-ink` with the
magenta rule and "PLATFORM OPERATIONS — OUTSIDE TENANT SCOPE" label while tenant color drains
from the chrome (the `[data-persona]` override in §2.4). Make clear the switch changes
identity, not enforcement.

### 6.8 Tenant differentiation
On the same screens, the two tenants must differ in: brand color (§2.3), masthead wordmark +
seal mark, the 3px letterhead rule, product lines, pipeline stage labels, and CRM field
mappings. The isolation proof (records created in Tenant 1 absent in Tenant 2) is a
walkthrough beat — its empty state is a calm framed ledger note styled as information, never
error: *"No records here. The records you created belong to Sunshine Senior Benefits."* with
an explainer link to the schema-per-tenant / tenant-isolation explainer.

### 6.9 Intake prefill row
On the intake form itself (not the stepper): a row of four labeled specimen cards — **Typical
lead / Duplicate / Declined / Sync failure** — each a Tonal button with a one-line
expected-outcome sublabel and an explainer icon (§6.2) describing the magic input and
publish-time flag mechanism. The form's sections are numbered (01, 02, 03…) in the manner of
ACORD forms.

### 6.10 Field-mapping viewer
Walkthrough step 13's side-by-side: a three-column layout — internal record (paper card) →
mapping rules applied (rename, picklist translation, format transform, constant injection) →
resulting CRM-style payload (ink console, mono, `__c` names). The same record under each
tenant's mappings must produce visibly different payloads; a tenant switcher or paired view
makes the contrast one glance.

### 6.11 Correlation trace view
The end-to-end story of one lead: reuses the §6.1 timeline anatomy, grouped by
`correlation_id` (mono, prominent), spanning core events and every sidecar reaction across
the lifecycle. An ink console page section — the engineering centerpiece of the walkthrough's
final beats.

### 6.12 Notification center & outbox
Bell icon in the masthead opens a popover list (per user) of notifications with state icons
and timestamps. The **simulated outbox** page renders email payloads as typeset letters on
paper sheets — each carrying the Simulated stamp (§6.3) — listed per tenant with recipient,
subject, triggering event id in mono.

### 6.13 Landing & "How it's built"
The two editorial surfaces the hiring audience reads most carefully — the one place the
Besley display register and generous whitespace lead. Landing: orientation, tenant selection,
session creation. "How it's built": annotated architecture diagram (ink console), ER view,
workflow map, and an index of every showcase pattern as deep-link cards, plus repository and
author links.

### 6.14 Cross-sell prompt
On Household detail when coverage gaps exist: a framed ledger note per uncovered product line
("This household has no Long Term Care coverage") with a one-click "Create opportunity"
Tonal action. Information-toned, not alarm-toned.

---

## 7. Accessibility Baseline

- WCAG AA contrast per the verified pairs in §2.5; state never by color alone.
- Visible focus ring on every interactive element (`--focus-ring-*` tokens — ink on paper,
  paper-toned on ink consoles; never tenant-colored).
- Full keyboard operability; logical tab order; `aria-*` relationships use the element `id`s
  this project already mandates.
- Dialogs/popovers trap focus and restore it on close; `Esc` closes.
- Live regions (`aria-live="polite"`) announce async state changes (enrichment done, sync
  failed) — paired with the snackbar — so the async story is accessible too.
- Honor `prefers-reduced-motion` (opacity-only transitions, no shimmer).
- **QA passes before calling the demo done:** (1) AA check on *both* grounds — paper and ink
  console — for any component that renders on both; (2) hairlines and dashed borders at
  Windows 125% / 150% fractional scaling; (3) key walkthrough screens through an actual
  Zoom/Teams screen-share and a grayscale render; (4) CVD simulation over the warm
  adjacencies (§2.5).

---

## 8. How to use this guide

- **Building UI?** Pull from the tokens (§2–4) and components (§5); apply the PolicyFlow patterns
  (§6) for any showcase surface. Don't introduce raw hex/spacing outside the token set.
- **Adding any color?** Re-read the two-register law (§1.4) and the hue-distance rule first.
  Tempted by a gradient, glow, blur, or pill? See the anti-template guardrails in the header —
  the answer is no.
- **New persona/tenant color?** Edit §2.3 / §2.4 only — components consume the tokens.
- **Want to pressure-test it?** The `frontend-design` skill can generate a sample screen
  (e.g. a lead detail view or the event-timeline console) against these tokens; feed gaps back
  here.
