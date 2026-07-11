"""Простая HMAC-аутентификация без JWT."""
from __future__ import annotations

import base64
import hashlib
import hmac

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import APP_SECRET
from app.database import get_db
from app.models import User

bearer_scheme = HTTPBearer(auto_error=False)


def _token_signature(device_id: str) -> str:
    digest = hmac.HMAC(
        APP_SECRET.encode("utf-8"),
        msg=device_id.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def create_token(device_id: str) -> str:
    """Возвращает простой подписанный токен для device_id."""
    signature = _token_signature(device_id)
    return f"{device_id}.{signature}"


def verify_token(token: str) -> str | None:
    """Проверяет подпись токена и возвращает device_id."""
    if not token or "." not in token:
        return None

    device_id, signature = token.rsplit(".", 1)
    if not device_id or not signature:
        return None

    expected_signature = _token_signature(device_id)
    if not hmac.compare_digest(signature, expected_signature):
        return None

    return device_id


def get_user_by_token(token: str, db: Session) -> User | None:
    """Возвращает пользователя по токену или None."""
    device_id = verify_token(token)
    if device_id is None:
        return None

    user = db.query(User).filter(User.device_id == device_id).first()
    if user is None or user.token != token:
        return None

    return user


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Достаёт текущего пользователя из Bearer-токена."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )

    user = get_user_by_token(credentials.credentials, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found for token",
        )

    return user
