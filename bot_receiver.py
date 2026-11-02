import ctypes
import getpass
import logging
import os
import re
import signal
import sys
import tempfile
import time
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import requests

# Настраиваем структурированное логирование
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("max-bot-receiver")

# Включаем поддержку русского языка в консоли Windows
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

APP_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "MyNotesApp")
DB_FILE = os.path.join(APP_DIR, "notes.db")
INBOX_DIR = os.path.join(APP_DIR, "inbox")
TOKEN_FILE = os.path.join(APP_DIR, "max_bot_token.dpapi")
CERT_PATH = os.path.join(os.path.dirname(__file__), "combined_ca.pem")
MAX_API_BASE_URL = "https://platform-api2.max.ru"
MAX_API_MIN_INTERVAL = 1 / 30
_last_api_request = 0.0

# Настраиваем сертификаты
if os.path.exists(CERT_PATH):
    os.environ["REQUESTS_CA_BUNDLE"] = CERT_PATH


@contextmanager
def _connect_db() -> Generator[sqlite3.Connection, None, None]:
    os.makedirs(APP_DIR, exist_ok=True)
    connection = sqlite3.connect(DB_FILE, timeout=10)
    try:
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            yield connection
    finally:
        connection.close()


# --- Шифрование токена (DPAPI) ---
def _dpapi_transform(data: bytes, decrypt: bool) -> bytes:
    if os.name != "nt":
        raise RuntimeError("Зашифрованное хранение доступно только в Windows.")
    from ctypes import wintypes

    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    buffer = ctypes.create_string_buffer(data)
    input_blob = DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    output_blob = DataBlob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    if decrypt:
        transform = crypt32.CryptUnprotectData
    else:
        transform = crypt32.CryptProtectData

    transform.argtypes = [
        ctypes.POINTER(DataBlob), ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(DataBlob),
    ]
    transform.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    if not transform(ctypes.byref(input_blob), None, None, None, None, 1, ctypes.byref(output_blob)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)

def _save_token(token: str) -> None:
    os.makedirs(APP_DIR, exist_ok=True)
    encrypted = _dpapi_transform(token.encode("utf-8"), decrypt=False)
    with tempfile.NamedTemporaryFile("wb", dir=APP_DIR, delete=False) as file:
        temp = file.name
        file.write(encrypted)
    os.replace(temp, TOKEN_FILE)

def _load_token() -> str | None:
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as file:
            encrypted = file.read()
        return _dpapi_transform(encrypted, decrypt=True).decode("utf-8")
    return os.environ.get("MAX_BOT_TOKEN")

def configure_token() -> None:
    token = getpass.getpass("Введите новый токен MAX (ввод скрыт): ").strip()
    if not token:
        raise ValueError("Токен не может быть пустым.")
    if token != getpass.getpass("Повторите ввод токена: ").strip():
        raise ValueError("Токены не совпадают; сохранение отменено.")
    _save_token(token)
    logger.info("Токен зашифрован и сохранен: %s", TOKEN_FILE)

# --- Работа с Базой Данных ---
def init_db():
    with _connect_db() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                description TEXT,
                created_at TEXT,
                remind_at TEXT,
                status TEXT DEFAULT 'active'
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                note_id INTEGER,
                file_path TEXT,
                file_type TEXT,
                original_name TEXT,
                FOREIGN KEY(note_id) REFERENCES notes(id) ON DELETE CASCADE
            )
        ''')
        conn.commit()

def add_text_note(text: str) -> int:
    with _connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO notes (title, description, created_at, status)
            VALUES (?, ?, ?, 'active')
        ''', (f"Заметка из MAX: {text[:20]}...", text, datetime.now().isoformat(timespec="minutes")))
        conn.commit()
        return cursor.lastrowid

