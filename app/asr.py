"""ASR-клиент недели 3: SaluteSpeech -> fallback Neuro.net.

Это каркас интеграции, а не финальная боевая реализация.
Реальные endpoint/headers/body нужно сверить по официальной документации.
"""
import io
import json
import logging
import time
import uuid
import wave
from typing import Any

import httpx

from app import config

logger = logging.getLogger(__name__)

_ASR_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
_SALUTE_SPEECH_DOCS_URL = "https://developers.sber.ru/docs/ru/salutespeech"
_NEURO_NET_DOCS_URL = "https://neuro.net/docs"
_salute_token_cache: dict[str, object] = {"token": "", "expires_at": 0}


def _extract_text_from_response(data: Any) -> str:
    """Пытается достать текст из типичных ASR-ответов без привязки к одному API."""
    if isinstance(data, str):
        return data.strip()

    if isinstance(data, dict):
        for key in ("text", "transcript", "result", "normalized_text"):
            value = data.get(key)
            if isinstance(value, str):
                return value.strip()

        results = data.get("results") or data.get("result")
        if isinstance(results, list):
            parts: list[str] = []
            for item in results:
                if isinstance(item, dict):
                    for key in ("text", "transcript", "normalized_text"):
                        value = item.get(key)
                        if isinstance(value, str) and value.strip():
                            parts.append(value.strip())
                            break
            if parts:
                return " ".join(parts).strip()

    return ""


def _pcm_to_wav_bytes(pcm_bytes: bytes) -> bytes:
    """Оборачивает raw PCM в минимальный WAV-заголовок для ASR API, если нужно."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(config.PCM_SAMPLE_RATE)
        wav_file.writeframes(pcm_bytes)
    return buffer.getvalue()


async def _get_salute_access_token() -> str:
    now = time.time()
    cached_token = str(_salute_token_cache.get("token", ""))
    cached_expires_at = int(_salute_token_cache.get("expires_at", 0) or 0)
    if cached_token and cached_expires_at > now + 60:
        return cached_token

    headers = {
        "Authorization": f"Basic {config.SALUTE_SPEECH_API_KEY}",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "RqUID": str(uuid.uuid4()),
    }
    data = f"scope={config.SALUTE_SPEECH_SCOPE}"

    async with httpx.AsyncClient(timeout=_ASR_TIMEOUT, verify=False) as client:
        response = await client.post(
            config.SALUTE_SPEECH_AUTH_URL,
            headers=headers,
            content=data,
        )
        response.raise_for_status()

    payload = response.json()
    token = str(payload["access_token"])
    _salute_token_cache["token"] = token
    _salute_token_cache["expires_at"] = payload.get("expires_at", now + 1700)
    return token


async def _post_asr_request(url: str, api_key: str, pcm_bytes: bytes) -> str:
    """Отправляет аудио в ASR и возвращает распознанный текст или пустую строку."""
    if not url or not api_key:
        return ""

    wav_bytes = _pcm_to_wav_bytes(pcm_bytes)

    # TODO: Сверить реальный endpoint, auth scheme, поля multipart/form-data
    # и формат аудио для SaluteSpeech/Neuro.net по официальной документации:
    # SaluteSpeech: https://developers.sber.ru/docs/ru/salutespeech
    # Neuro.net: https://neuro.net/docs
    # TODO: На реальном аудио проверить, принимает ли конкретный API raw PCM
    # или обязательно нужен WAV-контейнер. Сейчас отправляем WAV как самый
    # безопасный каркас для недели 3.
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }
    files = {
        "audio": ("audio.wav", wav_bytes, "audio/wav"),
    }

    async with httpx.AsyncClient(timeout=_ASR_TIMEOUT) as client:
        response = await client.post(url, headers=headers, files=files)
        response.raise_for_status()

    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        return _extract_text_from_response(response.json())

    text = response.text.strip()
    if not text:
        return ""

    try:
        return _extract_text_from_response(json.loads(text))
    except json.JSONDecodeError:
        return text


async def _transcribe_openrouter(pcm_bytes: bytes) -> str:
    if not config.OPENROUTER_API_KEY:
        return ""
    import base64

    wav_bytes = _pcm_to_wav_bytes(pcm_bytes)
    audio_b64 = base64.b64encode(wav_bytes).decode("ascii")
    headers = {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "input_audio": {"data": audio_b64, "format": "wav"},
        "model": config.OPENROUTER_STT_MODEL,
        "language": "ru",
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
        response = await client.post(config.OPENROUTER_STT_URL, headers=headers, json=payload)
        response.raise_for_status()
    data = response.json()
    text = data.get("text", "")
    return text.strip() if isinstance(text, str) else ""



async def _transcribe_salute_speech(pcm_bytes: bytes) -> str:
    if not config.SALUTE_SPEECH_API_KEY:
        return ""
    access_token = await _get_salute_access_token()
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "audio/x-pcm;bit=16;rate=16000",
    }
    async with httpx.AsyncClient(timeout=_ASR_TIMEOUT, verify=False) as client:
        response = await client.post(
            config.SALUTE_SPEECH_URL,
            headers=headers,
            content=pcm_bytes,
        )
        response.raise_for_status()
    data = response.json()
    return _extract_text_from_response(data)


async def _transcribe_neuro_net(pcm_bytes: bytes) -> str:
    if not config.NEURO_NET_API_KEY:
        return ""
    return await _post_asr_request(
        url=config.NEURO_NET_URL,
        api_key=config.NEURO_NET_API_KEY,
        pcm_bytes=pcm_bytes,
    )


async def transcribe(pcm_bytes: bytes) -> str:
    """Распознаёт PCM 16kHz mono signed 16-bit LE и всегда возвращает строку."""
    if not pcm_bytes:
        return ""

    providers = (_transcribe_openrouter, _transcribe_salute_speech, _transcribe_neuro_net)

    for provider in providers:
        try:
            text = await provider(pcm_bytes)
        except (
            httpx.TransportError,
            httpx.HTTPStatusError,
            ValueError,
            TypeError,
            json.JSONDecodeError,
        ) as exc:
            logger.warning("ASR provider failed: %s", exc)
            text = ""

        if text:
            return text

    return ""


async def recognize_audio(pcm_bytes: bytes) -> str:
    """Совместимое имя для real-time пайплайна недели 3."""
    return await transcribe(pcm_bytes)
