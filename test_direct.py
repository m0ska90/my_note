# Добавляем корень проекта в sys.path для корректных импортов
import sys
import os

_project_root = os.path.dirname(os.path.abspath(__file__))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Загружаем .env ДО импорта config (он сам читает .env)
import config  # noqa: F401

import requests
import api_client
from api_client import MAX_API_BASE_URL
from config import APP_DATA_DIR, INBOX_DIR
from crypto_utils import TOKEN_FILE, load_token


def _check_token(token: str) -> int:
    """Проверить токен через MAX API /me и вывести результат."""
    try:
        response = requests.get(
            f"{MAX_API_BASE_URL}/me",
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


def main() -> int:
    token_from_file = None
    read_error = None

    try:
        token_from_file = load_token()
    except OSError as error:
        read_error = f"Ошибка чтения файла токена: {error}"
    except RuntimeError as error:
        read_error = f"Ошибка расшифровки токена (возможно, файл повреждён или создан другим пользователем Windows): {error}"
    except UnicodeError as error:
        read_error = f"Токен содержит некорректные символы после расшифровки: {error}"
    except ValueError as error:
        # Валидация токена не пройдена — токен содержит пробелы или управляющие символы
        print(f"Токен в файле {TOKEN_FILE} не прошёл валидацию: {error}")
        print("Рекомендация: пересохраните токен через меню настроек бота в приложении или выполните:")
        print("  python bot_receiver.py --configure-token")
        return 1

    if read_error:
        print(f"Не удалось прочитать сохраненный токен: {read_error}")
        return 1

    # Пробуем ENV как fallback
    env_token = os.environ.get("MAX_BOT_TOKEN", "")
    if not env_token:
        env_token = None

    if not token_from_file and not env_token:
        print("Токен не найден. Задайте MAX_BOT_TOKEN или выполните --configure-token.")
        return 1

    token = (token_from_file or env_token).strip()

    # Настраиваем сертификат через api_client
    cert_info = api_client._setup_cert()
    if cert_info:
        print(f"Используется файл сертификатов: {cert_info}")
    else:
        print("Файл combined_ca.pem не найден; используется хранилище сертификатов requests.")

    return _check_token(token)


if __name__ == "__main__":
    sys.exit(main())
