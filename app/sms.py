"""Отправка экстренного SMS через SMS Aero."""
import os

import httpx

from app import config

_SMSAERO_SEND_URL = "https://gate.smsaero.ru/v2/sms/send"
_SMSAERO_TIMEOUT = httpx.Timeout(10.0, connect=5.0, read=10.0)


def _debug_enabled() -> bool:
    return bool(os.getenv("SMS_DEBUG"))


def _debug_log(message: str) -> None:
    if _debug_enabled():
        print(f"[sms] {message}")


def _normalize_phone(phone: str) -> str:
    if phone.startswith("+"):
        return phone[1:]
    return phone


async def send_alert_sms(phone: str, message: str) -> bool:
    """Отправляет SMS через SMS Aero и возвращает результат запроса."""
    email = config.SMSAERO_EMAIL
    api_key = config.SMSAERO_API_KEY
    sign = config.SMSAERO_SIGN.strip() or "SMS Aero"
    normalized_phone = _normalize_phone(phone)

    _debug_log(
        "request "
        f"email_present={bool(email)} "
        f"api_key_len={len(api_key)} "
        f"phone={normalized_phone} "
        f"message={message!r}"
    )

    if not email or not api_key:
        return False

    params: dict[str, str] = {
        "number": normalized_phone,
        "text": message,
        "sign": sign,
    }

    try:
        async with httpx.AsyncClient(timeout=_SMSAERO_TIMEOUT, auth=(email, api_key)) as client:
            response = await client.get(_SMSAERO_SEND_URL, params=params)
    except httpx.TransportError:
        return False

    _debug_log(f"response.status_code={response.status_code}")
    _debug_log(f"response.text={response.text}")

    try:
        data = response.json()
    except ValueError:
        _debug_log("response.json()=<invalid json>")
        return False

    _debug_log(f"response.json()={data}")
    return isinstance(data, dict) and data.get("success") is True
