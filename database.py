"""Модуль работы с базой данных SQLite.

Поддерживает два режима:
- Зашифрованный (SQLCipher) — если pysqlcipher3 установлен
- Обычный (sqlite3) — fallback если SQLCipher недоступен
"""
import logging
import os
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from shutil import copy2

from config import APP_DATA_DIR, DB_FILE, DB_KEY_FILE

from crypto_key import get_or_create_key, set_key_path

# Устанавливаем путь к файлу ключа
set_key_path(DB_KEY_FILE)

logger = logging.getLogger("database")

# Проверяем доступность SQLCipher
_HAS_SQLCIPHER = False
try:
    import pysqlcipher3.dbapi2 as sqlcipher  # noqa: F401
    _HAS_SQLCIPHER = True
    logger.info("Режим шифрования БД: SQLCipher доступен.")
except ImportError:
    pass

# Глобальная ссылка на пароль ключа (в памяти, пока работает приложение)
_db_password: str | None = None


def _set_password(password: str) -> None:
    """Установить пароль для шифрования (вызывается из main.py)."""
    global _db_password
    _db_password = password


def _get_password() -> str:
    """Получить пароль ключа."""
    if not _db_password:
        _db_password = get_or_create_key()
    return _db_password


@contextmanager
def _connect_db() -> Generator[sqlite3.Connection, None, None]:
    """Подключиться к базе данных (шифрованной или обычной)."""
    password = _get_password() if _HAS_SQLCIPHER else None

    if _HAS_SQLCIPHER:
        connection = sqlite3.connect(DB_FILE, timeout=10)
        try:
            connection.execute("PRAGMA key = ?", (password,))
            connection.execute("PRAGMA busy_timeout = 10000")
            connection.execute("PRAGMA foreign_keys = ON")
            # Проверка что ключ верный
            connection.execute("SELECT count(*) FROM sqlite_master")
            with connection:
                yield connection
        except sqlite3.DatabaseError:
            connection.close()
            raise ValueError("Неверный пароль шифрования или повреждение базы данных.")
        finally:
            if connection and connection.closed == 0:
                connection.close()
    else:
        # Fallback: обычный sqlite3 без шифрования
        connection = sqlite3.connect(DB_FILE, timeout=10)
        try:
            connection.execute("PRAGMA busy_timeout = 10000")
            connection.execute("PRAGMA foreign_keys = ON")
            with connection:
                yield connection
        finally:
            connection.close()


def init_db() -> None:
    """Инициализировать схему БД (создать таблицы если не существуют)."""
    os.makedirs(APP_DATA_DIR, exist_ok=True)
    try:
        with _connect_db() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA foreign_keys = ON")
            cursor = conn.cursor()

            # Создаём таблицы если не существуют
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT,
                    description TEXT,
                    created_at TEXT,
                    remind_at TEXT,
                    status TEXT DEFAULT 'active'
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS attachments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    note_id INTEGER,
                    file_path TEXT,
                    file_type TEXT,
                    original_name TEXT,
                    FOREIGN KEY(note_id) REFERENCES notes(id) ON DELETE CASCADE
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY,
                    customer_name TEXT,
                    deadline TEXT,
                    file_path TEXT,
                    weight_grams REAL,
                    print_time_hours REAL,
                    material_type TEXT,
                    extra_services REAL,
                    total_price REAL,
                    note_id INTEGER,
                    filament_id INTEGER,
                    printer_id INTEGER,
                    FOREIGN KEY(note_id) REFERENCES notes(id) ON DELETE SET NULL,
                    FOREIGN KEY(filament_id) REFERENCES filaments(id) ON DELETE SET NULL,
                    FOREIGN KEY(printer_id) REFERENCES printers(id) ON DELETE SET NULL
                )
                """
            )
            # Миграция: добавляем note_id если столбца ещё нет
            _ensure_orders_note_id_column(conn)

            # Индексы для производительности
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_notes_remind_at ON notes(remind_at)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_notes_title ON notes(title)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_attachments_note_id ON attachments(note_id)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_orders_note_id ON orders(note_id)"
            )

            # --- Оборудование и пластик ---
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS printers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS filaments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    printer_id INTEGER NOT NULL,
                    material_type TEXT NOT NULL,
                    price_per_gram REAL,
                    FOREIGN KEY(printer_id) REFERENCES printers(id) ON DELETE CASCADE,
                    UNIQUE(printer_id, material_type)
                )
                """
            )
            # Миграция: добавляем note_id, filament_id, printer_id если столбцов ещё нет
            _ensure_orders_note_id_column(conn)
            _ensure_orders_filament_id_column(conn)
            _ensure_orders_printer_id_column(conn)

            # Индексы для orders (после миграций, когда столбцы уже есть)
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_orders_filament_id ON orders(filament_id)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_orders_printer_id ON orders(printer_id)"
            )

            # Инициализация оборудования
            _init_printers_and_filaments(conn)
    except ValueError:
        logger.error("Неверный пароль шифрования. Перезапустите и введите правильный пароль.")
        raise


