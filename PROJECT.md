# Семейный щит — PROJECT.md (MVP, real-time анализ звонков)

> Единый источник правды для разработки через GPT-5.4 / GPT-5.4 mini в Kodik.  
> Держать этот файл коротким и актуальным. Прикреплять в контекст каждой крупной сессии.  
> Правило: одна фича за раз, после рабочей фичи — git commit.

---

## 0. Что это

Android-приложение, которое во время телефонного звонка пенсионера слушает речь,
в реальном времени распознаёт мошеннические паттерны и:

1. голосом предупреждает пенсионера (TTS в динамик),
2. отправляет тревогу родственнику (push + экстренное SMS).

Заказчик/плательщик — родственник. Пользователь под защитой — пенсионер (senior).

---

## 1. Зафиксированные решения (НЕ менять без причины)


| Тема                | Решение                                                                                                           |
| ------------------- | ----------------------------------------------------------------------------------------------------------------- |
| Захват звука        | **Accessibility Service** слушает аудио сессии звонка. Фолбэк-ветка на MIC+спикерфон описана в §7.                |
| Анализ              | **Real-time стриминг** аудио-чанков на сервер во время звонка                                                     |
| ASR                 | **Облачный, цепочка провайдеров:** OpenRouter STT (Whisper-large-v3) — основной, SaluteSpeech и Neuro.net — fallback |
| Реакция на угрозу   | Оповещение родственника (push+SMS) + **TTS-предупреждение пенсионеру**. Звонок НЕ сбрасываем автоматически в MVP. |
| Экстренное SMS      | С **сервера через SMSAERO.ru**                                                                                       |
| БД                  | **SQLite** на старте (миграция на Postgres — после MVP)                                                           |
| Транспорт реалтайма | WebSocket только для аудио-стрима и тревог. Остальное — REST.                                                     |
| Push                | **FCM** (Firebase Cloud Messaging)                                                                                |
| Платформа           | Android 9 (API 28) … 16. iOS — нет.                                                                               |
| Дистрибуция         | APK ставит родственник физически на телефон пенсионера (Google Play запись звонков забанит)                       |


---

## 2. КРИТИЧЕСКОЕ ПРЕДУПРЕЖДЕНИЕ ПО ЗАХВАТУ ЗВУКА (читать до старта)

Accessibility Service в Android **НЕ даёт прямого доступа к аудиопотоку звонка.**
Он даёт: события UI, чтение экрана, возможность держать процесс живым, кнопки/жесты.
Захват именно ГОЛОСА собеседника по линии без системных привилегий на стоковом
Android 10+ официально невозможен — это намеренное ограничение ОС (тайна связи).

Что это значит для MVP — выбрать одну из двух честных реализаций:

