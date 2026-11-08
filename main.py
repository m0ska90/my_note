import ctypes
import os
import sys

# Добавляем корень проекта в sys.path для корректных импортов
_project_root = os.path.dirname(os.path.abspath(__file__))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import customtkinter as ctk
import tkinter as tk
from ctypes import wintypes
from tkinter import messagebox

from database import init_db, migrate_from_plaintext
from ui.main_window import NotesApp


_INSTANCE_MUTEX_HANDLE = None
_MIGRATION_DONE = False
_BOT_MUTEX_NAME = "Local\\ЗаказикиBotReceiver"


def is_already_running():
    if sys.platform != "win32":
        return False
    global _INSTANCE_MUTEX_HANDLE
    mutex_name = "Global\\ЗаказикиMutex_UniqueName123"
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
    
    # Подавляем TclError от CustomTkinter при перерисовке виджетов —
    # при удалении/создании карточек отложенные draw-события CTk
    # срабатывают на уже удалённых canvas. Это известное поведение.
    def _suppress_ctk_errors(exc_type, exc_val, exc_tb):
        if exc_type is tk.TclError:
            return  # игнорируем TclError от CTk
        # Выводим остальные ошибки в stderr
        import traceback
        sys.stderr.write(f"Exception in Tkinter callback\n")
        sys.stderr.write(''.join(traceback.format_exception(exc_type, exc_val, exc_tb)))
    root.report_callback_exception = _suppress_ctk_errors
    
    app = NotesApp(root, bot_running_check=_is_bot_running)
    app.start_bot()
    root.mainloop()


if __name__ == "__main__":
    main()
