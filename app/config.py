"""Настройки приложения. Читаются из переменных окружения / файла .env."""
import os

from dotenv import load_dotenv

# Загружаем переменные из файла .env (если он есть рядом).
load_dotenv()

# Секрет для подписи токенов. На неделе 1 ещё не используется.
APP_SECRET = os.getenv("APP_SECRET", "dev-secret-change-me")

# Имя файла базы данных SQLite.
DB_FILE = os.getenv("DB_FILE", "family_shield.db")

# Внешние сервисы недели 2.
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
OPENROUTER_FALLBACK_MODEL = os.getenv(
    "OPENROUTER_FALLBACK_MODEL", "deepseek/deepseek-chat"
)
OPENROUTER_STT_URL = os.getenv(
    "OPENROUTER_STT_URL", "https://openrouter.ai/api/v1/audio/transcriptions"
)
OPENROUTER_STT_MODEL = os.getenv(
    "OPENROUTER_STT_MODEL", "openai/whisper-large-v3"
)
SCAM_SCORE_THRESHOLD = float(os.getenv("SCAM_SCORE_THRESHOLD", "0.85"))

# Внешние сервисы недели 3.
SALUTE_SPEECH_API_KEY = os.getenv("SALUTE_SPEECH_API_KEY", "")
SALUTE_SPEECH_AUTH_URL = os.getenv(
    "SALUTE_SPEECH_AUTH_URL",
    "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
)
SALUTE_SPEECH_SCOPE = os.getenv("SALUTE_SPEECH_SCOPE", "SALUTE_SPEECH_PERS")
SALUTE_SPEECH_URL = os.getenv(
    "SALUTE_SPEECH_URL",
    "https://smartspeech.sber.ru/rest/v1/speech:recognize",
)
NEURO_NET_API_KEY = os.getenv("NEURO_NET_API_KEY", "")
NEURO_NET_URL = os.getenv("NEURO_NET_URL", "https://api.neuro.net/api/v1/recognize")
SMSC_LOGIN = os.getenv("SMSC_LOGIN", "")
SMSC_PASSWORD = os.getenv("SMSC_PASSWORD", "")
SMSC_SENDER = os.getenv("SMSC_SENDER", "")
SMSAERO_EMAIL = os.getenv("SMSAERO_EMAIL", "")
SMSAERO_API_KEY = os.getenv("SMSAERO_API_KEY", "")
SMSAERO_SIGN = os.getenv("SMSAERO_SIGN", "")
FCM_SERVER_KEY = os.getenv("FCM_SERVER_KEY", "")  # устарел (Legacy API отключён 2024-06)
FCM_SERVICE_ACCOUNT_JSON = os.getenv("FCM_SERVICE_ACCOUNT_PATH", os.getenv("FCM_SERVICE_ACCOUNT_JSON", ""))
PCM_SAMPLE_RATE = int(os.getenv("PCM_SAMPLE_RATE", "16000"))
PCM_CHUNK_DURATION_SEC = int(os.getenv("PCM_CHUNK_DURATION_SEC", "8"))
