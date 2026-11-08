"""Безопасное хранение ключа шифрования базы данных.

Использует Windows DPAPI (CryptProtectData) для шифрования пароля.
Ключ привязан к пользователю и машине, как токен бота.
"""
import logging
import os
import tempfile

from crypto_utils import _dpapi_transform

logger = logging.getLogger("crypto_key")

# Путь к зашифрованному ключу шифрования БД
_DB_KEY_FILE = None  # устанавливается при импорте из config


def set_key_path(key_file: str) -> None:
    """Установить путь к файлу ключа (вызывается при инициализации)."""
    global _DB_KEY_FILE
    _DB_KEY_FILE = key_file


def _save_key(password: str) -> None:
    """Сохранить пароль, зашифрованный через DPAPI."""
    if not _DB_KEY_FILE:
        raise RuntimeError("Путь к ключу не установлен. Вызовите set_key_path().")

    encrypted = _dpapi_transform(password.encode("utf-8"), decrypt=False)
    os.makedirs(os.path.dirname(_DB_KEY_FILE), exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=os.path.dirname(_DB_KEY_FILE), delete=False) as file:
        temp = file.name
        file.write(encrypted)
    os.replace(temp, _DB_KEY_FILE)
    logger.info("Ключ шифрования БД сохранён: %s", _DB_KEY_FILE)


def _load_key() -> str | None:
    """Загрузить и расшифровать пароль."""
    if not _DB_KEY_FILE:
        raise RuntimeError("Путь к ключу не установлен. Вызовите set_key_path().")

    if os.path.exists(_DB_KEY_FILE):
        with open(_DB_KEY_FILE, "rb") as file:
            encrypted = file.read()
        return _dpapi_transform(encrypted, decrypt=True).decode("utf-8")
    return None


def get_or_create_key(min_length: int = 8) -> str:
    """Загрузить существующий ключ или запросить новый.

    Args:
        min_length: минимальная длина нового пароля.

    Returns:
        Расшифрованный пароль для SQLCipher.
    """
    existing = _load_key()
    if existing:
        logger.debug("Ключ шифрования БД найден в хранилище.")
        return existing

    # Ключа нет — запрашиваем
    import getpass

    while True:
        pwd1 = getpass.getpass("Введите пароль для шифрования базы данных (мин. {} символов): ".format(min_length)).strip()
        if len(pwd1) < min_length:
            print(f"Пароль слишком короткий. Минимум {min_length} символов.")
            continue
        pwd2 = getpass.getpass("Повторите ввод пароля: ").strip()
        if pwd1 != pwd2:
            print("Пароли не совпадают. Попробуйте снова.")
            continue
        _save_key(pwd1)
        logger.info("Новый ключ шифрования БД создан и сохранён.")
        return pwd1


def has_key() -> bool:
    """Проверить, сохранён ли ключ."""
    if not _DB_KEY_FILE:
        return False
    return os.path.exists(_DB_KEY_FILE)


def reset_key() -> bool:
    """Удалить сохранённый ключ. Возвращает True если ключ существовал."""
    if not _DB_KEY_FILE:
        return False
    if os.path.exists(_DB_KEY_FILE):
        os.remove(_DB_KEY_FILE)
        logger.info("Ключ шифрования БД удалён.")
        return True
    return False
