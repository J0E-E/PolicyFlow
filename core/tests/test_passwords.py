"""Unit tests for the bcrypt-backed password hashing helper.

Pure unit tests — no DB, no Docker — matching the no-Docker style of
`test_models.py` and `test_db.py`. They prove the round-trip works, that wrong
passwords are rejected, that each hash carries a random salt, that the hash has
the expected bcrypt shape (the loud guard against a broken/mis-detected bcrypt
install), and that a malformed stored hash reads as "no match" rather than
raising.
"""

from app.auth.passwords import hash_password, verify_password


def test_round_trip_password_verifies():
    """A password verifies against its own freshly-computed hash."""
    password = "correct horse battery staple"

    assert verify_password(password, hash_password(password)) is True


def test_wrong_password_is_rejected():
    """A different password does not verify against the stored hash."""
    stored_hash = hash_password("correct horse battery staple")

    assert verify_password("wrong password", stored_hash) is False


def test_salt_is_random_yet_both_hashes_verify():
    """Hashing the same password twice yields two different hashes that both verify."""
    password = "correct horse battery staple"

    first_hash = hash_password(password)
    second_hash = hash_password(password)

    assert first_hash != second_hash
    assert verify_password(password, first_hash) is True
    assert verify_password(password, second_hash) is True


def test_hash_has_expected_bcrypt_shape():
    """The hash is a non-empty `str` starting with the bcrypt `$2b$` marker.

    This is the loud failure the epic asks for: a broken or mis-detected bcrypt
    install fails this assertion instead of silently degrading.
    """
    stored_hash = hash_password("correct horse battery staple")

    assert isinstance(stored_hash, str)
    assert stored_hash.startswith("$2b$")


def test_malformed_stored_hash_returns_false_not_an_exception():
    """A corrupt stored hash reads as "does not match" rather than raising."""
    assert verify_password("anything", "not-a-real-hash") is False
