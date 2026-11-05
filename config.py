import logging
import os

# Настраиваем логирование при загрузке конфига
logger = logging.getLogger("config")

logger.debug("Загружен конфиг: APP_DATA_DIR=%s", os.environ.get("APPDATA", "Not set"))

APP_DATA_DIR = os.path.join(
    os.environ.get("APPDATA", os.path.expanduser("~")),
    "MyNotesApp",
)
DB_FILE = os.path.join(APP_DATA_DIR, "notes.db")
INBOX_DIR = os.path.join(APP_DATA_DIR, "inbox")
TOKEN_FILE = os.path.join(APP_DATA_DIR, "max_bot_token.dpapi")
DB_KEY_FILE = os.path.join(APP_DATA_DIR, "db_key.dpapi")
CERT_PATH = os.path.join(os.path.dirname(__file__), "combined_ca.pem")

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
