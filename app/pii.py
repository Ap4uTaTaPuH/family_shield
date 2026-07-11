"""PII-фильтр для транскриптов."""
import re

_PHONE_PATTERNS = [
    re.compile(r"(?<!\d)(?:\+7|8|7)[\s-]?\(?\d{3}\)?[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}(?!\d)"),
    re.compile(r"(?<!\d)\d{10,11}(?!\d)"),
]
_CARD_PATTERN = re.compile(r"(?<!\d)(?:\d[\s-]?){13,19}(?!\d)")
_SUM_PATTERN = re.compile(
    r"(?<!\d)\d{2,}(?:[ \u00A0-]?\d{3})*\s*(?:руб(?:\.|лей)?|р\.?|₽|к)\b",
    re.IGNORECASE,
)
_CODE_PATTERN = re.compile(r"(?<!\d)\d{4,}(?!\d)")


def pii_filter(text: str) -> str:
    if not text:
        return ""

    result = text
    for pattern in _PHONE_PATTERNS:
        result = pattern.sub("[PHONE]", result)
    result = _CARD_PATTERN.sub("[CARD]", result)
    result = _SUM_PATTERN.sub("[SUM]", result)
    result = _CODE_PATTERN.sub("[CODE]", result)
    return result
