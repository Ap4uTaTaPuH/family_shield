"""LLM-классификатор мошеннических транскриптов через OpenRouter."""
import json
from typing import Any

import httpx

from app import config

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_ALLOWED_LABELS = {"safe", "suspicious", "scam"}
_ALLOWED_SCHEMES = {
    "SAFE_ACCOUNT",
    "CB_OFFICER",
    "POLICE_FSB",
    "RELATIVE_TROUBLE",
    "PRIZE",
    "COURIER",
    "NONE",
}
_FALLBACK_RESULT = {
    "label": "suspicious",
    "score": 0.0,
    "scheme": "NONE",
    "flags": ["parse_error"],
}
_SYSTEM_PROMPT = """Ты классификатор телефонного мошенничества для MVP Family Shield.

Проанализируй транскрипт звонка и верни ТОЛЬКО валидный JSON-объект без markdown, пояснений и лишнего текста.

Схема ответа:
{
  "label": "safe" | "suspicious" | "scam",
  "score": число от 0 до 1,
  "scheme": "SAFE_ACCOUNT" | "CB_OFFICER" | "POLICE_FSB" | "RELATIVE_TROUBLE" | "PRIZE" | "COURIER" | "NONE",
  "flags": ["короткие_признаки"]
}

Правила:
- SAFE_ACCOUNT: безопасный счёт, перевод денег на защищённый счёт.
- CB_OFFICER: якобы служба безопасности банка, подозрительные операции, срочно перевести деньги.
- POLICE_FSB: давление от имени полиции, следствия, ФСБ, Центробанка.
- RELATIVE_TROUBLE: родственник попал в беду, ДТП, срочно нужны деньги.
- PRIZE: выигрыш, компенсация, приз, пошлина за получение.
- COURIER: передача наличных через курьера.
- NONE: если признаков схемы нет.
- score — уверенность модели.
- Если текст без явных признаков мошенничества, выбирай safe + NONE.
- Если признаки есть, но данных мало, выбирай suspicious.
- Если есть явное давление, легенда и побуждение к переводу/передаче денег, выбирай scam.
"""
_FEW_SHOT_MESSAGES: list[dict[str, str]] = [
    {
        "role": "user",
        "content": "Транскрипт: Здравствуйте, это служба безопасности банка. По вашему счёту подозрительная операция. Срочно переведите деньги на безопасный счёт, иначе их спишут.",
    },
    {
        "role": "assistant",
        "content": '{"label":"scam","score":0.99,"scheme":"SAFE_ACCOUNT","flags":["служба_безопасности","безопасный_счет","срочный_перевод"]}',
    },
    {
        "role": "user",
        "content": "Транскрипт: Мама, я попал в аварию, не звони никому. Сейчас следователь скажет, куда перевести деньги, чтобы меня не посадили.",
    },
    {
        "role": "assistant",
        "content": '{"label":"scam","score":0.98,"scheme":"RELATIVE_TROUBLE","flags":["родственник_в_беде","эмоциональное_давление","требование_денег"]}',
    },
    {
        "role": "user",
        "content": "Транскрипт: Алло, привет. Я купил хлеб и молоко, буду дома через полчаса. Если что, позвони мне позже.",
    },
    {
        "role": "assistant",
        "content": '{"label":"safe","score":0.99,"scheme":"NONE","flags":[]}',
    },
]


def _build_messages(text: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        *_FEW_SHOT_MESSAGES,
        {
            "role": "user",
            "content": (
                "Транскрипт для классификации:\n"
                f"{text}\n\n"
                "Верни только JSON по указанной схеме."
            ),
        },
    ]


async def _request_openrouter(model: str, text: str) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": _build_messages(text),
        "temperature": 0,
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0)) as client:
        response = await client.post(_OPENROUTER_URL, headers=headers, json=payload)
        response.raise_for_status()

    data = response.json()
    return data


def _extract_content(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("OpenRouter response has no choices")

    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise ValueError("OpenRouter response has no message")

    content = message.get("content")
    if not isinstance(content, str):
        raise ValueError("OpenRouter response content is not a string")

    return content.strip()


def _validate_result(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Result is not an object")

    label = value.get("label")
    scheme = value.get("scheme")
    score = value.get("score")
    flags = value.get("flags")

    if label not in _ALLOWED_LABELS:
        raise ValueError("Invalid label")
    if scheme not in _ALLOWED_SCHEMES:
        raise ValueError("Invalid scheme")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise ValueError("Invalid score type")

    score_value = float(score)
    if score_value < 0.0 or score_value > 1.0:
        raise ValueError("Score out of range")
    if not isinstance(flags, list) or not all(isinstance(item, str) for item in flags):
        raise ValueError("Invalid flags")

    return {
        "label": label,
        "score": score_value,
        "scheme": scheme,
        "flags": flags,
    }


def _parse_result(raw_content: str) -> dict[str, Any]:
    parsed = json.loads(raw_content)
    return _validate_result(parsed)


async def classify_transcript(text: str) -> dict[str, Any]:
    """Классифицирует транскрипт через OpenRouter и всегда возвращает dict."""
    if not config.OPENROUTER_API_KEY:
        return dict(_FALLBACK_RESULT)

    try:
        primary_data = await _request_openrouter(config.OPENROUTER_MODEL, text)
        primary_content = _extract_content(primary_data)
        return _parse_result(primary_content)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, httpx.HTTPStatusError):
        return dict(_FALLBACK_RESULT)
    except httpx.TransportError:
        try:
            fallback_data = await _request_openrouter(
                config.OPENROUTER_FALLBACK_MODEL,
                text,
            )
            fallback_content = _extract_content(fallback_data)
            return _parse_result(fallback_content)
        except (
            httpx.TransportError,
            httpx.HTTPStatusError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ):
            return dict(_FALLBACK_RESULT)
