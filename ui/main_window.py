import logging
import os
import sqlite3
import subprocess
import sys
import threading
from collections.abc import Callable
from datetime import datetime

import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox

try:
    import pystray
    from PIL import Image, ImageDraw

    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

try:
    from ui.file_watcher import create_file_watcher
    HAS_FILE_WATCHER = True
except ImportError:
    HAS_FILE_WATCHER = False

try:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetParent.argtypes = [wintypes.HWND]
    user32.GetParent.restype = wintypes.HWND
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    IS_WINDOWS = True
except (AttributeError, OSError):
    user32 = None
    IS_WINDOWS = False

from config import (
    APP_DATA_DIR,
    APP_FONT,
    BG_MAIN,
    CHECK_INTERVAL,
    INBOX_DIR,
    SW_RESTORE,
    SW_SHOW,
    WARN_BEFORE,
)
from database import (
    add_event as db_add_event,
    clear_attachments,
    database_signature,
    delete_event as db_delete_event,
    delete_past_events,
    get_all_events,
    get_all_orders,
    get_event,
    get_inbox_attachments,
    get_max_text_notes,
    get_reminders,
    update_event as db_update_event,
)
from ui.events_tab import EventDialog, EventsTab
from ui.orders_tab import OrdersTab
from ui.max_tab import MaxTab

ctk.set_appearance_mode("Light")
ctk.set_default_color_theme("blue")


def get_hwnd(tk_window):
    if not IS_WINDOWS:
        return 0
    hwnd = user32.GetParent(tk_window.winfo_id())
    if hwnd == 0:
        hwnd = tk_window.winfo_id()
    return hwnd


def show_window(hwnd):
    if not IS_WINDOWS or not hwnd:
        return
    user32.ShowWindow(hwnd, SW_SHOW)
    user32.ShowWindow(hwnd, SW_RESTORE)


def open_file(path):
    if IS_WINDOWS:
        os.startfile(path)
    else:
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.call([opener, path])


def _find_file_with_extension(path: str) -> str | None:
    """Если файл не найден — ищем в inbox с распространённым расширением."""
    if os.path.isfile(path):
        return path
    inbox_dir = os.path.join(APP_DATA_DIR, "inbox")
    basename = os.path.basename(path)
    for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic",
                ".mp4", ".mov", ".avi", ".mp3", ".ogg", ".flac", ".pdf",
                ".doc", ".docx", ".xls", ".xlsx", ".zip", ".gz"):
        candidate = os.path.join(inbox_dir, basename + ext)
        if os.path.isfile(candidate):
            return candidate
    return None