def _ensure_orders_note_id_column(conn) -> None:
    """Добавить столбец note_id в orders если его ещё нет (миграция)."""
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("ALTER TABLE orders ADD COLUMN note_id INTEGER")
        conn.execute(
            "ALTER TABLE orders ADD CONSTRAINT fk_orders_note "
            "FOREIGN KEY(note_id) REFERENCES notes(id) ON DELETE SET NULL"
        )
        logger.info("Миграция: добавлен столбец note_id в таблицу orders.")
    except sqlite3.OperationalError as e:
        # Столбец уже существует или ошибка ограничений — игнорируем
        if "duplicate column" not in str(e).lower():
            logger.debug(" orders note_id check: %s", e)


def _ensure_orders_filament_id_column(conn) -> None:
    """Добавить столбец filament_id в orders если его ещё нет (миграция)."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(orders)")}
    if "filament_id" not in columns:
        conn.execute("ALTER TABLE orders ADD COLUMN filament_id INTEGER")
        logger.info("Миграция: добавлен столбец filament_id в таблицу orders.")


def _ensure_orders_printer_id_column(conn) -> None:
    """Добавить столбец printer_id в orders если его ещё нет (миграция)."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(orders)")}
    if "printer_id" not in columns:
        conn.execute("ALTER TABLE orders ADD COLUMN printer_id INTEGER")
        logger.info("Миграция: добавлен столбец printer_id в таблицу orders.")


# ================================================================
# ОБОРУДОВАНИЕ И ПЛАСТИК
# ================================================================

def _init_printers_and_filaments(conn) -> None:
    """Заполнить таблицы printers и filaments начальными данными (если пусто)."""
    cursor = conn.cursor()

    # 1. Принтеры
    default_printers = [
        "Elegoo Centauri Carbon",
        "Elegoo Centauri Carbon 2",
    ]
    for name in default_printers:
        try:
            cursor.execute(
                "INSERT INTO printers (name) VALUES (?)", (name,)
            )
            logger.info("Принтер добавлен: %s", name)
        except sqlite3.IntegrityError:
            pass  # уже существует

    # 2. Пластик для каждого принтера
    default_filaments = [
        ("PLA", 2.0),
        ("PETG", 2.5),
        ("ABS", 2.3),
        ("TPU", 3.0),
    ]

    cursor.execute("SELECT id FROM printers")
    printers = cursor.fetchall()

    for (printer_id,) in printers:
        for material, price in default_filaments:
            try:
                cursor.execute(
                    """
                    INSERT INTO filaments (printer_id, material_type, price_per_gram)
                    VALUES (?, ?, ?)
                    """,
                    (printer_id, material, price),
                )
            except sqlite3.IntegrityError:
                pass  # уже существует


def get_all_printers() -> list[tuple]:
    """Вернуть список всех принтеров: (id, name)."""
    with _connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM printers ORDER BY name")
        return cursor.fetchall()


