"""Argon2id password hashes. Demo parameters, still a real password hash."""

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError

# OWASP's minimum memory profile. Enough for a synthetic demo, fast enough to seed.
_hasher = PasswordHasher(time_cost=2, memory_cost=19_456, parallelism=1)
_dummy: str | None = None


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, password)
    except (VerifyMismatchError, VerificationError):
        return False


def dummy_hash() -> str:
    """A hash to verify against when the username does not exist, so the two paths take similar time."""
    global _dummy
    if _dummy is None:
        _dummy = hash_password("synthetic-demo-dummy")
    return _dummy
