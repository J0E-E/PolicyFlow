"""The `pii_demo` HTTP surface: the masked write/read demonstrator (Epic 10).

This package wires the PII building blocks the earlier P1.3 epics built in
isolation — field encryption + blind indexing (`pii/service.py`), per-tenant key
resolution (`pii/keys.py`), the pure maskers + `age_band_for` (`pii/masking.py`),
value normalization (`pii/crypto.py`), and the `PiiDemoRecord` model — into the
first real write/read path over HTTP. It adds no new crypto, masking, or scoping
logic of its own; it only composes those pieces, exactly as the auth and tenant
routers compose theirs.

The demonstrated contract is "encrypt on write, mask on read": create encrypts
each PII field, computes blind indexes, and derives the plaintext `age_band`; read
decrypts in-process and returns only the masked display strings. Every route is
tenant-scoped via `get_tenant_db`, so a caller can only ever read or write their
own tenant's records.
"""