def get_filaments_by_printer(printer_id: int) -> list[tuple]:
    """Вернуть список пластиков для принтера: (id, material_type, price_per_gram)."""
    with _connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, material_type, price_per_gram
            FROM filaments
            WHERE printer_id = ?
            ORDER BY material_type
            """,
            (printer_id,),
        )
        return cursor.fetchall()


def get_filament_by_type(printer_id: int, material_type: str) -> tuple | None:
    """Найти пластиков по типу и принтеру: (id, material_type, price_per_gram) или None.

    material_type — регистронезависимый поиск.
    """
    with _connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, material_type, price_per_gram
            FROM filaments
            WHERE printer_id = ? AND LOWER(material_type) = LOWER(?)
            """,
            (printer_id, material_type),
        )
        return cursor.fetchone()


def update_filament_price(filament_id: int, price_per_gram: float) -> None:
    """Сохранить фактическую цену за грамм."""
    with _connect_db() as conn:
        conn.execute(
            "UPDATE filaments SET price_per_gram = ? WHERE id = ?",
            (price_per_gram, filament_id),
        )


def get_filament_price(filament_id: int) -> float:
    """Вернуть цену за грамм для пластика.

    Если price_per_gram == NULL — возвращает дефолтную цену 2.0 руб/г.
    """
    with _connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT price_per_gram FROM filaments WHERE id = ?",
            (filament_id,),
        )
        row = cursor.fetchone()
        if row and row[0] is not None:
            return float(row[0])
        return 2.0  # Дефолтная цена


def migrate_from_plaintext(password: str | None = None) -> bool:
    """Мигрировать нешифрованную БД в зашифрованную.

    Создаёт резервную копию оригинала и копирует данные в новую БД.
    Если SQLCipher недоступен — просто возвращает False (миграция не нужна).

    Args:
        password: пароль шифрования. Если None — запрашивается.

    Returns:
        True если миграция выполнена, False если не нужна.
    """
    if not _HAS_SQLCIPHER:
        logger.info("SQLCipher недоступен — БД остаётся нешифрованной.")
        return False

    if not os.path.exists(DB_FILE):
        logger.info("Новая база данных — миграция не нужна.")
        return False

    # Проверяем, зашифрована ли уже БД
    try:
        with _connect_db() as conn:
            conn.execute("SELECT count(*) FROM notes")
        logger.info("База данных уже зашифрована, миграция не нужна.")
        return False
    except ValueError:
        pass

    if password is None:
        password = get_or_create_key()

    logger.info("Начата миграция нешифрованной БД в зашифрованную...")

    try:
        import pysqlcipher3.dbapi2 as sqlcipher
    except ImportError:
        logger.error("pysqlcipher3 не установлен. Установите: pip install pysqlcipher3")
        return False

    # Резервная копия оригинала
    backup_path = f"{DB_FILE}.plaintext.backup"
    copy2(DB_FILE, backup_path)
    logger.info("Резервная копия создана: %s", backup_path)

    try:
        # Подключаемся к существующей БД без пароля (для чтения)
        plain_conn = sqlite3.connect(DB_FILE, timeout=10)
        plain_cursor = plain_conn.cursor()

        # Проверяем что таблицы существуют
        plain_cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in plain_cursor.fetchall()}
        plain_conn.close()

        if "notes" not in tables:
            logger.info("Таблица notes не найдена — база пуста, создаём зашифрованную.")
            return True

        # Открываем новую БД с шифрованием
        encrypted_conn = sqlcipher.connect(DB_FILE, timeout=10)
        encrypted_conn.execute("PRAGMA key = ?", (password,))
        encrypted_conn.execute("PRAGMA journal_mode = WAL")
        encrypted_conn.execute("PRAGMA foreign_keys = ON")

        # Создаём схему
        enc_cursor = encrypted_conn.cursor()
        enc_cursor.execute(
            """
            CREATE TABLE notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                description TEXT,
                created_at TEXT,
                remind_at TEXT,
                status TEXT DEFAULT 'active'
            )
            """
        )
        enc_cursor.execute(
            """
            CREATE TABLE attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                note_id INTEGER,
                file_path TEXT,
                file_type TEXT,
                original_name TEXT,
                FOREIGN KEY(note_id) REFERENCES notes(id) ON DELETE CASCADE
            )
            """
        )
        enc_cursor.execute(
            "CREATE INDEX idx_notes_remind_at ON notes(remind_at)"
        )
        enc_cursor.execute(
            "CREATE INDEX idx_notes_title ON notes(title)"
        )
        enc_cursor.execute(
            "CREATE INDEX idx_attachments_note_id ON attachments(note_id)"
        )

        # Копируем данные из notes
        plain_conn = sqlite3.connect(DB_FILE, timeout=10)
        plain_cursor = plain_conn.cursor()
        plain_cursor.execute("SELECT id, title, description, created_at, remind_at, status FROM notes")
        notes_rows = plain_cursor.fetchall()
        plain_conn.close()

        if notes_rows:
            enc_cursor.executemany(
                """INSERT INTO notes (id, title, description, created_at, remind_at, status)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                notes_rows,
            )

        # Копируем данные из attachments
        plain_conn = sqlite3.connect(DB_FILE, timeout=10)
        plain_cursor = plain_conn.cursor()
        plain_cursor.execute("SELECT id, note_id, file_path, file_type, original_name FROM attachments")
        attachment_rows = plain_cursor.fetchall()
        plain_conn.close()

        if attachment_rows:
            enc_cursor.executemany(
                """INSERT INTO attachments (id, note_id, file_path, file_type, original_name)
                   VALUES (?, ?, ?, ?, ?)""",
                attachment_rows,
            )

        encrypted_conn.commit()
        encrypted_conn.close()

        logger.info(
            "Миграция завершена: %d заметок, %d вложений скопировано.",
            len(notes_rows), len(attachment_rows),
        )
        return True

    except Exception as e:
        logger.error("Ошибка миграции: %s. Восстановлена резервная копия.", e)
        # Восстанавливаем оригинал
        if os.path.exists(backup_path):
            copy2(backup_path, DB_FILE)
            os.remove(backup_path)
        return False


def get_all_events() -> list[tuple]:
    with _connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, title, description, remind_at
            FROM notes
            WHERE title NOT LIKE 'Заметка из MAX%'
            ORDER BY remind_at
            """
        )
        return cursor.fetchall()


