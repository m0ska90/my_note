import ctypes
import logging
import os
import subprocess
import sys

# Добавляем корень проекта в sys.path для корректных импортов
_project_root = os.path.dirname(os.path.abspath(__file__))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import customtkinter as ctk
from ctypes import wintypes
from tkinter import messagebox

from database import init_db, migrate_from_plaintext
from ui.main_window import NotesApp


_INSTANCE_MUTEX_HANDLE = None
_MIGRATION_DONE = False
_BOT_PROCESS: subprocess.Popen[bytes] | None = None
_BOT_MUTEX_NAME = "Local\\MyNoteMaxBotReceiver"
logger = logging.getLogger(__name__)


def is_already_running():
    if sys.platform != "win32":
        return False
    global _INSTANCE_MUTEX_HANDLE
    mutex_name = "Global\\MyNotesAppMutex_UniqueName123"
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [
        wintypes.LPVOID,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    ]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    ctypes.set_last_error(0)
    handle = kernel32.CreateMutexW(None, False, mutex_name)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == 183:
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.CloseHandle(handle)
        return True
    _INSTANCE_MUTEX_HANDLE = handle
    return False


def _init_encryption() -> bool:
    """Инициализировать шифрование БД. Выполнить миграцию при необходимости.
    
    Returns:
        True если инициализация прошла успешно.
    """
    global _MIGRATION_DONE
    try:
        _MIGRATION_DONE = migrate_from_plaintext()
    except ValueError:
        # Неверный пароль
        messagebox.showerror(
            "Ошибка шифрования",
            "Неверный пароль базы данных или повреждение БД.\n"
            "Удалите файл notes.db и перезапустите для создания новой БД.\n\n"
            "(Резервная копия сохранена как notes.db.plaintext.backup)",
        )
        return False
    except Exception as e:
        messagebox.showerror(
            "Ошибка",
            f"Не удалось инициализировать шифрование: {e}",
        )
        return False
    return True


def _is_bot_running() -> bool:
    if sys.platform != "win32":
        return False

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenMutexW.argtypes = [
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    ]
    kernel32.OpenMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenMutexW(0x00100000, False, _BOT_MUTEX_NAME)
    if handle:
        kernel32.CloseHandle(handle)
        return True
    if ctypes.get_last_error() != 2:
        raise ctypes.WinError(ctypes.get_last_error())
    return False


def _monitor_bot(root: ctk.CTk, process: subprocess.Popen[bytes]) -> None:
    global _BOT_PROCESS
    return_code = process.poll()
    if return_code is None:
        root.after(3000, lambda: _monitor_bot(root, process))
        return

    _BOT_PROCESS = None
    try:
        bot_is_running = _is_bot_running()
    except OSError as error:
        logger.exception("Не удалось проверить состояние MAX-бота.")
        messagebox.showwarning(
            "MAX-бот",
            f"Бот завершился с кодом {return_code}; "
            f"не удалось проверить наличие другого экземпляра:\n{error}",
            parent=root,
        )
        return
    if not bot_is_running:
        messagebox.showwarning(
            "MAX-бот",
            f"Процесс бота завершился (код {return_code}). "
            "Проверьте токен и журнал запуска.",
            parent=root,
        )


def _start_bot(root: ctk.CTk) -> None:
    global _BOT_PROCESS
    try:
        if _is_bot_running():
            logger.info("MAX-бот уже запущен.")
            return

        if getattr(sys, "frozen", False):
            try:
                import bot_receiver
            except ImportError as error:
                raise FileNotFoundError(
                    "В сборке приложения отсутствует модуль bot_receiver."
                ) from error
            if not callable(bot_receiver.main):
                raise FileNotFoundError(
                    "В сборке приложения отсутствует точка входа MAX-бота."
                )
            command = [sys.executable, "--run-bot"]
        else:
            bot_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "bot_receiver.py",
            )
            if not os.path.isfile(bot_path):
                raise FileNotFoundError(f"Файл бота не найден: {bot_path}")
            command = [sys.executable, bot_path]

        process = subprocess.Popen(
            command,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _BOT_PROCESS = process
        root.after(1500, lambda: _monitor_bot(root, process))
    except (OSError, subprocess.SubprocessError) as error:
        logger.exception("Не удалось запустить MAX-бот.")
        messagebox.showerror(
            "Ошибка запуска MAX-бота",
            f"Не удалось запустить бота:\n{error}",
            parent=root,
        )


def _stop_bot() -> None:
    global _BOT_PROCESS
    process = _BOT_PROCESS
    _BOT_PROCESS = None
    if process is None or process.poll() is not None:
        return

    try:
        process.terminate()
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            logger.exception("Процесс MAX-бота не завершился после принудительной остановки.")
    except OSError:
        logger.exception("Не удалось корректно завершить процесс MAX-бота.")


def main():
    if "--run-bot" in sys.argv[1:]:
        from bot_receiver import main as bot_main

        bot_main()
        return

    if is_already_running():
        root = ctk.CTk()
        root.withdraw()
        messagebox.showwarning("Заметки", "Программа уже запущена!")
        root.destroy()
        return

    # Инициализация шифрования БД (миграция при необходимости)
    if not _init_encryption():
        return

    init_db()
    root = ctk.CTk()
    NotesApp(root, on_close_callback=_stop_bot)
    _start_bot(root)
    root.mainloop()


if __name__ == "__main__":
    main()
