"""Точка входа приложения. Запускает сервер и создаёт таблицы при старте."""
from contextlib import asynccontextmanager
from datetime import datetime
import logging
import random

from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.alerting import active_notify_connections, trigger_alert
from app.asr import recognize_audio
from app.auth import create_token, get_current_user
from app.database import get_db, init_db
from app.fcm import _mask_fcm_token
from app.models import Call, FamilyLink, User
from app.pipeline import analyze_transcript
from app.schemas import (
    CallDetailResponse,
    CallHistoryItem,
    CallHistoryResponse,
    DebugAnalyzeRequest,
    DebugAnalyzeResponse,
    DeviceRegisterRequest,
    FamilyLinkResponse,
    FamilyPairRequest,
    FamilyPairResponse,
    RelativeFcmTokenRequest,
    RelativeFcmTokenResponse,
    RelativePhoneRequest,
    RelativePhoneResponse,
    RelativeRegisterResponse,
    SeniorRegisterResponse,
    UserResponse,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Family Shield API", version="0.1.0", lifespan=lifespan)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:     %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)
TTS_WARNING_TEXT = (
    "Внимание! Возможный мошенник. Не сообщайте данные карты."
)


def _validate_ws_token(token: str, db: Session) -> User | None:
    """Валидирует query-token для WebSocket через get_current_user и возвращает пользователя или None."""
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    try:
        return get_current_user(credentials=credentials, db=db)
    except HTTPException:
        return None


def _get_relative_senior_ids(db: Session, relative_id: str) -> list[str]:
    """Возвращает список active senior_id для родственника."""
    links = (
        db.query(FamilyLink.senior_id)
        .filter(
            FamilyLink.relative_id == relative_id,
            FamilyLink.status == "active",
            FamilyLink.senior_id.isnot(None),
        )
        .all()
    )
    return [senior_id for (senior_id,) in links]


@app.get("/api/health")
def health():

    """Простой эндпоинт-проверка: сервер жив?"""
    return {"status": "ok"}


@app.post("/api/senior/register", response_model=SeniorRegisterResponse)
def register_senior(payload: DeviceRegisterRequest, db: Session = Depends(get_db)):
    """Регистрирует senior и создаёт pending family_link с pairing_code.

    Идемпотентно по pending FamilyLink: если у senior уже есть pending link
    с не истёкшим pairing_expires_at — возвращает его существующий pairing_code.
    Истёкшие pending-линки этого senior удаляются (active не трогаем).
    """
    now = datetime.utcnow()
    token = create_token(payload.device_id)

    user = db.query(User).filter(User.device_id == payload.device_id).first()
    if user is None:
        user = User(device_id=payload.device_id, role="senior", token=token)
        db.add(user)
        db.flush()
    else:
        user.role = "senior"
        user.token = token

    # Cleanup: удаляем истёкшие pending-линки этого senior.
    # active-линки не трогаем (у них свой relative_id и pairing_expires_at
    # не используется как условие протухания).
    db.query(FamilyLink).filter(
        FamilyLink.senior_id == user.id,
        FamilyLink.status == "pending",
        FamilyLink.pairing_expires_at < now,
    ).delete(synchronize_session=False)

    # Ищем валидный pending. Фильтр pairing_expires_at > now гарантирует,
    # что только что удалённые истёкшие строки не попадут в результат,
    # даже если session ещё не синхронизировала delete.
    existing_pending = (
        db.query(FamilyLink)
        .filter(
            FamilyLink.senior_id == user.id,
            FamilyLink.status == "pending",
            FamilyLink.pairing_expires_at > now,
        )
        .order_by(FamilyLink.created_at.desc())
        .first()
    )

    if existing_pending is not None:
        pairing_code = existing_pending.pairing_code
    else:
        pairing_code = f"{random.SystemRandom().randint(0, 999999):06d}"
        family_link = FamilyLink(
            senior_id=user.id,
            pairing_code=pairing_code,
            status="pending",
        )
        db.add(family_link)

    db.commit()

    return SeniorRegisterResponse(pairing_code=pairing_code, token=token)


@app.post("/api/relative/register", response_model=RelativeRegisterResponse)
def register_relative(payload: DeviceRegisterRequest, db: Session = Depends(get_db)):
    """Регистрирует relative и возвращает токен."""
    token = create_token(payload.device_id)

    user = db.query(User).filter(User.device_id == payload.device_id).first()
    if user is None:
        user = User(device_id=payload.device_id, role="relative", token=token)
        db.add(user)
    else:
        user.role = "relative"
        user.token = token

    db.commit()
    return RelativeRegisterResponse(token=token)


@app.post("/api/family/pair", response_model=FamilyPairResponse)
def pair_family(
    payload: FamilyPairRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Привязывает родственника к senior по 6-значному коду."""
    if current_user.role != "relative":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Только родственник может привязаться по коду.",
        )

    existing_active_link = (
        db.query(FamilyLink)
        .filter(
            FamilyLink.relative_id == current_user.id,
            FamilyLink.status == "active",
        )
        .first()
    )
    if existing_active_link is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Этот родственник уже привязан к другому пенсионеру.",
        )

    family_link = (
        db.query(FamilyLink)
        .filter(FamilyLink.pairing_code == payload.pairing_code)
        .first()
    )
    if family_link is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Код не найден. Проверьте 6 цифр у получателя кода.",
        )

    if family_link.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Этот код уже использован.",
        )

    if (
        family_link.pairing_expires_at is not None
        and family_link.pairing_expires_at < datetime.utcnow()
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Срок действия кода истёк. Попросите пенсионера получить новый код.",
        )

    family_link.relative_id = current_user.id
    family_link.relative_phone = current_user.phone
    family_link.status = "active"
    db.commit()

    return FamilyPairResponse(
        family_link_id=family_link.id,
        status=family_link.status,
        message="Связь с пенсионером успешно подтверждена.",
    )


@app.post("/api/relative/phone", response_model=RelativePhoneResponse)
def save_relative_phone(
    payload: RelativePhoneRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Сохраняет телефон для SMS у авторизованного родственника."""
    if current_user.role != "relative":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Только родственник может сохранить свой номер телефона.",
        )

    current_user.phone = payload.phone
    for family_link in db.query(FamilyLink).filter(FamilyLink.relative_id == current_user.id):
        family_link.relative_phone = payload.phone

    db.commit()
    return RelativePhoneResponse(
        phone=payload.phone,
        message="Номер телефона сохранён.",
    )


@app.post("/api/relative/fcm-token", response_model=RelativeFcmTokenResponse)
def save_relative_fcm_token(
    payload: RelativeFcmTokenRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Идемпотентно сохраняет FCM-токен у авторизованного родственника."""
    if current_user.role != "relative":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Только родственник может сохранить FCM-токен.",
        )

    current_user.fcm_token = payload.token
    db.commit()
    logger.info(
        "FCM token saved relative_id=%s token=%s",
        current_user.id,
        _mask_fcm_token(payload.token),
    )
    return RelativeFcmTokenResponse(message="FCM-токен сохранён.")


@app.get("/api/me", response_model=UserResponse)
def get_me(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Возвращает профиль пользователя и активные семейные связи."""
    active_links = (
        db.query(FamilyLink)
        .filter(FamilyLink.status == "active")
        .filter(
            FamilyLink.relative_id == current_user.id
            if current_user.role == "relative"
            else FamilyLink.senior_id == current_user.id
        )
        .order_by(FamilyLink.created_at.desc())
        .all()
    )

    return UserResponse(
        id=current_user.id,
        device_id=current_user.device_id,
        role=current_user.role,
        phone=current_user.phone,
        token=current_user.token,
        family_links=[
            FamilyLinkResponse(
                id=link.id,
                senior_id=link.senior_id,
                relative_id=link.relative_id,
                label=link.label,
                status=link.status,
                relative_phone=link.relative_phone,
            )
            for link in active_links
        ],
    )


@app.get("/api/calls/history", response_model=CallHistoryResponse)
def get_calls_history(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """История звонков для родственника по всем активным привязкам."""
    if current_user.role != "relative":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Только родственник может смотреть историю звонков.",
        )

    senior_ids = _get_relative_senior_ids(db, current_user.id)
    if not senior_ids:
        return CallHistoryResponse(calls=[])

    calls = (
        db.query(Call)
        .filter(Call.senior_id.in_(senior_ids))
        .order_by(Call.started_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return CallHistoryResponse(
        calls=[
            CallHistoryItem(
                id=call.id,
                started_at=call.started_at,
                ended_at=call.ended_at,
                verdict=call.verdict,
                threat_level=call.threat_level,
            )
            for call in calls
        ]
    )


@app.get("/api/calls/{call_id}", response_model=CallDetailResponse)
def get_call_detail(
    call_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Детали звонка для родственника только по своим active senior."""
    if current_user.role != "relative":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Только родственник может смотреть детали звонков.",
        )

    call = db.query(Call).filter(Call.id == call_id).first()
    if call is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Звонок не найден.",
        )

    senior_ids = _get_relative_senior_ids(db, current_user.id)
    if call.senior_id not in senior_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нет доступа",
        )

    return CallDetailResponse(
        id=call.id,
        started_at=call.started_at,
        ended_at=call.ended_at,
        verdict=call.verdict,
        threat_level=call.threat_level,
        transcript=call.transcript,
        caller_phone=call.caller_phone,
    )


@app.websocket("/ws/notify")
async def websocket_notify(websocket: WebSocket, db: Session = Depends(get_db)):

    """WebSocket real-time тревог для родственника."""
    token = websocket.query_params.get("token", "")

    current_user = _validate_ws_token(token=token, db=db)
    if current_user is None:
        await websocket.close(code=1008, reason="Invalid token")
        return

    if current_user.role != "relative":
        await websocket.close(code=1008, reason="Only relative can open notify stream")
        return

    await websocket.accept()
    active_notify_connections[current_user.id] = websocket
    logger.info(
        "/ws/notify connected user_id=%s active=%s",
        current_user.id,
        len(active_notify_connections),
    )

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info("/ws/notify disconnected")
    except Exception:
        logger.exception("Unexpected error in /ws/notify")
        await websocket.close(code=1011)
    finally:
        if active_notify_connections.get(current_user.id) is websocket:
            active_notify_connections.pop(current_user.id, None)
            logger.info(
                "/ws/notify disconnected user_id=%s active=%s",
                current_user.id,
                len(active_notify_connections),
            )


@app.websocket("/ws/call")
async def websocket_call(websocket: WebSocket, db: Session = Depends(get_db)):
    """WebSocket real-time анализа звонка для недели 3 MVP."""
    # недели 3 MVP
    # в проде добавить rate-limit и reconnect-логику
    token = websocket.query_params.get("token", "")
    call: Call | None = None
    transcript_parts: list[str] = []
    alert_triggered = False

    current_user = _validate_ws_token(token=token, db=db)
    if current_user is None:
        await websocket.close(code=1008, reason="Invalid token")
        return

    if current_user.role != "senior":
        await websocket.close(code=1008, reason="Only senior can open call stream")
        return

    await websocket.accept()
    logger.info("WS /ws/call connected user_id=%s", current_user.id)

    try:
        call = Call(
            senior_id=current_user.id,
            started_at=datetime.utcnow(),
            verdict=None,
        )
        db.add(call)
        db.commit()
        db.refresh(call)
        logger.info("Call record created call_id=%s", call.id)

        while True:
            logger.debug("Waiting for audio chunk...")
            pcm_bytes = await websocket.receive_bytes()
            logger.info("Received audio chunk: %d bytes", len(pcm_bytes))
            
            text = await recognize_audio(pcm_bytes)
            logger.info("ASR result: %s", text if text else "(empty)")
            if not text:
                continue

            transcript_parts.append(text.strip())
            transcript = " ".join(part for part in transcript_parts if part).strip()
            if not transcript:
                continue

            result = await analyze_transcript(transcript)
            call.verdict = result["verdict"]
            call.threat_level = result["threat_level"]
            call.transcript = result["clean_text"]
            db.commit()
            logger.info(
                "LLM verdict: %s, score=%s, flags=%s",
                result["verdict"],
                result["threat_level"],
                result.get("flags", [])
            )

            if result["alert"] and not alert_triggered:
                logger.info("SCAM DETECTED! Triggering alert for call_id=%s", call.id)
                await trigger_alert(call.id, current_user.id, db)
                await websocket.send_json(
                    {
                        "action": "tts",
                        "text": TTS_WARNING_TEXT,
                    }
                )
                logger.info("TTS command sent to senior")
                alert_triggered = True

    except WebSocketDisconnect:
        logger.info("/ws/call disconnected")
    except Exception:
        logger.exception("Unexpected error in /ws/call")
        await websocket.close(code=1011)
    finally:
        if call is not None:
            call.ended_at = datetime.utcnow()
            db.commit()


@app.post("/api/debug/analyze", response_model=DebugAnalyzeResponse)
async def debug_analyze_transcript(
    payload: DebugAnalyzeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Debug-only эндпоинт недели 2; в проде должен быть закрыт или удалён."""
    result = await analyze_transcript(payload.transcript)

    call = Call(
        senior_id=current_user.id,
        verdict=result["verdict"],
        threat_level=result["threat_level"],
        transcript=result["clean_text"],
        ended_at=datetime.utcnow(),
    )
    db.add(call)
    db.commit()
    db.refresh(call)

    if result["alert"]:
        logger.info("DEBUG ANALYZE: scam detected, triggering alert for call_id=%s", call.id)
        await trigger_alert(call.id, current_user.id, db)

    return DebugAnalyzeResponse(call_id=call.id, **result)
