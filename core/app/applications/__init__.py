"""The application lifecycle (P2.3) — the Draft → Submitted → decided machine.

`state.py` is the pure, framework-free state machine: the single source of truth
for which application status moves are legal, mirroring `app.leads.state` /
`app.opportunities.state`. The DB table, the select/submit/decision actions, and
the endpoints land in later P2.3 epics on top of this machine.
"""