class NotesApp:
    open_file = staticmethod(open_file)

    def __init__(self, root, on_close_callback: Callable[[], None] | None = None):
        self.root = root
        self.on_close_callback = on_close_callback
        self.root.title("Заказики и MAX")
        self.root.configure(fg_color=BG_MAIN)
        self.root.attributes("-alpha", 1.0)
        self.root.attributes("-topmost", False)

        self.warned = {}
        self.pending_alerts = []
        self.tray_icon = None
        self.is_hidden = False
        self._last_inbox_mtime = 0
        self._last_db_signature = None
        self._refresh_error_shown = False

        self.build_ui()
        self.refresh_list()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.check_job = None
        self.alert_job = None
        self.check_events(initial=True)

        self.root.after(2000, self.auto_refresh_inbox)

        # Запустить событийное обновление вложений
        self._start_inbox_watcher()

        # Запускаем мониторинг переключения вкладок (CTkTabview не поддерживает <<NotebookTabChanged>>)
        self._last_active_tab = ""
        self._tab_check_job = None
        self._check_tab_switch()

        # CTk.mainloop() показывает окно через deiconify(), сбрасывая state,
        # поэтому максимизируем его после первоначального показа.
        self.root.after(100, self._maximize_window)

    def _maximize_window(self) -> None:
        """Развернуть главное окно после его отображения."""
        if IS_WINDOWS:
            self.root.state("zoomed")
        else:
            self.root.attributes("-zoomed", True)

    def _check_tab_switch(self):
        """Проверяем текущую активную вкладку каждые 2 секунды."""
        try:
            current_tab = self.notebook.cget("value")
            if current_tab != self._last_active_tab:
                self._last_active_tab = current_tab
                if "Заказы" in (current_tab or ""):
                    if hasattr(self, "orders_tab") and self.orders_tab:
                        self.orders_tab.refresh()
        except Exception:
            pass
        self._tab_check_job = self.root.after(2000, self._check_tab_switch)

    def build_ui(self):
        self.notebook = ctk.CTkTabview(
            self.root, segmented_button_font=APP_FONT
        )
        self.notebook.pack(fill="both", expand=True, padx=4, pady=4)

        self.notebook.add("📅 События")
        self.tab_events = EventsTab(self.notebook.tab("📅 События"), self)
        self.tab_events.pack(fill="both", expand=True)
        self.events_tab = self.tab_events
        self.event_list = self.tab_events.event_list
        self.desc = self.tab_events.desc

        self.notebook.add("📦 Заказы")
        self.orders_tab = OrdersTab(self.notebook.tab("📦 Заказы"), self)
        self.orders_tab.pack(fill="both", expand=True)
        self.tree_orders = self.orders_tab.tree

        self.notebook.add("📥 Из MAX")
        self.tab_max = MaxTab(self.notebook.tab("📥 Из MAX"), self)
        self.tab_max.pack(fill="both", expand=True)
        self.max_tab = self.tab_max
        self.inbox_list = self.tab_max.inbox_list
        self.max_text = self.tab_max.max_text

        # Отложенные draw-события CustomTkinter при обновлении виджетов
        # (destroy + recreate) срабатывают на уже удалённых canvas и
        # вызывают TclError. Это известное поведение CTk. Подавляем ошибки,
        # но оставляем traceback в stderr для отладки настоящих проблем.
        self._ignore_tcl_errors = False

    def _handle_tcl_error(self, exc, val, tb):
        """Перехват ошибок callback-ов. Игнорируем TclError при перерисовке."""
        if isinstance(exc, tk.TclError) and self._ignore_tcl_errors:
            return  # игнорируем
        import traceback
        sys.stderr.write(f"Exception in Tkinter callback\n")
        sys.stderr.write(''.join(traceback.format_exception(exc, val, tb)))

    def _on_inbox_change(self) -> None:
        """Callback при изменении файлов в INBOX_DIR."""
        try:
            self.refresh_inbox()
        except (OSError, sqlite3.Error, ValueError) as error:
            logging.getLogger("main_window").error("Ошибка обновления inbox: %s", error)

    def _start_inbox_watcher(self) -> None:
        """Запустить файловый монитор для INBOX_DIR."""
        if not HAS_FILE_WATCHER:
            return
        try:
            if not os.path.isdir(INBOX_DIR):
                os.makedirs(INBOX_DIR, exist_ok=True)
            self._inbox_watcher = create_file_watcher(
                INBOX_DIR, self._on_inbox_change, poll_interval=1.5
            )
        except Exception as e:
            logging.getLogger("main_window").warning("Не удалось запустить файловый монитор: %s", e)

    def auto_refresh_inbox(self):
        try:
            current_signature = database_signature()
            if current_signature != self._last_db_signature:
                self._last_db_signature = current_signature
                self.refresh_list()
                self.refresh_inbox()
        except (OSError, sqlite3.Error, ValueError) as error:
            self._last_db_signature = None
            if not self._refresh_error_shown:
                messagebox.showerror(
                    "Ошибка обновления",
                    "Не удалось проверить изменения в заметках.",
                    parent=self.root,
                )
                self._refresh_error_shown = True
        else:
            self._refresh_error_shown = False
        self.root.after(15000, self.auto_refresh_inbox)

    def refresh_inbox(self):
        self.tab_max.refresh(get_inbox_attachments(), get_max_text_notes())

    def clear_inbox_list(self):
        if not messagebox.askyesno(
            "Очистка вложений",
            "Вы уверены, что хотите очистить список поступивших файлов?\n"
            "Сами файлы будут удалены с диска.",
            parent=self.root,
        ):
            return

        rows = clear_attachments(INBOX_DIR)
        if not rows:
            messagebox.showinfo("Вложения", "Список вложений уже пуст.", parent=self.root)
            return

        deleted_files = 0
        skipped_files = 0
        inbox_real = os.path.realpath(INBOX_DIR)
        for (file_path,) in rows:
            # Защита от Path Traversal
            clean_path = os.path.normpath(file_path)
            if os.path.isabs(clean_path) or clean_path.startswith(".."):
                skipped_files += 1
                continue
            full_path = os.path.realpath(os.path.join(INBOX_DIR, clean_path))
            if not full_path.startswith(inbox_real + os.sep):
                skipped_files += 1
                continue
            try:
                if os.path.isfile(full_path):
                    os.remove(full_path)
                    deleted_files += 1
            except PermissionError:
                messagebox.showwarning(
                    "Внимание",
                    f"Не удалось удалить файл:\n{os.path.basename(full_path)}\n"
                    "Возможно, файл открыт в другой программе.",
                    parent=self.root,
                )
            except OSError as error:
                messagebox.showerror(
                    "Ошибка",
                    f"Не удалось удалить файл:\n{os.path.basename(full_path)}\n"
                    f"Причина: {error}",
                    parent=self.root,
                )

        self.refresh_inbox()
        msg = f"Удалено файлов с диска: {deleted_files}"
        if skipped_files:
            msg += f"\nПропущено подозрительных записей: {skipped_files}"
        messagebox.showinfo("Очищено", msg, parent=self.root)

    def open_inbox_file(self, file_path: str):
        if not file_path:
            return
        filepath = os.path.realpath(
            os.path.join(APP_DATA_DIR, file_path)
        )
        app_data_path = os.path.realpath(APP_DATA_DIR)
        try:
            is_inside_app_data = (
                os.path.commonpath((app_data_path, filepath)) == app_data_path
            )
        except ValueError:
            is_inside_app_data = False
        if not is_inside_app_data:
            messagebox.showerror(
                "Ошибка", "Недопустимый путь к вложению.", parent=self.root
            )
            return
        filepath = _find_file_with_extension(filepath)
        if filepath and os.path.isfile(filepath):
            open_file(filepath)
        else:
            messagebox.showerror(
                "Ошибка", "Файл вложения не найден.", parent=self.root
            )

    def show_details(self, event=None):
        self.tab_events.show_details(event)

    def refresh_list(self):
        self.tab_events.refresh(get_all_events())

    def open_add_dialog(self):
        EventDialog(self.root, on_save=self.add_event)

    def add_event(self, data):
        db_add_event(data["title"], data["description"], data["datetime"])
        self.refresh_list()
        return True

    def edit_selected(self):
        selection = self.event_list.curselection()
        if not selection:
            return
        note_id = self.tab_events.sorted_events[selection[0]][0]
        row = get_event(note_id)
        if row:
            event_data = {
                "id": row[0],
                "title": row[1],
                "description": row[2],
                "datetime": row[3],
            }
            EventDialog(
                self.root,
                on_save=lambda data: self.update_event(note_id, data),
                initial=event_data,
            )

    def update_event(self, event_id, data):
        db_update_event(
            event_id,
            data["title"],
            data["description"],
            data["datetime"],
        )
        self.warned.pop(event_id, None)
        self.refresh_list()
        return True

    def delete_selected(self):
        selection = self.event_list.curselection()
        if not selection:
            return
        if not messagebox.askyesno("Заметки", "Удалить выбранное событие?"):
            return
        note_id = self.tab_events.sorted_events[selection[0]][0]
        db_delete_event(note_id)
        self.warned.pop(note_id, None)
        self.refresh_list()

    def refresh_orders(self):
        self.orders_tab.refresh()

    def clear_past_events(self):
        now = datetime.now().isoformat(timespec="seconds")
        delete_past_events(now)
        self.refresh_list()

    def restore_window(self):
        if not HAS_TRAY:
            self.is_hidden = False
            self.root.iconify()
            return

        self.root.withdraw()
        self.is_hidden = True
        if self.tray_icon is None:
            image = Image.new("RGB", (64, 64), color=(240, 240, 240))
            draw = ImageDraw.Draw(image)
            draw.rectangle([10, 10, 54, 54], outline="black", width=3)
            menu = pystray.Menu(
                pystray.MenuItem("Открыть", self._tray_restore),
                pystray.MenuItem("Выход", self._tray_exit),
            )
            self.tray_icon = pystray.Icon("Заказики", image, "Заметки", menu)
        self.tray_icon.run_detached()

    def _tray_restore(self, icon, _item):
        icon.stop()
        self.tray_icon = None
        self.root.after(0, self.restore_window)

    def _tray_exit(self, icon, _item):
        icon.stop()
        self.root.after(0, self.on_close)

    def restore_window(self):
        self.is_hidden = False
        self.root.deiconify()
        if IS_WINDOWS:
            try:
                hwnd = get_hwnd(self.root)
                if hwnd:
                    show_window(hwnd)
            except tk.TclError:
                pass

    def check_events(self, initial=False):
        self.check_job = None
        now = datetime.now()

        for note_id, title, description, remind_at in get_reminders():
            event_dt = datetime.fromisoformat(remind_at)
            flags = self.warned.setdefault(note_id, set())
            delta = (event_dt - now).total_seconds()

            if delta <= 0:
                if initial:
                    flags.add("done")
                elif "done" not in flags:
                    flags.add("done")
                    self.schedule_alert(
                        "🔔 Событие наступило",
                        f"{title}\n\n{description}",
                        count=3,
                    )
                    self.refresh_list()
            elif delta <= WARN_BEFORE and "warn" not in flags:
                flags.add("warn")
                self.schedule_alert(
                    "⏰ Скоро событие",
                    f"{title}\nНачнётся в {event_dt.strftime('%H:%M:%S')}",
                    count=3,
                )

        self.check_job = self.root.after(
            CHECK_INTERVAL * 1000, self.check_events
        )

    def schedule_alert(self, title, text, count=3):
        self.pending_alerts.append({"title": title, "text": text, "left": count})
        if self.alert_job is None:
            self.show_next_alert()

    def show_next_alert(self):
        if not self.pending_alerts:
            self.alert_job = None
            return
        alert = self.pending_alerts[0]
        dialog = ctk.CTkToplevel(self.root)
        dialog.title(alert["title"])
        dialog.geometry("420x200")
        dialog.attributes("-topmost", True)
        dialog.transient(self.root)
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)

        ctk.CTkLabel(
            dialog,
            text=alert["text"],
            font=APP_FONT,
            wraplength=370,
            justify="left",
        ).pack(fill="both", expand=True, padx=20, pady=(20, 10))
        ctk.CTkButton(
            dialog,
            text="ОК",
            font=APP_FONT,
            command=dialog.destroy,
        ).pack(pady=(0, 15))

        dialog.lift()
        dialog.focus_force()
        dialog.grab_set()
        self.root.wait_window(dialog)

        alert["left"] -= 1
        if alert["left"] > 0:
            self.alert_job = self.root.after(10000, self.show_next_alert)
        else:
            self.pending_alerts.pop(0)
            self.alert_job = None
            if self.pending_alerts:
                self.alert_job = self.root.after(100, self.show_next_alert)

    def on_close(self):
        # Остановить автообновление заказов
        if hasattr(self, "orders_tab") and self.orders_tab:
            self.orders_tab.stop_auto_refresh()

        # Остановить мониторинг переключения вкладок
        if hasattr(self, "_tab_check_job") and self._tab_check_job:
            self.root.after_cancel(self._tab_check_job)

        # Остановить файловый монитор
        if hasattr(self, "_inbox_watcher") and self._inbox_watcher:
            self._inbox_watcher.stop()

        if HAS_TRAY and self.tray_icon is not None:
            self.tray_icon.stop()
        if self.on_close_callback is not None:
            self.on_close_callback()
        for job in (self.check_job, self.alert_job):
            if job:
                self.root.after_cancel(job)
        self.root.destroy()
