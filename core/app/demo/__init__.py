"""The demo HTTP surface: pre-login, registry-backed reads for the demo shell.

P1.6 turns the placeholder app into a signed-in demo. The surfaces here run
*before* anyone signs in, so they are public and touch no database and no
personal data — they read only the in-memory tenant registry.
"""
