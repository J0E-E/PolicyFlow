"""Policy issuance (P2.3) — the issued-policy domain.

`service.py` holds `issue_policy` (the approve-path auto-issuance: create the policy
row with a deterministic human-readable number, emit `policy.created`, and advance
the opportunity to *Policy Active*) and the `policy_number` helper. `read.py` holds
the policy wire shape for the agent-workspace policy view.
"""
