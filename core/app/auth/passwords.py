"""Password hashing helpers built directly on the maintained `bcrypt` library.

We call `bcrypt` directly rather than going through `passlib`. `passlib` was
last released in 2020 and is unmaintained: its bcrypt backend reads a version
attribute that modern `bcrypt` removed, which produces a noisy error and a
mis-detected backend (the "passlib/bcrypt version trap"). Calling `bcrypt`
directly behind this helper boundary sidesteps the trap entirely, and the
round-trip tests fail loudly on any bad install.

Bcrypt only considers the first 72 bytes of a password. The pinned bcrypt
(5.0.0) does NOT silently truncate longer input: `bcrypt.hashpw` raises
`ValueError("password cannot be longer than 72 bytes, ...")`. Seed and demo
passwords in this project are short, so this is a documented boundary rather
than something we work around here.
"""

import bcrypt


def hash_password(plain_text_password: str) -> str:
    """Hash a plaintext password with bcrypt and a fresh per-call salt.

    Returns the bcrypt hash as a `str` so callers and the database can store a
    plain string. Raises `ValueError` if the password is longer than 72 bytes.
    """
    hashed_bytes = bcrypt.hashpw(
        plain_text_password.encode("utf-8"), bcrypt.gensalt()
    )
    return hashed_bytes.decode("utf-8")


def verify_password(plain_text_password: str, stored_hash: str) -> bool:
    """Return whether the plaintext password matches the stored bcrypt hash.

    A malformed or corrupt stored hash makes `bcrypt.checkpw` raise
    `ValueError`; we catch it and return `False` so a bad hash reads as "does
    not match" rather than surfacing as a 500.
    """
    try:
        return bcrypt.checkpw(
            plain_text_password.encode("utf-8"), stored_hash.encode("utf-8")
        )
    except ValueError:
        return False
