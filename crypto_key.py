"""Безопасное хранение ключа шифрования базы данных.

Использует Windows DPAPI (CryptProtectData) для шифрования пароля.
Ключ привязан к пользователю и машине, как токен бота.
"""
import logging
import os
import tempfile

logger = logging.getLogger("crypto_key")

# Путь к зашифрованному ключу шифрования БД
_DB_KEY_FILE = None  # устанавливается при импорте из config


def set_key_path(key_file: str) -> None:
    """Установить путь к файлу ключа (вызывается при инициализации)."""
    global _DB_KEY_FILE
    _DB_KEY_FILE = key_file


def _dpapi_transform(data: bytes, decrypt: bool) -> bytes:
    """Шифрование/дешифрование через Windows DPAPI."""
    if os.name != "nt":
        raise RuntimeError("DPAPI доступен только на Windows.")
    from ctypes import wintypes
    import ctypes

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
