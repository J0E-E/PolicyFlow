"""The `tenant` package: the guarded tenant-config HTTP surface.

Holds the Tenant-Admin-only `GET /api/tenant/config` route — the first endpoint
that proves the RBAC capability matrix end-to-end over real HTTP. It adds no new
auth logic; it composes the pieces the auth epics already built.
"""
