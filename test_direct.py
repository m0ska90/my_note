# Добавляем корень проекта в sys.path для корректных импортов
import sys
import os
_project_root = os.path.dirname(os.path.abspath(__file__))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import os
from pathlib import Path

CERT_PATH = Path(__file__).with_name("combined_ca.pem")
if CERT_PATH.is_file():
    os.environ["REQUESTS_CA_BUNDLE"] = str(CERT_PATH)

# Загружаем .env ДО импорта config/bot_receiver (они читают env-переменные)
import config  # noqa: F401

import requests
from bot_receiver import _load_token


def main() -> int:
    try:
        token = (_load_token() or "").strip()
    except (OSError, RuntimeError, UnicodeError, ValueError) as error:
        print(f"Не удалось прочитать сохраненный токен: {error}")
        return 1

    if not token:
        print("Токен не найден. Задайте MAX_BOT_TOKEN или выполните --configure-token.")
        return 1

    if CERT_PATH.is_file():
        print(f"Используется файл сертификатов: {CERT_PATH}")
    else:
        print("Файл combined_ca.pem не найден; используется хранилище сертификатов requests.")

    try:
        # Пробуем без Bearer - MAX API принимает только токен
        response = requests.get(
            "https://platform-api2.max.ru/me",
            headers={"Authorization": token},
            timeout=10,
        )
    except requests.RequestException as error:
        print(f"Ошибка запроса к MAX API ({type(error).__name__}): {error}")
        return 1

    print(f"HTTP-статус: {response.status_code}")

    if response.status_code == 200:
        try:
            profile = response.json()
        except ValueError:
            print("API ответил успешно, но вернул некорректный JSON.")
            return 1

        if not isinstance(profile, dict):
            print("API ответил успешно, но формат профиля неожиданный.")
            return 1

        username = profile.get("username")
        print("Токен принят, API отвечает.")
        if username:
            print(f"Бот: @{username}")
        return 0

    if response.status_code == 401:
        print("Ошибка аутентификации: проверьте токен в MAX.")
    elif response.status_code == 429:
        print("Превышен лимит запросов; повторите проверку позже.")
    else:
        print("MAX API вернул ошибку; тело ответа скрыто, чтобы не выводить лишние данные.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
