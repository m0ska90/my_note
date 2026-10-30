import asyncio
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from maxbot.bot import Bot
from maxbot.dispatcher import Dispatcher
from maxbot.types import Attachment, Message


APP_DIR = os.path.join(
    os.environ.get("APPDATA", os.path.expanduser("~")), "MyNotesApp")
DATA_FILE = os.path.join(APP_DIR, "notes_data.json")
INBOX_DIR = os.path.join(APP_DIR, "inbox")


def _read_events() -> list[dict]:
    if not os.path.exists(DATA_FILE):
        return []

    with open(DATA_FILE, "r", encoding="utf-8") as file:
        events = json.load(file)

    if not isinstance(events, list):
        raise ValueError(f"Файл заметок должен содержать список: {DATA_FILE}")

    event_ids: set[int] = set()
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("Запись заметки должна быть объектом")
        event_id = event.get("id")
        if (not isinstance(event_id, int) or isinstance(event_id, bool)
                or event_id in event_ids):
            raise ValueError("Идентификаторы заметок некорректны")
        if not isinstance(event.get("title"), str):
            raise ValueError("У заметки отсутствует название")
        event_datetime = event.get("datetime")
        if not isinstance(event_datetime, str):
            raise ValueError("У заметки отсутствуют дата и время")
        parsed_datetime = datetime.fromisoformat(event_datetime)
        if parsed_datetime.tzinfo is not None:
            raise ValueError("Дата заметки должна быть без часового пояса")
        if not isinstance(event.get("description", ""), str):
            raise ValueError("Описание заметки должно быть текстом")
        event_ids.add(event_id)

    return events


def add_text_note(text: str) -> None:
    """Append a text note using the format expected by the desktop app."""
    events = _read_events()
    new_event = {
        "id": max((event["id"] for event in events), default=0) + 1,
        "title": f"Заметка из MAX: {text[:20]}...",
        "description": text,
        "datetime": datetime.now().isoformat(timespec="minutes"),
    }
    events.append(new_event)

    os.makedirs(APP_DIR, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=APP_DIR, delete=False) as file:
            temporary_path = file.name
            json.dump(events, file, ensure_ascii=False, indent=2)
        os.replace(temporary_path, DATA_FILE)
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.remove(temporary_path)

    print(f"Текстовая заметка сохранена: {text[:30]}")


def _attachment_path(attachment: Attachment, prefix: str) -> str:
    suffix = Path(urlsplit(attachment.url or "").path).suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,10}", suffix):
        suffix = ".bin"
    filename = f"{prefix}_{uuid4().hex}{suffix}"
    return os.path.join(INBOX_DIR, filename)


async def handle_message(msg: Message, bot: Bot) -> None:
    chat_id = msg.chat.id
    if msg.text:
        add_text_note(msg.text)
        await bot.send_message(chat_id=chat_id, text="📝 Текст сохранен в Заметки!")

    images = msg.get_attachments("image")
    if images:
        os.makedirs(INBOX_DIR, exist_ok=True)
        for image in images:
            save_path = _attachment_path(image, "image")
            await image.download(bot, save_path)
            print(f"Картинка сохранена: {save_path}")
        await bot.send_message(
            chat_id=chat_id, text=f"📸 Сохранено картинок: {len(images)}")

    files = msg.get_attachments("file")
    if files:
        os.makedirs(INBOX_DIR, exist_ok=True)
        for attachment in files:
            save_path = _attachment_path(attachment, "file")
            await attachment.download(bot, save_path)
            print(f"Файл сохранен: {save_path}")
        await bot.send_message(
            chat_id=chat_id, text=f"📎 Сохранено файлов: {len(files)}")


def create_dispatcher(bot: Bot) -> Dispatcher:
    dispatcher = Dispatcher(bot)

    @dispatcher.message()
    async def on_message(msg: Message) -> None:
        await handle_message(msg, bot)

    return dispatcher


async def main() -> None:
    token = os.environ.get("MAX_BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "Укажите токен бота в переменной окружения MAX_BOT_TOKEN.")

    bot = Bot(token)
    dispatcher = create_dispatcher(bot)
    print(f"Бот запущен. Следим за папкой: {APP_DIR}")
    await dispatcher.run_polling()


if __name__ == "__main__":
    asyncio.run(main())
