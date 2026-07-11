"""Pydantic-схемы для REST API."""
from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime


class DeviceRegisterRequest(BaseModel):
    """Тело запроса для регистрации устройства."""

    device_id: str = Field(min_length=1, max_length=255)


class SeniorRegisterResponse(BaseModel):
    """Ответ регистрации пенсионера."""

    pairing_code: str
    token: str


class RelativeRegisterResponse(BaseModel):
    """Ответ регистрации родственника."""

    token: str


class FamilyPairRequest(BaseModel):
    """Тело запроса для привязки родственника по коду."""

    pairing_code: str = Field(min_length=6, max_length=6)


class FamilyPairResponse(BaseModel):
    """Ответ после успешной привязки родственника."""

    family_link_id: str
    status: str
    message: str


class RelativePhoneRequest(BaseModel):
    """Тело запроса для сохранения телефона родственника."""

    phone: str = Field(min_length=1, max_length=32)


class RelativePhoneResponse(BaseModel):
    """Ответ после сохранения телефона родственника."""

    phone: str
    message: str


class RelativeFcmTokenRequest(BaseModel):
    """Тело запроса для сохранения FCM-токена родственника."""

    token: str = Field(min_length=1, max_length=4096)


class RelativeFcmTokenResponse(BaseModel):
    """Ответ после сохранения FCM-токена родственника."""

    message: str


class FamilyLinkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    senior_id: str | None
    relative_id: str | None
    label: str | None
    status: str
    relative_phone: str | None


class UserResponse(BaseModel):
    """Публичные данные пользователя для auth dependency."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    device_id: str
    role: str
    phone: str | None
    token: str | None
    family_links: list[FamilyLinkResponse] = []


class DebugAnalyzeRequest(BaseModel):
    """Тело запроса для debug-анализа текстового транскрипта."""

    transcript: str = Field(min_length=1)


class DebugAnalyzeResponse(BaseModel):
    """Ответ debug-анализа с сохранённой записью звонка."""

    call_id: str
    verdict: str
    threat_level: int
    scheme: str
    flags: list[str]
    clean_text: str
    alert: bool


class CallHistoryItem(BaseModel):
    id: str
    started_at: datetime | None
    ended_at: datetime | None
    verdict: str | None
    threat_level: int


class CallHistoryResponse(BaseModel):
    calls: list[CallHistoryItem]


class CallDetailResponse(BaseModel):
    id: str
    started_at: datetime | None
    ended_at: datetime | None
    verdict: str | None
    threat_level: int
    transcript: str | None
    caller_phone: str | None

