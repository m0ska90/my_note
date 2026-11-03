import ctypes
import sys

import customtkinter as ctk
from ctypes import wintypes
from tkinter import messagebox

from database import init_db
from ui.main_window import NotesApp


_INSTANCE_MUTEX_HANDLE = None


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


def main():
    if is_already_running():
        root = ctk.CTk()
        root.withdraw()
        messagebox.showwarning("Заметки", "Программа уже запущена!")
        root.destroy()
        return

    init_db()
    root = ctk.CTk()
    NotesApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
