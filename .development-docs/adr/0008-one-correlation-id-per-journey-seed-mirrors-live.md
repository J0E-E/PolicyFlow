# 0008 — One correlation_id per journey; the seed mirrors live emission

A journey (lead → contact/household → opportunity → quote → application → policy) shares a
single `correlation_id` end-to-end — live conversion already propagates the lead's id, and
the baseline seed must produce the same shape (its per-chain fresh correlation ids are
replaced by the journey's conversion correlation id). Renewals deliberately fork a fresh
`correlation_id`; their causal parentage is the `opportunity.source_policy_id` row fact,
not the envelope. Source: tdd-p2.5-timeline-correlation-trace.md §6 D6.