- **Реализация A (ВЫБРАНА, работает): Accessibility-клик по кнопке спикерфона + MIC.**
  `AudioManager.setSpeakerphoneOn()` / `setCommunicationDevice()` от стороннего
  приложения на Android 10+ **игнорируется** Telecom'ом (`Ignoring speakerphone
  request -- already false` — подтверждено логами на Tecno). Telecom сам владеет
  маршрутизацией звонка и принимает команды только от дефолтного дайлера через
  `InCallService.setAudioRoute()`.
  **Рабочий путь:** `ShieldAccessibilityService` при переходе в `CallState.ACTIVE`
  ищет кнопку динамика в дереве AccessibilityNodeInfo дайлера (BFS по id/description:
  `speaker`, `speakerphone`, `динамик`, `громкая связь` и т.д.) и вызывает
  `performAction(ACTION_CLICK)` — это тот же «палец пользователя», Telecom его не
  блокирует. Повторные попытки на 200/500/1000/2000/3500 мс + триггер на
  `TYPE_WINDOW_CONTENT_CHANGED`. Защита от двойного клика: если кнопка уже
  `isChecked` — не трогаем.
  **Подтверждено на Tecno (com.sh.smart.caller):** кнопка `com.sh.smart.caller:id/incall_speaker_button`
  (desc=«Динамик, отключен») находится и кликается с первой попытки (~120 мс после ACTIVE).
  Тогда `AudioRecord(VOICE_RECOGNITION, 16kHz, mono, PCM)` ловит оба голоса из динамика.
  Минус: разговор идёт по громкой связи.
- **Реализация B (агрессивная, нестабильная): захват сессии звонка.**
  Попытка `AudioPlaybackCapture` (API 29+) и/или вендорских источников
  `VOICE_CALL`/`VOICE_DOWNLINK`. Работает фрагментарно, зависит от вендора и
  версии, легко даёт тишину. НЕ закладывать как основной путь MVP.

=> В коде MVP делаем A. `SpeakerphoneController` через `AudioManager` оставлен
как best-effort fallback (ничего не ломает, но реально не работает на Android 10+).
Основной механизм включения спикерфона — клик через `ShieldAccessibilityService`.

---

## 3. Архитектура (текстом + ASCII)

```
  ПЕНСИОНЕР (Android, роль SENIOR)
  ┌───────────────────────────────────────────────┐
  │ AccessibilityService (детект звонка)           │
  │   └─> включает спикерфон                        │
  │ ForegroundService "Щит"                         │
  │   ├─ AudioRecord (MIC, 16kHz mono)              │
  │   ├─ нарезка на чанки ~8 сек                    │
  │   └─ WebSocket: отправка чанков на сервер       │
  │ TtsPlayer (проигрывает предупреждение в динамик)│
  └───────────────┬───────────────────────────────┘
                  │  WS /ws/call  (аудио-чанки)
                  ▼
  ┌───────────────────────────────────────────────┐
  │ BACKEND  (FastAPI, один процесс, SQLite)        │
  │  call_pipeline:                                 │
  │    чанк -> PII-фильтр(regex) -> ASR             │
  │         (OpenRouter Whisper осн.,               │
  │          SaluteSpeech / Neuro.net fallback)      │
  │         -> LLM-классификатор(OpenRouter)         │
  │         -> вердикт (safe/suspicious/scam, score) │
  │  если scam:                                     │
  │    -> WS senior: команда TTS-предупреждения      │
  │    -> FCM push родственнику                      │
  │    -> SMSAERO.ru экстренное SMS родственнику         │
  │  запись: только ТЕКСТ транскрипта (не аудио)     │
  └───────────────┬───────────────────────────────┘
                  │ FCM push + WS /ws/notify
                  ▼
  РОДСТВЕННИК (Android, роль RELATIVE)
  ┌───────────────────────────────────────────────┐
  │ Экран тревоги (full-screen intent)              │
  │ История звонков / транскрипты / статистика      │
  │ Управление режимом, ЧС, подписка (ЮKassa)        │
  └───────────────────────────────────────────────┘
```

Принцип: сервер — мозг (ASR/LLM/SMS/push), телефон пенсионера — только микрофон,
спикерфон и колонка для TTS. Минимум логики на устройстве = минимум багов.

---

## 4. Технологический стек (MVP)

### Backend

- Python 3.11, FastAPI 0.115
- SQLite (через SQLAlchemy 2.0; БЕЗ Alembic на старте — схему пересоздаём)
- WebSocket — встроенный в FastAPI (только /ws/call и /ws/notify)
- httpx (async) для ASR/LLM/SMS/ЮKassa
- Токен: простой подписанный токен по device_id+pairing (не полный JWT-refresh-флоу)
- Деплой: один процесс под systemd на VPS, Caddy для авто-HTTPS (проще Nginx+certbot)
- БЕЗ Docker на старте, БЕЗ Alembic, БЕЗ Hilt-аналогов

### Android

- Kotlin + Jetpack Compose
- БЕЗ Hilt (зависимости вручную через простые синглтоны)
- Retrofit (REST) + OkHttp WebSocket (аудио-стрим)
- AudioRecord (PCM 16kHz mono) — БЕЗ Opus-кодека на старте (PCM проще; сжатие позже)
- Foreground Service (тип microphone) + AccessibilityService
- TextToSpeech (системный, бесплатно) для предупреждения пенсионеру
- FCM для push
- DataStore для локальных настроек

### Внешние сервисы


| Сервис                                            | Назначение                                         |
| ------------------------------------------------- | -------------------------------------------------- |
| OpenRouter STT (Whisper-large-v3)                 | ASR основной                                       |
| SaluteSpeech                                      | ASR fallback #1                                    |
| Neuro.net                                         | ASR fallback #2                                    |
| OpenRouter (gpt-4o-mini осн. / DeepSeek fallback) | классификация мошенничества                        |
| SMSAERO.ru                                           | экстренное SMS родственнику |
| FCM                                               | push родственнику           |
| ЮKassa                                            | подписка                    |
| VPS + Caddy                                       | хостинг + HTTPS             |


---

## 5. Модель данных (SQLite, минимум)

```
users(id, device_id UNIQUE, role['senior'|'relative'], phone NULL, token, created_at)
family_links(id, senior_id, relative_id, pairing_code, label,
             protection_mode['standard'], relative_phone, status, created_at)
