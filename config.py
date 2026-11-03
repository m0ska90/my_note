import os


APP_DATA_DIR = os.path.join(
    os.environ.get("APPDATA", os.path.expanduser("~")),
    "MyNotesApp",
)
DB_FILE = os.path.join(APP_DATA_DIR, "notes.db")
INBOX_DIR = os.path.join(APP_DATA_DIR, "inbox")
TOKEN_FILE = os.path.join(APP_DATA_DIR, "max_bot_token.dpapi")
CERT_PATH = os.path.join(os.path.dirname(__file__), "combined_ca.pem")

os.makedirs(APP_DATA_DIR, exist_ok=True)
os.makedirs(INBOX_DIR, exist_ok=True)

BG_MAIN = "#f2f2f2"
BG_PANEL = "#ffffff"
BG_BUTTON = "#e0e0e0"
FG_TEXT = "#090202"
COLOR_DONE = "red"
ALPHA = 1.0
APP_FONT = ("Segoe UI", 14)

CHECK_INTERVAL = 30
WARN_BEFORE = 60

HWND_BOTTOM = 1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SW_SHOW = 5
SW_RESTORE = 9
