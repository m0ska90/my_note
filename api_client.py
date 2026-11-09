"""Общий клиент для запросов к MAX API.

Вынесенная логика:
- Загрузка сертификата (с поддержкой PyInstaller _MEIPASS)
- Создание сессии requests с нужными заголовками и CA bundle
- Rate-limit (не более 30 запросов в секунду)
- Константы API
"""
import os
import time
from pathlib import Path
from typing import Any

import requests

# ---------- Константы ----------
MAX_API_BASE_URL = "https://platform-api2.max.ru"
MAX_API_MIN_INTERVAL = 1 / 30  # 30 req/s

# ---------- Сертификат ----------
_RESOURCE_DIR = Path(__file__).resolve().parent
_CERT_PATH = str(_RESOURCE_DIR / "combined_ca.pem")


def _setup_cert() -> str | None:
    """Настроить CA bundle для requests.

    Возвращает путь к файлу сертификата или None.
    """
    if os.path.isfile(_CERT_PATH):
        os.environ["REQUESTS_CA_BUNDLE"] = _CERT_PATH
        return _CERT_PATH
    return None


# ---------- Rate-limit ----------
_last_api_request = 0.0


def _wait_for_api_slot() -> None:
    """Обеспечивает интервал между запросами к API MAX (≤30/sec)."""
    global _last_api_request
    delay = MAX_API_MIN_INTERVAL - (time.monotonic() - _last_api_request)
    if delay > 0:
        time.sleep(delay)
    _last_api_request = time.monotonic()


# ---------- Сессия ----------
def create_session(token: str, ca_bundle: str | None = None) -> requests.Session:
    """Создать настроенную сессию для запросов к MAX API.

    Args:
        token: токен аутентификации.
        ca_bundle: путь к CA bundle. Если None — используется ранее настроенный.
    """
    if ca_bundle:
        os.environ["REQUESTS_CA_BUNDLE"] = ca_bundle
    else:
        _setup_cert()

    session = requests.Session()
    session.headers.update({
        "Authorization": token,
        "Content-Type": "application/json",
    })
    return session
