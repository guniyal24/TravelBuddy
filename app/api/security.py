"""Password hashing and JWT helpers."""
from datetime import UTC, datetime, timedelta

import bcrypt
from jose import JWTError, jwt

BCRYPT_MAX_BYTES = 72  # bcrypt ignores everything past 72 bytes


def _pw_bytes(password: str) -> bytes:
    return password.encode("utf-8")[:BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_pw_bytes(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_pw_bytes(plain), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(
    data: dict, secret_key: str, algorithm: str = "HS256", expires_minutes: int = 30
) -> str:
    payload = data.copy()
    payload["exp"] = datetime.now(UTC) + timedelta(minutes=expires_minutes)
    return jwt.encode(payload, secret_key, algorithm=algorithm)


def decode_token(token: str, secret_key: str, algorithm: str = "HS256") -> dict | None:
    """Return the payload, or None if the token is invalid or expired."""
    try:
        return jwt.decode(token, secret_key, algorithms=[algorithm])
    except JWTError:
        return None
