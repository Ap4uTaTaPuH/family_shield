"""Отправка data-only push через FCM HTTP v1 API."""
from __future__ import annotations

import json
import logging
import os
import time

import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account

logger = logging.getLogger(__name__)


def _mask_fcm_token(token: str | None) -> str:
    """Маскирует FCM-токен для логов: префикс 12 символов + длина.

    FCM-токен — полу-секрет (идентификатор устройства), полный токен нигде не логируется.
    Использовать во ВСЕХ логах, где встречается fcm_token.
    """
    if not token:
        return "<empty>"
    return f"{token[:12]}…(len={len(token)})"

FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
_TOKEN_REFRESH_SAFETY_SECONDS = 300
_cached_credentials: service_account.Credentials | None = None
_cached_project_id: str | None = None
_cached_access_token: str | None = None
_cached_access_token_expiry = 0.0


def _load_credentials() -> tuple[service_account.Credentials, str] | None:
    """Загружает service-account credentials и project_id из JSON."""
    global _cached_credentials, _cached_project_id

    if _cached_credentials is not None and _cached_project_id:
        return _cached_credentials, _cached_project_id

    from app.config import FCM_SERVICE_ACCOUNT_JSON

    if not FCM_SERVICE_ACCOUNT_JSON:
        logger.warning("FCM_SERVICE_ACCOUNT_JSON not set, FCM push disabled")
        return None

    if not os.path.exists(FCM_SERVICE_ACCOUNT_JSON):
        logger.warning("FCM service account file not found: %s", FCM_SERVICE_ACCOUNT_JSON)
        return None

    try:
        credentials = service_account.Credentials.from_service_account_file(
            FCM_SERVICE_ACCOUNT_JSON,
            scopes=[FCM_SCOPE],
        )
    except Exception:
        logger.exception("Failed to load FCM service account JSON")
        return None

    if not credentials.project_id:
        logger.error("FCM service account JSON has no project_id")
        return None

    _cached_credentials = credentials
    _cached_project_id = credentials.project_id
    return credentials, credentials.project_id


def _get_access_token() -> str | None:
    """Возвращает OAuth2 access_token для FCM v1, кэшируя его между push."""
    global _cached_access_token, _cached_access_token_expiry

    now = time.time()
    if _cached_access_token and now < _cached_access_token_expiry - _TOKEN_REFRESH_SAFETY_SECONDS:
        return _cached_access_token

    loaded = _load_credentials()
    if loaded is None:
        return None

    credentials, _ = loaded
    try:
        credentials.refresh(Request())
    except Exception:
        logger.exception("Failed to refresh FCM OAuth2 access token")
        return None

    if not credentials.token:
        logger.error("FCM OAuth2 access token is empty after refresh")
        return None

    _cached_access_token = credentials.token
    if credentials.expiry is not None:
        _cached_access_token_expiry = credentials.expiry.timestamp()
    else:
        _cached_access_token_expiry = now + 3300
    return _cached_access_token


async def send_fcm_push(fcm_token: str, call_id: str, title: str, body: str) -> bool:
    """Отправляет data-only push через FCM HTTP v1 API.

    Возвращает True при успехе, False при любой ошибке.
    Data-only (без поля notification) — onMessageReceived вызывается всегда,
    даже когда приложение убито.
    """
    if not fcm_token:
        logger.warning("send_fcm_push: empty fcm_token, skip")
        return False

    loaded = _load_credentials()
    if loaded is None:
        return False
    _, project_id = loaded

    access_token = _get_access_token()
    if not access_token:
        return False

    data_payload = {
        "type": "scam_alert",
        "call_id": call_id,
        "timestamp": str(int(time.time())),
        "title": title,
        "body": body,
    }
    body_json = {
        "message": {
            "token": fcm_token,
            "data": data_payload,
            "android": {
                "priority": "HIGH",
                "ttl": "60s",
            },
        }
    }
    body_for_log = {
        "message": {
            "token": _mask_fcm_token(fcm_token),
            "data": data_payload,
            "android": {
                "priority": "HIGH",
                "ttl": "60s",
            },
        }
    }

    logger.info("FCM v1 payload: %s", json.dumps(body_for_log, ensure_ascii=False))

    url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=utf-8",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, headers=headers, json=body_json)

        if response.status_code >= 400:
            logger.error(
                "FCM v1 error status=%s call_id=%s token=%s body=%s",
                response.status_code,
                call_id,
                _mask_fcm_token(fcm_token),
                response.text,
            )
            return False

        response_body = response.json()
        logger.info(
            "FCM push sent name=%s call_id=%s token=%s",
            response_body.get("name"),
            call_id,
            _mask_fcm_token(fcm_token),
        )
        return True

    except Exception:
        logger.exception(
            "FCM push failed call_id=%s token=%s",
            call_id,
            _mask_fcm_token(fcm_token),
        )
        return False