def add_attachment(note_id: int, file_path: str, file_type: str, original_name: str):
    with _connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO attachments (note_id, file_path, file_type, original_name)
            VALUES (?, ?, ?, ?)
        ''', (note_id, file_path, file_type, original_name))
        conn.commit()

def _attachment_path(url: str, prefix: str) -> str:
    """Формирует путь для сохранения вложения с определением типа файла.
    
    Сначала пытается получить расширение из URL, если не удалось —
    использует prefix.
    """
    suffix = Path(urlsplit(url or "").path).suffix.lower()
    
    # Если URL не дал расширение — используем тип из payload
    if not re.fullmatch(r"\.[a-z0-9]{1,10}", suffix):
        type_map = {
            "image": "image",
            "photo": "image",
            "video": "video",
            "audio": "audio",
            "file": "file",
            "sticker": "sticker",
            "animation": "animation",
        }
        prefix = type_map.get(prefix.lower(), prefix)
    
    safe_prefix = re.sub(r"[^a-zA-Z0-9_-]", "_", str(prefix))[:32] or "attachment"
    return f"inbox/{safe_prefix}_{uuid4().hex}"


# Magic bytes для определения типов файлов
_MAGIC_SIGNATURES = {
    b"\xff\xd8\xff": ".jpg",
    b"\x89PNG\r\n\x1a\n": ".png",
    b"GIF87a": ".gif",
    b"GIF89a": ".gif",
    b"RIFF": None,  # WebP — проверяем дальше
    b"WEBP": ".webp",
    b"%PDF": ".pdf",
    b"\x1f\x8b": ".gz",
    b"PK\x03\x04": ".zip",  # также .docx, .xlsx, .pptx
    b"\xd0\xcf": ".doc",  # Microsoft Office
    b"\x00\x00\x01\x00": ".ico",
    b"\x00\x00\x00\x18\x66\x74\x79\x70\x68\x65\x63": ".heic",
}

_AUDIO_MAGIC = {
    b"\xff\xfb": ".mp3",
    b"ID3": ".mp3",
    b"\x4f\x72\x67\x61": ".ogg",
    b"FLaC": ".flac",
    b"\x52\x49\x46\x46": None,  # wav — проверяем дальше
    b"WEB": ".weba",
}

_VIDEO_MAGIC = {
    b"\x00\x00\x00\x18\x66\x74\x79\x70\x69\x73\x6f\x6d": ".mp4",
    b"\x00\x00\x00\x1c\x66\x74\x79\x70\x6d\x70\x34\x32": ".mp4",
    b"\x00\x00\x00\x14\x66\x74\x79\x70\x4d\x53\x4e\x56": ".mp4",
    b"\x00\x00\x00\x14\x66\x74\x79\x70\x69\x73\x6f\x6d": ".mp4",
    b"\x1a\x45\xdf\xa3": ".mkv",
    b"\x00\x00\x01\xb3": ".mpg",
    b"\x00\x00\x01\xb6": ".mpg",
    b"\x47\x49\x46": ".gif",  # animated gif
}


def _detect_extension_by_content(file_path: str) -> str:
    """Определяет расширение файла по magic bytes содержимого.
    
    Возвращает корректное расширение или ".bin" если тип не определён.
    """
    try:
        with open(file_path, "rb") as f:
            header = f.read(16)
    except (OSError, IOError):
        return ".bin"
    
    if not header:
        return ".bin"
    
    # Проверяем signatures
    for magic, ext in _MAGIC_SIGNATURES.items():
        if header.startswith(magic):
            if ext is None:
                # Нужна дополнительная проверка
                if magic == b"RIFF" and len(header) >= 12:
                    if header[8:12] == b"WEBP":
                        return ".webp"
                    if header[8:12] == b"AWAV":
                        return ".wav"
            else:
                return ext
    
    # Проверяем аудио
    for magic, ext in _AUDIO_MAGIC.items():
        if header.startswith(magic):
            if ext is None and magic == b"\x52\x49\x46\x46":
                if len(header) >= 12 and header[8:12] == b"AWAV":
                    return ".wav"
            else:
                return ext if ext else ".bin"
    
    # Проверяем видео
    for magic, ext in _VIDEO_MAGIC.items():
        if header.startswith(magic):
            return ext
    
    return ".bin"


def _fix_extension(file_path: str) -> str:
    """Исправляет расширение файла на основе его содержимого.
    
    Если файл имеет .bin расширение но содержимое указывает на другой тип —
    переименовывает файл с правильным расширением.
    """
    if not file_path.lower().endswith(".bin"):
        return file_path
    
    detected = _detect_extension_by_content(file_path)
    if detected == ".bin":
        return file_path
    
    # Переименовываем файл
    new_path = file_path.rsplit(".", 1)[0] + detected
    try:
        if os.path.exists(new_path):
            # Если файл с таким именем уже есть — добавляем UUID
            new_path = file_path.rsplit(".", 1)[0] + f"_{uuid4().hex[:8]}" + detected
        os.rename(file_path, new_path)
        logger.debug("Исправлено расширение: %s → %s", file_path, os.path.basename(new_path))
        return new_path
    except OSError as e:
        logger.warning("Не удалось переименовать файл: %s", e)
        return file_path

# --- Сетевые функции ---
def _wait_for_api_slot() -> None:
    global _last_api_request
    delay = MAX_API_MIN_INTERVAL - (time.monotonic() - _last_api_request)
    if delay > 0:
        time.sleep(delay)
    _last_api_request = time.monotonic()


def send_message(bot_token: str, chat_id: int, text: str) -> bool:
    if len(text) > 4000:
        logger.warning("Текст превышает лимит MAX в 4000 символов для chat_id=%d", chat_id)
        return False

    url = f"{MAX_API_BASE_URL}/messages"
    headers = {"Authorization": bot_token, "Content-Type": "application/json"}
    try:
        _wait_for_api_slot()
        response = requests.post(
            url, params={"chat_id": chat_id}, headers=headers, json={"text": text}, timeout=10
        )
        response.raise_for_status()
        return True
    except requests.RequestException as error:
        logger.error("Не удалось отправить сообщение chat_id=%d: %s", chat_id, error)
        return False


def send_message_with_split(bot_token: str, chat_id: int, text: str) -> int:
    """Отправить текст длиннее 4000 символов, разбив на несколько сообщений.
    
    Возвращает количество отправленных сообщений.
    """
    if len(text) <= 4000:
        if send_message(bot_token, chat_id, text):
            return 1
        return 0
    
    # Разбиваем по кодовым точкам (code points), а не байтам
    chars = list(text)
    parts: list[str] = []
    
    while len(chars) > 4000:
        # Ищем разрыв по пробелу или переносу строки во второй половине чанка
        cut = 4000
        last_newline = ''.join(chars[:cut]).rfind('\n')
        last_space = ''.join(chars[:cut]).rfind(' ')
        
        # Выбираем лучший разрыв (предпочитаем во второй половине)
        if last_newline > 2000:
            cut = last_newline + 1
        elif last_space > 2000:
            cut = last_space + 1
        
        parts.append(''.join(chars[:cut]))
        chars = chars[cut:]
    
    parts.append(''.join(chars))
    
    sent = 0
    for part in parts:
        if send_message(bot_token, chat_id, part):
            sent += 1
    
    return sent


def send_keyboard_message(bot_token: str, chat_id: int, text: str, buttons: list[dict]) -> bool:
    """Отправить сообщение с inline-кнопками.
    
    buttons: список кнопок, каждая - {"text": str, "callback": str}
    """
    import json
    
    # MAX лимит: ≤210 кнопок total, ≤30 рядов, ≤7 в ряду
    if len(buttons) > 210:
        logger.warning("Слишком много кнопок: %d (макс 210)", len(buttons))
        buttons = buttons[:210]
    
    # Формируем inline_keyboard
    keyboard = []
    row = []
    for i, btn in enumerate(buttons):
        row.append({
            "text": btn["text"][:128],
            "callback_button": {
                "callback": btn["callback"][:1024]
            }
        })
        if len(row) >= 7:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    
    url = f"{MAX_API_BASE_URL}/messages"
    headers = {"Authorization": bot_token, "Content-Type": "application/json"}
    body = {
        "text": text[:4000],
        "attachments": [
            {
                "type": "inline_keyboard",
                "payload": {"keyboard": keyboard}
            }
        ]
    }
    
    try:
        _wait_for_api_slot()
        response = requests.post(
            url, params={"chat_id": chat_id}, headers=headers, json=body, timeout=10
        )
        response.raise_for_status()
        return True
    except requests.RequestException as error:
        logger.error("Не удалось отправить сообщение с кнопками chat_id=%d: %s", chat_id, error)
        return False


def answer_callback(bot_token: str, callback_id: str, text: str | None = None) -> bool:
    """Ответ на нажатие кнопки (callback).
    
    Лимит: ≤2 ответов/сек на чат.
    """
    url = f"{MAX_API_BASE_URL}/answers"
    headers = {"Authorization": bot_token, "Content-Type": "application/json"}
    body: dict[str, Any] = {"callback_id": callback_id}
    if text:
        body["text"] = text[:1024]
    
    try:
        _wait_for_api_slot()
        response = requests.post(
            url, params={"callback_id": callback_id}, headers=headers, json=body, timeout=10
        )
        response.raise_for_status()
        return True
    except requests.RequestException as error:
        logger.error("Не удалось ответить на callback %s: %s", callback_id[:20], error)
        return False

def download_file(bot_token: str, url: str, save_path: str, max_retries: int = 3) -> bool:
    parsed_url = urlsplit(url)
    if parsed_url.scheme != "https" or not parsed_url.hostname:
        logger.warning("Недопустимый URL для скачивания: %s", url)
        return False

    headers = {}
    if parsed_url.hostname.lower() == "platform-api2.max.ru":
        headers["Authorization"] = bot_token

    temp_path = None
    for attempt in range(max_retries):
        try:
            full_path = os.path.realpath(os.path.join(APP_DIR, save_path))
            inbox_path = os.path.realpath(INBOX_DIR)
            if os.path.normcase(os.path.commonpath((inbox_path, full_path))) != os.path.normcase(inbox_path):
                raise ValueError("Недопустимый путь для вложения.")

            parent_dir = os.path.dirname(full_path)
            os.makedirs(parent_dir, exist_ok=True)
            if headers:
                _wait_for_api_slot()
            with requests.get(url, headers=headers, timeout=30, stream=True) as response:
                response.raise_for_status()
                with tempfile.NamedTemporaryFile("wb", dir=parent_dir, delete=False) as file:
                    temp_path = file.name
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            file.write(chunk)
            os.replace(temp_path, full_path)
            return True
        except (requests.RequestException, OSError, ValueError) as error:
            if isinstance(error, requests.HTTPError) and error.response is not None:
                # attachment.not.ready — пробуем повторить
                if error.response.status_code == 400 and "not.ready" in str(error.response.text):
                    wait_time = (attempt + 1) * 2
                    logger.info("Повторная попытка (attempt %d/%d) через %d с", attempt + 1, max_retries, wait_time)
                    time.sleep(wait_time)
                    continue
            # Удаляем временный файл только если это не retry
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError as cleanup_error:
                    logger.warning("Не удалось удалить временный файл: %s", cleanup_error)
                temp_path = None
            
            # Последняя попытка — возвращаем ошибку
            if attempt == max_retries - 1:
                if isinstance(error, requests.RequestException):
                    status = error.response.status_code if isinstance(error, requests.HTTPError) and error.response else None
                    detail = f"HTTP {status}" if status is not None else type(error).__name__
                    logger.error("Ошибка скачивания файла (%s): %s", detail, error)
                else:
                    logger.error("Ошибка скачивания файла: %s", error)
                return False


def _process_update(bot_token: str, update: dict[str, Any]) -> None:
    update_type = update.get("update_type")
    
    # Обрабатываем callback (нажатия кнопок)
    if update_type == "callback":
        callback = update.get("callback")
        if not isinstance(callback, dict):
            logger.debug("Пропущен callback без корректного объекта callback.")
            return
        
        callback_id = callback.get("callback_id")
        chat_id = callback.get("chat_id")
        message_id = callback.get("message_id")
        callback_data = callback.get("data")
        
        if not callback_id:
            logger.warning("Пропущен callback без callback_id.")
            return
        
        logger.info("Получен callback (chat_id=%d, message_id=%s, data=%s)", chat_id, message_id, callback_data)
        
        # Автоматически отвечаем на callback
        answer_callback(bot_token, callback_id, "✅ Обработано")
        return
    
    # Обрабатываем новые сообщения
    if update_type != "message_created":
        return

    message = update.get("message")
    if not isinstance(message, dict):
        logger.debug("Пропущено обновление без корректного message.")
        return

    sender = message.get("sender")
    if isinstance(sender, dict) and sender.get("is_bot"):
        logger.debug("Пропущено сообщение от бота.")
        return

    body = message.get("body")
    recipient = message.get("recipient")
    if not isinstance(body, dict) or not isinstance(recipient, dict):
        logger.warning("Пропущено обновление без body или recipient.")
        return

    chat_id = recipient.get("chat_id")
    if not isinstance(chat_id, int) or isinstance(chat_id, bool):
        logger.warning("Пропущено обновление без корректного chat_id.")
        return

    text = body.get("text")
    note_id = None
    if isinstance(text, str) and text:
        note_id = add_text_note(text)
        # Используем split для длинных текстов
        sent_count = send_message_with_split(bot_token, chat_id, "📝 Текст сохранен в Заметки!")
        logger.info("Сохранена текстовая заметка (chat_id=%d, note_id=%d, сообщений=%d)", chat_id, note_id, sent_count)

    attachments = body.get("attachments", [])
    if not isinstance(attachments, list):
        logger.warning("Поле attachments имеет неожиданный формат в chat_id=%d", chat_id)
        return

    for attachment in attachments:
        if not isinstance(attachment, dict):
            logger.warning("Пропущено вложение с неожиданным форматом в chat_id=%d", chat_id)
            continue

        attachment_type = attachment.get("type")
        payload = attachment.get("payload")
        if not isinstance(payload, dict):
            continue
        file_url = payload.get("url")
        if not isinstance(file_url, str) or not file_url:
            continue

        if note_id is None:
            note_id = add_text_note("[Вложение без текста]")

        save_path = _attachment_path(file_url, attachment_type or "attachment")
        if not download_file(bot_token, file_url, save_path):
            logger.warning("Не удалось скачать вложение в chat_id=%d", chat_id)
            continue

        # Исправляем расширение на основе содержимого файла
        full_path = os.path.join(APP_DIR, save_path)
        save_path = os.path.relpath(_fix_extension(full_path), APP_DIR)

        original_name = Path(urlsplit(file_url).path).name or f"{attachment_type}_{uuid4().hex[:6]}"
        add_attachment(note_id, save_path, str(attachment_type or "attachment"), original_name)
        
        # Отправляем уведомление с кнопками
        buttons = [
            {"text": "📁 Открыть папку", "callback": f"open:{save_path}"},
            {"text": "ℹ️ Информация", "callback": f"info:{attachment_type}"}
        ]
        send_keyboard_message(
            bot_token, chat_id, f"📎 Сохранено вложение ({attachment_type})!", buttons
        )
        logger.info("Сохранено вложение: %s (chat_id=%d)", save_path, chat_id)


# --- Главный цикл ---
_running = False  # Флаг для graceful shutdown

def _signal_handler(signum, frame):
    """Обработчик сигналов для graceful shutdown."""
    logger.info("Получен сигнал %d, завершение работы...", signum)
    _running = False

def main():
    global _running
    _running = True
    
    # Настраиваем обработчики сигналов
    for sig in (signal.SIGINT, signal.SIGTERM):
        if sys.platform != "win32":
            signal.signal(sig, _signal_handler)
    
    # Для Windows используем KeyboardInterrupt
    def windows_handler(sig, frame):
        logger.info("Получен сигнал прерывания, завершение работы...")
        _running = False
    
    if sys.platform == "win32":
        signal.signal(signal.SIGBREAK, windows_handler)
    
    logger.info("Инициализация базы данных: %s", DB_FILE)
    init_db()
    
    try:
        token = _load_token()
    except (OSError, RuntimeError, UnicodeError, ValueError) as error:
        logger.error("Не удалось прочитать сохраненный токен: %s", error)
        return

    if not token:
        logger.error("Токен не найден. Сначала выполните: python bot_receiver.py --configure-token")
        return

    token = token.strip()
    if not token:
        logger.error("Токен MAX пуст.")
        return

    logger.info("Бот запущен. База данных: %s", DB_FILE)
    marker = None
    headers = {"Authorization": token.strip(), "Content-Type": "application/json"}
    
    # Для отслеживания ошибок и backoff
    consecutive_errors = 0
    max_backoff = 60  # Максимальная задержка при ошибках

    while _running:
        # MAX требует интервал не менее 300 мс между запросами long polling.
        time.sleep(0.3)

        try:
            url = f"{MAX_API_BASE_URL}/updates"
            params = {"timeout": 30, "types": "message_created", "limit": 100}
            if marker is not None:
                params["marker"] = marker

            _wait_for_api_slot()
            response = requests.get(url, params=params, headers=headers, timeout=40)

            if response.status_code == 401:
                logger.error("401 Unauthorized: токен MAX неверный или отозван. Остановка.")
                break
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After", "1")
                try:
                    delay = max(1.0, float(retry_after))
                except ValueError:
                    delay = 1.0
                logger.warning("Превышен лимит запросов MAX. Повтор через %g с.", delay)
                time.sleep(delay)
                continue

            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("MAX API вернул неожиданный формат списка обновлений.")

            updates = data.get("updates")
            if not isinstance(updates, list):
                raise ValueError("MAX API вернул ответ без корректного списка updates.")

            marker = data.get("marker")
            
            # Сбрасываем счётчик ошибок при успешном получении
            consecutive_errors = 0

            for update in updates:
                if not _running:
                    break
                if not isinstance(update, dict):
                    logger.debug("Пропущено обновление с неожиданным форматом.")
                    continue
                try:
                    _process_update(token, update)
                except (requests.RequestException, sqlite3.Error, OSError, TypeError, ValueError) as error:
                    logger.error("Не удалось обработать обновление: %s", error, exc_info=True)

        except requests.exceptions.Timeout:
            # Таймаут Long Polling — это норма, просто продолжаем
            consecutive_errors = 0
            continue
        except KeyboardInterrupt:
            logger.info("Бот остановлен пользователем.")
            break
        except (requests.RequestException, sqlite3.Error, OSError, TypeError, ValueError) as e:
            consecutive_errors += 1
            # Экспоненциальный backoff при ошибках
            backoff = min(max_backoff, 2 ** consecutive_errors)
            logger.error("Ошибка в цикле бота (ошибок подряд: %d): %s. Повтор через %d с.", consecutive_errors, e, backoff)
            time.sleep(backoff)
    
    logger.info("Бот остановлен.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="MAX Messenger Bot Receiver")
    parser.add_argument("--configure-token", action="store_true", help="Конфигурация токена MAX")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO", help="Уровень логирования")
    parser.add_argument("--health-port", type=int, default=0, help="Порт для health check endpoint (0 = отключено)")
    args = parser.parse_args()

    # Настраиваем уровень логирования
    logger.setLevel(getattr(logging, args.log_level.upper()))

    if args.configure_token:
        configure_token()
    else:
        # Запускаем health check в отдельном потоке если указан порт
        if args.health_port > 0:
            import threading
            from http.server import HTTPServer, BaseHTTPRequestHandler
            
            class HealthHandler(BaseHTTPRequestHandler):
                def do_GET(self):
                    if self.path == "/health":
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(b'{"status": "ok"}')
                    else:
                        self.send_response(404)
                        self.end_headers()
                
                def log_message(self, format, *args):
                    logger.debug("Health check request: %s", args)
            
            health_server = HTTPServer(("127.0.0.1", args.health_port), HealthHandler)
            health_thread = threading.Thread(target=health_server.serve_forever, daemon=True)
            health_thread.start()
            logger.info("Health check запущен на порту %d", args.health_port)
        
        main()