calls(id, senior_id, caller_phone NULL, started_at, ended_at,
      verdict['safe'|'suspicious'|'scam'], threat_level INT, transcript TEXT)
alerts(id, call_id, relative_id, channels JSON, delivered BOOL, sent_at)
subscriptions(id, relative_id, plan, status, yookassa_sub_id, period_end)
```

Хранение транскрипта максимум 30 дней (152-ФЗ). Аудио НЕ храним вообще.

---

## 6. API

### REST

```
POST /api/senior/register      device_id -> pairing_code, token
POST /api/relative/register    device_id -> token
POST /api/family/pair          relative вводит pairing_code
POST /api/relative/phone       сохранить номер для SMS
GET  /api/calls/history?limit=50
GET  /api/calls/{id}           детали + транскрипт
PATCH /api/family/{id}/mode
POST /api/payments/checkout
POST /api/payments/yookassa/webhook
GET  /api/subscription/status
GET  /api/health
```

### WebSocket

```
WS /ws/call?token=...    senior шлёт аудио-чанки (бинарь PCM), получает {action:"tts", text:"..."}
WS /ws/notify?token=...  relative получает тревоги real-time (дублируется FCM-пушем)
```

### Doze mode contract

При Doze mode WS `/ws/notify` может закрыться. Alert доставляется через FCM high-priority push, WS — best-effort. Полагаться только на WS для критических тревог нельзя. При выходе из Doze WS восстанавливается за <5 секунд через NetworkCallback или `ACTION_DEVICE_IDLE_MODE_CHANGED`.

---

## 7. Логика захвата звонка на senior (Реализация A)

1. `ShieldAccessibilityService` ловит переход экрана дайлера в `CallState.ACTIVE` →
   определяет «идёт звонок», запускает `ShieldForegroundService`.
2. Спикерфон включается **кликом через Accessibility**: сервис обходит дерево
   `AccessibilityNodeInfo` дайлера (BFS), находит кнопку по id/description
   (`speaker`, `speakerphone`, `динамик`, `громкая связь` и т.д.) и вызывает
   `performAction(ACTION_CLICK)`. Повторные попытки: 200/500/1000/2000/3500 мс +
   триггер на `TYPE_WINDOW_CONTENT_CHANGED`. Если кнопка уже `isChecked` — не кликаем.
   `AudioManager.setSpeakerphoneOn()` / `setCommunicationDevice()` — **только fallback**,
   Telecom его игнорирует на Android 10+ (подтверждено логами).
3. `AudioRecord(VOICE_RECOGNITION, 16kHz, mono, PCM)` пишет звук из динамика
   (оба голоса — пенсионера и собеседника).
4. Буфер режется на чанки ~8 сек, каждый чанк → WS /ws/call.
5. По завершении звонка (Accessibility видит закрытие экрана дайлера) — стоп,
   финализация call на сервере.
6. Если сервер прислал `{action:"tts"}` — `TtsPlayer` проговаривает предупреждение
   в динамик, пенсионер слышит его прямо в разговоре.

Вендорские прошивки: на Transsion (Tecno/itel/Infinix) протестировано, работает.
Xiaomi/Huawei — дать пользователю-родственнику пошаговую инструкцию вручную
разрешить автозапуск и снять battery optimization. НЕ автоматизировать в MVP.

---

## 8. Серверный пайплайн (call_pipeline)

```
on_chunk(call_id, pcm_bytes):
    # ASR-цепочка: OpenRouter Whisper -> SaluteSpeech -> Neuro.net
    # (app/asr.py: transcribe() итерирует providers до первого непустого ответа)
    text = asr(pcm_bytes)
    if not text: return
    clean = pii_filter(text)          # regex: имена/номера/суммы -> маски
    accumulate transcript[call_id] += clean
    verdict = llm_classify(transcript[call_id])   # JSON: {label, score, flags[]}
    save partial verdict
    if verdict.label == "scam" and verdict.score >= 0.85:
        ws_send(senior, {"action":"tts", "text": WARNING_TEXT})
        fcm_push(relative, alert)
        smsaero_send(relative_phone, SMS_TEXT)
        mark alert delivered