def get_reminders() -> list[tuple]:
    with _connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, title, description, remind_at
            FROM notes
            WHERE remind_at IS NOT NULL
              AND title NOT LIKE 'Заметка из MAX%'
            """
        )
        return cursor.fetchall()


def get_event(note_id: int) -> tuple | None:
    with _connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, title, description, remind_at FROM notes WHERE id = ?",
            (note_id,),
        )
        return cursor.fetchone()


def add_event(title: str, description: str, remind_at: str) -> None:
    with _connect_db() as conn:
        conn.execute(
            """
            INSERT INTO notes (title, description, remind_at, created_at, status)
            VALUES (?, ?, ?, ?, 'active')
            """,
            (title, description, remind_at, datetime.now().isoformat()),
        )


def update_event(note_id: int, title: str, description: str, remind_at: str) -> None:
    with _connect_db() as conn:
        conn.execute(
            """
            UPDATE notes
            SET title = ?, description = ?, remind_at = ?
            WHERE id = ?
            """,
            (title, description, remind_at, note_id),
        )


def delete_event(note_id: int) -> None:
    with _connect_db() as conn:
        conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))


def add_order(
    customer_name: str,
    deadline: str,
    file_path: str,
    weight_grams: float,
    print_time_hours: float,
    material_type: str,
    extra_services: float,
    total_price: float,
    note_id: int | None = None,
    filament_id: int | None = None,
    printer_id: int | None = None,
) -> None:
    with _connect_db() as conn:
        conn.execute(
            """
            INSERT INTO orders (
                customer_name, deadline, file_path, weight_grams,
                print_time_hours, material_type, extra_services, total_price, note_id, filament_id, printer_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                customer_name,
                deadline,
                file_path,
                weight_grams,
                print_time_hours,
                material_type,
                extra_services,
                total_price,
                note_id,
                filament_id,
                printer_id,
            ),
        )


