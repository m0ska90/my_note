"""DPAPI-backed storage for the MAX bot token."""

import ctypes
import os
import tempfile
from pathlib import Path

from config import APP_DATA_DIR, TOKEN_FILE

TOKEN_FILE = Path(TOKEN_FILE)
TOKEN_DIR = TOKEN_FILE.parent
_LEGACY_TOKEN_FILE = Path(APP_DATA_DIR) / "max_bot_token.dpapi"


def _dpapi_transform(data: bytes, decrypt: bool) -> bytes:
    """Encrypt or decrypt bytes using the current Windows user's DPAPI."""
    if os.name != "nt":
        raise RuntimeError("DPAPI доступен только на Windows.")

    from ctypes import wintypes

    class DataBlob(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_byte)),
        ]

    buffer = ctypes.create_string_buffer(data)
    input_blob = DataBlob(
        len(data),
        ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)),
    )
    output_blob = DataBlob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    transform = (
        crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    )
    transform.argtypes = [
        ctypes.POINTER(DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(DataBlob),
    ]
    transform.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    if not transform(
        ctypes.byref(input_blob),
        None,
        None,
        None,
        None,
        1,
        ctypes.byref(output_blob),
    ):
        raise ctypes.WinError(ctypes.get_last_error())

    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)


def save_token(token: str) -> None:
    """Encrypt and atomically save a non-empty token in the user's profile."""
    if not token:
        raise ValueError("Токен не может быть пустым.")

    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    encrypted = _dpapi_transform(token.encode("utf-8"), decrypt=False)
    temp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "wb", dir=TOKEN_DIR, delete=False
        ) as token_file:
            temp_path = token_file.name
            token_file.write(encrypted)
        os.replace(temp_path, TOKEN_FILE)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


def load_token() -> str | None:
    """Load and decrypt the current or legacy saved token, if present."""
    for token_path in (TOKEN_FILE, _LEGACY_TOKEN_FILE):
        if token_path.is_file():
            encrypted = token_path.read_bytes()
            return _dpapi_transform(encrypted, decrypt=True).decode("utf-8")
    return None
