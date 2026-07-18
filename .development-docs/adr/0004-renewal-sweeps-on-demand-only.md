# ADR 0004 — Renewal sweeps are on-demand-only; the button bypasses the seasonal calendar

Sweeps fire only via the Platform-Admin buttons — no background renewal loop and no demo clock. The
schedule semantics (AEP seasonal Oct 15–Dec 7 window, 60-day anniversary, life never) live as pure,
unit-tested predicates that no in-session firing observes (BRD FR4). The on-demand AEP button
generates for every active MA policy regardless of the real date (today falls outside the window),
because a background job auto-mutating session/baseline data would be nondeterministic and threaten
the byte-identical-seed guarantee. Chosen over wiring a `demo_lifecycle`-style renewal loop and over
introducing a cross-cutting frozen demo "today".
Source: tdd-P2.4 §6, brd-P2.4 §6 FR4
