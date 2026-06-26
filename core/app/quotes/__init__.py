"""The carrier-quote round-trip (P2.3) — request, generate, poll.

`service.py` holds the two halves of the round-trip: `request_quotes` (the
request-side action that writes a `quote_requests` row and enqueues
`quote.requested` on the caller's transaction) and `complete_quote_request` (the
non-terminal `carrier.quote` consumer's effect — generate the options from the
registry catalog, write the `quotes` rows, mark the request completed, and enqueue
`quote.completed`).
"""
