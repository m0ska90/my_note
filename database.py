import os
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime

from config import APP_DATA_DIR, DB_FILE


@contextmanager
def _connect_db() -> Generator[sqlite3.Connection, None, None]:
    connection = sqlite3.connect(DB_FILE, timeout=10)
    try:
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            yield connection
    finally:
        connection.close()


def init_db() -> None:
    os.makedirs(APP_DATA_DIR, exist_ok=True)
    with _connect_db() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        cursor = conn.cursor()
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
            SELECT created_at, description
            FROM notes
            WHERE title LIKE 'Заметка из MAX%'
            ORDER BY id DESC
            """
        )
        return cursor.fetchall()


def clear_attachments() -> list[tuple]:
    with _connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT file_path FROM attachments")
        rows = cursor.fetchall()
        if rows:
            conn.execute("DELETE FROM attachments")
        return rows


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
