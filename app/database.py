"""Подключение к базе данных SQLite и создание таблиц."""
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import DB_FILE

# Адрес базы: обычный файл SQLite рядом с проектом.
DATABASE_URL = f"sqlite:///{DB_FILE}"

# engine — это "соединение" с базой.
# check_same_thread=False нужно SQLite при работе с FastAPI.
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

# Фабрика сессий: через неё мы будем читать/писать данные.
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

# Базовый класс, от которого наследуются все модели (таблицы).
Base = declarative_base()


def _add_column_if_missing(table_name: str, column_name: str, column_sql: str) -> None:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if table_name not in table_names:
        return

    column_names = {column["name"] for column in inspector.get_columns(table_name)}
    if column_name in column_names:
        return

    with engine.begin() as connection:
        connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}"))


def _upgrade_sqlite_schema() -> None:
    """Добавляет недостающие столбцы в существующую SQLite-схему MVP."""
    _add_column_if_missing(
        "family_links",
        "pairing_expires_at",
        "pairing_expires_at DATETIME",
    )
    _add_column_if_missing("users", "fcm_token", "fcm_token VARCHAR")


def init_db() -> None:
    """Создаёт все таблицы в базе, если их ещё нет."""
    # Импортируем модели, чтобы SQLAlchemy узнал о таблицах.
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _upgrade_sqlite_schema()


def get_db():
    """Отдаёт сессию базы на время одного запроса и закрывает её после."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