```

LLM-промпт: few-shot + строгий JSON-выход + temperature 0. Классы схем:
SAFE_ACCOUNT (безопасный счёт), CB_OFFICER (служба безопасности банка),
POLICE_FSB, RELATIVE_TROUBLE (родственник в беде), PRIZE, COURIER. Один порог 0.85.

---

## 9. План разработки (реалистично 8–10 недель соло-вайбкодинг)


| Неделя | Фокус                                                                        | Результат                                   |
| ------ | ---------------------------------------------------------------------------- | ------------------------------------------- |
| 1      | Backend каркас: FastAPI, SQLite, регистрация, pairing, токен                 | Можно создать senior+relative и связать их  |
| 2      | ASR + LLM + PII-фильтр на ТЕКСТОВЫХ фикстурах (без аудио)                    | Транскрипт-заглушка -&gt; вердикт scam/safe |
| 3      | WS /ws/call (приём PCM) + пайплайн чанков + WS /ws/notify + SMSAERO.ru + FCM    | Сервер на тестовом аудио выдаёт тревогу+SMS |
| 4      | Android каркас: роль-селектор, регистрация, pairing, REST                    | Оба приложения логинятся и связываются      |
| 5      | Senior: AccessibilityService (детект звонка) + ForegroundService + спикерфон | Звонок детектится, спикерфон включается     |
| 6      | Senior: AudioRecord -&gt; чанки -&gt; WS /ws/call + TtsPlayer                | Реальный звук уходит на сервер, TTS играет  |
| 7      | Relative: full-screen тревога + история + транскрипт                         | Родственник видит тревогу и историю         |
| 8      | ЮKassa подписка + webhook + статус                                           | Платёж работает end-to-end                  |
| 9      | Стабилизация: reconnect WS, edge-cases, вендор-инструкции                    | Не падает на потере сети                    |
| 10     | Тест на 3–5 реальных семьях, фиксы                                           | Готово к узкому запуску                     |


Совет: недели 1–3 (сервер на текстовых фикстурах) дают работающий «мозг» до того,
как вы коснётесь самой сложной части — захвата звука. Если §2/§7 не заработает на
ваших устройствах, у вас уже есть ценный серверный продукт для пивота.

---

## 10. Не делаем в MVP

iOS · веб-дашборд · автосброс звонка · Opus-кодек · Postgres · Docker · Hilt ·
Alembic · Natasha NER · мультиязычность · кастомные MCP · хранение аудио ·
полный JWT-refresh · реализация B (захват линии).

---

## 11. Правила работы с GPT-5.4 / mini в Kodik

- GPT-5.4: Accessibility/Foreground/AudioRecord, WS-пайплайн, отладка «почему тишина».
- GPT-5.4 mini: CRUD-эндпоинты, Compose-экраны, схемы, тесты, рутина.
- Версии библиотек указывать явно. Сначала план -&gt; проверка -&gt; код.
- Никогда не принимать незапущенный код. После рабочей фичи — git commit.
- Этот файл прикреплять в контекст. Большой старый план — НЕ прикреплять.

---

## 12. MCP (минимум)

Старт: filesystem + github.
Разработка: + fetch (тест API), + sqlite.
Не нужно для MVP: docker, web-search, telegram, android-emulator, все кастомные MCP.

---

## 13. Юридический минимум (не пропускать)

- Явный экран согласия у ОБЕИХ ролей: senior соглашается на прослушивание звонков,
relative — на обработку. Без галочки — приложение не работает.
- Текст: что слушаем, зачем, что НЕ храним аудио, срок хранения транскрипта 30 дней.
- Запись/анализ разговора затрагивает вторую сторону линии — до публичного запуска
показать политику юристу. Для теста на «своих» семьях — допустимо с их согласия.

```

```

