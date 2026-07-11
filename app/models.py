"""Модели данных (таблицы базы). Соответствуют разделу 5 в PROJECT.md."""
import uuid
from datetime import datetime, timedelta

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    JSON,
)

from app.database import Base


def new_id() -> str:
    """Генерирует новый уникальный идентификатор (UUID в виде строки)."""
    return str(uuid.uuid4())


class User(Base):
    """Пользователь: либо пенсионер (senior), либо родственник (relative)."""
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=new_id)
    device_id = Column(String, unique=True, nullable=False)
    role = Column(String, nullable=False)            # 'senior' или 'relative'
    phone = Column(String, nullable=True)            # только для SMS
    fcm_token = Column(String, nullable=True)        # push для родственника
    token = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class FamilyLink(Base):
    """Связь между пенсионером и родственником."""
    __tablename__ = "family_links"

    id = Column(String, primary_key=True, default=new_id)
    senior_id = Column(String, ForeignKey("users.id"), nullable=True)
    relative_id = Column(String, ForeignKey("users.id"), nullable=True)
    pairing_code = Column(String, nullable=True)      # 6 цифр
    pairing_expires_at = Column(
        DateTime,
        default=lambda: datetime.utcnow() + timedelta(hours=24),
        nullable=True,
    )
    label = Column(String, nullable=True)             # "Папа", "Мама"
    protection_mode = Column(String, default="standard")
    relative_phone = Column(String, nullable=True)
    status = Column(String, default="pending")      # 'pending' / 'active'
    created_at = Column(DateTime, default=datetime.utcnow)


class Call(Base):
    """Один телефонный звонок и вердикт по нему."""
    __tablename__ = "calls"

    id = Column(String, primary_key=True, default=new_id)
    senior_id = Column(String, ForeignKey("users.id"), nullable=False)
    caller_phone = Column(String, nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    verdict = Column(String, nullable=True)          # safe / suspicious / scam
    threat_level = Column(Integer, default=0)        # 0..100
    transcript = Column(Text, nullable=True)


class Alert(Base):
    """Тревога, отправленная родственнику."""
    __tablename__ = "alerts"

    id = Column(String, primary_key=True, default=new_id)
    call_id = Column(String, ForeignKey("calls.id"), nullable=False)
    relative_id = Column(String, ForeignKey("users.id"), nullable=False)
    channels = Column(JSON, nullable=True)           # channels JSON можно упростить до списка строк
    delivered = Column(Boolean, default=False)
    sent_at = Column(DateTime, default=datetime.utcnow)


class Subscription(Base):
    """Подписка родственника."""
    __tablename__ = "subscriptions"

    id = Column(String, primary_key=True, default=new_id)
    relative_id = Column(String, ForeignKey("users.id"), nullable=False)
    plan = Column(String, nullable=True)             # monthly / yearly
    status = Column(String, default="active")
    yookassa_sub_id = Column(String, nullable=True)
    period_end = Column(DateTime, nullable=True)
