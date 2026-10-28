import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_hasher = PasswordHasher()
ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


class TokenError(Exception):
    pass


def create_token(
    secret: str, user_id: str, kind: str, ttl: timedelta, jti: str | None = None
) -> tuple[str, str, datetime]:
    now = datetime.now(UTC)
    expires = now + ttl
    token_id = jti or uuid.uuid4().hex
    payload = {"sub": user_id, "type": kind, "jti": token_id, "iat": now, "exp": expires}
    return jwt.encode(payload, secret, algorithm=ALGORITHM), token_id, expires


def decode_token(secret: str, token: str, expected_kind: str) -> dict[str, Any]:
    try:
        payload: dict[str, Any] = jwt.decode(token, secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise TokenError("invalid token") from exc
    if payload.get("type") != expected_kind:
        raise TokenError("wrong token type")
    return payload
