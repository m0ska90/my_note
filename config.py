import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Загружаем переменные из .env файла
if getattr(sys, "frozen", False):
    _env_path = Path(sys.executable).resolve().parent / ".env"
else:
    _env_path = Path(__file__).resolve().parent / ".env"
if _env_path.is_file():
    load_dotenv(_env_path, override=True)

# Настраиваем логирование при загрузке конфига
logger = logging.getLogger("config")

logger.debug("Загружен конфиг: APP_DATA_DIR=%s", os.environ.get("APPDATA", "Not set"))

USER_DATA_DIR = os.environ.get("APPDATA", os.path.expanduser("~"))
APP_DATA_DIR = os.path.join(USER_DATA_DIR, "Заказики")
DB_FILE = os.path.join(APP_DATA_DIR, "notes.db")
INBOX_DIR = os.path.join(APP_DATA_DIR, "inbox")
TOKEN_FILE = os.path.join(USER_DATA_DIR, "MyNotesApp", "max_bot_token.dpapi")
DB_KEY_FILE = os.path.join(APP_DATA_DIR, "db_key.dpapi")
_resource_dir = Path(
    getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)
)
CERT_PATH = str(_resource_dir / "combined_ca.pem")

os.makedirs(APP_DATA_DIR, exist_ok=True)
os.makedirs(INBOX_DIR, exist_ok=True)

BG_MAIN = "#f2f2f2"
BG_PANEL = "#ffffff"
BG_BUTTON = "#e0e0e0"
FG_TEXT = "#090202"
COLOR_DONE = "red"
ALPHA = 1.0
APP_FONT = ("Segoe UI", 20)

CHECK_INTERVAL = 30
WARN_BEFORE = 60

SW_RESTORE = 9
SW_SHOW = 5
