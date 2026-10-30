import asyncio
import ctypes
import getpass
import json
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from maxpyin import AsyncMaxBot

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

APP_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "MyNotesApp")
DATA_FILE = os.path.join(APP_DIR, "notes_data.json")
INBOX_DIR = os.path.join(APP_DIR, "inbox")
TOKEN_FILE = os.path.join(APP_DIR, "max_bot_token.dpapi")


def _dpapi_transform(data: bytes, decrypt: bool) -> bytes:
    if os.name != "nt":
        raise RuntimeError("Зашифрованное хранение токена доступно только в Windows.")
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
        transform.argtypes = [ctypes.POINTER(DataBlob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DataBlob)]
    else:
        transform = crypt32.CryptProtectData
        transform.argtypes = [ctypes.POINTER(DataBlob), wintypes.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DataBlob)]
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
    print(f"Токен зашифрован: {TOKEN_FILE}")


def add_text_note(text: str) -> None:
    events = []
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as file:
            events = json.load(file)
    new_event = {
        "id": max((event["id"] for event in events), default=0) + 1,
        "title": f"Заметка из MAX: {text[:20]}...",
        "description": text,
        "datetime": datetime.now().isoformat(timespec="minutes"),
    }
    events.append(new_event)
    os.makedirs(APP_DIR, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=APP_DIR, delete=False) as file:
        temp = file.name
        json.dump(events, file, ensure_ascii=False, indent=2)
    os.replace(temp, DATA_FILE)
    print(f"Текстовая заметка сохранена: {text[:30]}")


def _attachment_path(url: str, prefix: str) -> str:
    suffix = Path(urlsplit(url or "").path).suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,10}", suffix):
        suffix = ".bin"
    return os.path.join(INBOX_DIR, f"{prefix}_{uuid4().hex}{suffix}")


async def main() -> None:
    token = _load_token()
    if not token:
        print("ОШИБКА: Токен не найден. Сначала выполните: python bot_receiver.py --configure-token")
        return

    async with AsyncMaxBot(token) as bot:
        me = await bot.get_me()
        print(f"Бот запущен: @{me.username}. Следим за папкой: {APP_DIR}")

        async for update in bot.poll(types=["message_created"]):
            if update.update_type != "message_created":
                continue

            message = update.message
            text = message.body.text if message.body else None
            chat_id = message.recipient.chat_id

            if text:
                add_text_note(text)
                await bot.send_message(
                    text="📝 Текст сохранен в Заметки!",
                    chat_id=chat_id
                )

            attachments = message.body.attachments if message.body else []
            for att in attachments:
                if att.type == "image":
                    os.makedirs(INBOX_DIR, exist_ok=True)
                    save_path = _attachment_path(att.payload.url, "image")
                    await bot.download_file(att.payload.url, save_path)
                    await bot.send_message(text="📸 Картинка сохранена!", chat_id=chat_id)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--configure-token", action="store_true")
    args = parser.parse_args()

    if args.configure_token:
        configure_token()
    else:
        asyncio.run(main())