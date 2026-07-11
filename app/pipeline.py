"""Текстовый call pipeline для недели 2 без аудио и WebSocket."""
from typing import Any

from app import config
from app.classifier import classify_transcript
from app.pii import pii_filter


async def analyze_transcript(text: str) -> dict[str, Any]:
    """Очищает транскрипт и возвращает нормализованный вердикт пайплайна."""
    clean_text = pii_filter(text)
    classification = await classify_transcript(clean_text)

    label = classification["label"]
    score = float(classification["score"])

    return {
        "verdict": label,
        "threat_level": round(score * 100),
        "scheme": classification["scheme"],
        "flags": classification["flags"],
        "clean_text": clean_text,
        "alert": label == "scam" and score >= config.SCAM_SCORE_THRESHOLD,
    }
