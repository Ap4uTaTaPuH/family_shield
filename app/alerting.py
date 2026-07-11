"""Оркестрация тревоги для недели 3 MVP."""
from __future__ import annotations

from datetime import datetime
import logging

from fastapi import WebSocket
from sqlalchemy.orm import Session

from app.fcm import send_fcm_push
from app.models import Alert, FamilyLink, User
from app.sms import send_alert_sms

logger = logging.getLogger(__name__)

WARNING_SMS_TEXT = (
    "ТРЕВОГА! Возможное мошенничество в звонке пенсионера. "
    "Проверьте приложение Family Shield."
)
WARNING_PUSH_TITLE = "Семейный щит: тревога"
WARNING_PUSH_BODY = "Обнаружено возможное мошенничество в звонке пенсионера."

# недели 3 MVP
active_notify_connections: dict[str, WebSocket] = {}


async def send_notify_alert(
    user_id: str,
    call_id: str,
    timestamp: str,
    message: str = "Тревога!",
) -> bool:
    """Отправляет alert в активное WS-соединение родственника, если оно есть."""
    websocket = active_notify_connections.get(user_id)
    if websocket is None:
        return False

    try:
        await websocket.send_json(
            {
                "type": "alert",
                "call_id": call_id,
                "timestamp": timestamp,
                "message": message,
            }
        )
    except Exception:
        logger.exception("Failed to send notify alert to user_id=%s", user_id)
        return False

    return True


async def trigger_alert(call_id: str, senior_id: str, db: Session) -> None:
    """Создаёт и доставляет тревоги всем активным родственникам senior."""
    active_links = (
        db.query(FamilyLink)
        .filter(
            FamilyLink.senior_id == senior_id,
            FamilyLink.status == "active",
            FamilyLink.relative_id.isnot(None),
        )
        .all()
    )

    for family_link in active_links:
        relative_id = family_link.relative_id
        if relative_id is None:
            continue

        relative = db.query(User).filter(User.id == relative_id).first()
        alert = Alert(
            call_id=call_id,
            relative_id=relative_id,
            channels=["ws", "sms", "fcm"],
            delivered=False,
        )
        # channels JSON можно упростить до списка строк
        db.add(alert)
        db.commit()
        db.refresh(alert)

        timestamp = (
            alert.sent_at.isoformat()
            if alert.sent_at is not None
            else datetime.utcnow().isoformat()
        )
        relative_phone = family_link.relative_phone or (relative.phone if relative else None)
        relative_fcm_token = relative.fcm_token if relative else None

        try:
            ws_delivered = await send_notify_alert(
                user_id=relative_id,
                call_id=call_id,
                timestamp=timestamp,
                message=WARNING_PUSH_BODY,
            )
            if ws_delivered:
                alert.delivered = True
        except Exception:
            logger.exception(
                "WS alert failed call_id=%s relative_id=%s",
                call_id,
                relative_id,
            )
        finally:
            db.commit()

        if relative_phone:
            try:
                sms_delivered = await send_alert_sms(relative_phone, WARNING_SMS_TEXT)
                if sms_delivered:
                    alert.delivered = True
                else:
                    logger.warning(
                        "SMS alert not delivered call_id=%s relative_id=%s phone=%s",
                        call_id,
                        relative_id,
                        relative_phone,
                    )
            except Exception:
                logger.exception(
                    "SMS alert failed call_id=%s relative_id=%s phone=%s",
                    call_id,
                    relative_id,
                    relative_phone,
                )
            finally:
                db.commit()
        else:
            logger.info(
                "SMS alert skipped call_id=%s relative_id=%s reason=no_phone",
                call_id,
                relative_id,
            )

        if relative_fcm_token:
            try:
                push_delivered = await send_fcm_push(
                    fcm_token=relative_fcm_token,
                    call_id=call_id,
                    title=WARNING_PUSH_TITLE,
                    body=WARNING_PUSH_BODY,
                )
                if push_delivered:
                    alert.delivered = True
                else:
                    logger.warning(
                        "FCM alert not delivered call_id=%s relative_id=%s",
                        call_id,
                        relative_id,
                    )
            except Exception:
                logger.exception(
                    "FCM alert failed call_id=%s relative_id=%s",
                    call_id,
                    relative_id,
                )
            finally:
                db.commit()
        else:
            logger.info(
                "FCM alert skipped call_id=%s relative_id=%s reason=no_token",
                call_id,
                relative_id,
            )