def get_all_orders() -> list[tuple]:
    with _connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, customer_name, deadline, file_path, weight_grams,
                   print_time_hours, material_type, extra_services, total_price, note_id, filament_id, printer_id
            FROM orders
            ORDER BY id DESC
            """
        )
        return cursor.fetchall()


def get_note_text_by_order_id(order_id: int) -> str | None:
    """Вернуть текст описания заметки, связанной с заказом.

    Args:
        order_id: ID заказа.

    Returns:
        Текст описания из notes или None если не найден.
    """
    with _connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT n.description
            FROM orders o
            LEFT JOIN notes n ON o.note_id = n.id
            WHERE o.id = ?
            """,
            (order_id,),
        )
        row = cursor.fetchone()
        return row[0] if row else None


def delete_order(order_id: int) -> None:
    with _connect_db() as conn:
        conn.execute("DELETE FROM orders WHERE id = ?", (order_id,))


def delete_past_events(now: str) -> None:
    with _connect_db() as conn:
        conn.execute(
            """
            DELETE FROM notes
            WHERE remind_at <= ?
              AND title NOT LIKE 'Заметка из MAX%'
            """,
            (now,),
        )


def get_inbox_attachments() -> list[tuple]:
    with _connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT a.file_path, a.original_name, n.title
            FROM attachments a
            JOIN notes n ON a.note_id = n.id
            """
        )
        return cursor.fetchall()


def get_max_text_notes() -> list[tuple]:
    with _connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, created_at, description
            FROM notes
            WHERE title LIKE 'Заметка из MAX%'
            ORDER BY id DESC
            """
        )
        return cursor.fetchall()


def clear_max_text_notes() -> int:
    """Удалить все заметки из MAX и вернуть количество удалённых записей.

    Returns:
        Количество удалённых записей.
    """
    with _connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM notes WHERE title LIKE 'Заметка из MAX%'"
        )
        return cursor.rowcount


def clear_attachments(inbox_dir: str) -> list[tuple]:
    """Удалить все записи вложений и вернуть удалённые пути.

    Args:
        inbox_dir: путь к директории вложений для валидации (защита от path traversal).

    Returns:
        Список (file_path,) для удалённых записей.
    """
    import logging
    logger = logging.getLogger("db")

    clean_rows = []
    with _connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT file_path FROM attachments")
        rows = cursor.fetchall()

        if rows:
            # Валидация путей перед удалением записей из БД
            real_inbox = os.path.realpath(inbox_dir)
            for (file_path,) in rows:
                clean_path = os.path.normpath(file_path)
                if os.path.isabs(clean_path) or clean_path.startswith(".."):
                    logger.warning("Пропуск подозрительного пути в БД: %s", file_path)
                    continue
                full_path = os.path.realpath(os.path.join(inbox_dir, clean_path))
                if not full_path.startswith(real_inbox + os.sep):
                    logger.warning("Пропуск path traversal в БД: %s", file_path)
                    continue
                clean_rows.append((file_path,))

            if clean_rows:
                conn.execute("DELETE FROM attachments")

    return clean_rows


def add_max_text_note(text: str) -> int:
    with _connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO notes (title, description, created_at, status)
            VALUES (?, ?, ?, 'active')
            """,
            (
                f"Заметка из MAX: {text[:20]}...",
                text,
                datetime.now().isoformat(timespec="minutes"),
            ),
        )
        return cursor.lastrowid


def add_attachment(
    note_id: int,
    file_path: str,
    file_type: str,
    original_name: str,
) -> None:
    with _connect_db() as conn:
        conn.execute(
            """
            INSERT INTO attachments (note_id, file_path, file_type, original_name)
            VALUES (?, ?, ?, ?)
            """,
            (note_id, file_path, file_type, original_name),
        )


def database_signature() -> tuple:
    signature = []
    for path in (DB_FILE, f"{DB_FILE}-wal"):
        try:
            stat = os.stat(path)
        except FileNotFoundError:
            signature.append(None)
        else:
            signature.append((stat.st_mtime_ns, stat.st_size))
    return tuple(signature)
