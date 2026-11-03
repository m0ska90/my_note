import os
import sqlite3
import subprocess
import sys
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
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetParent.argtypes = [wintypes.HWND]
    user32.GetParent.restype = wintypes.HWND
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND
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
    SWP_NOMOVE,
    SWP_NOSIZE,
    SWP_NOACTIVATE,
    SW_RESTORE,
    SW_SHOW,
    WARN_BEFORE,
    HWND_BOTTOM,
)
from database import (
    add_event as db_add_event,
    clear_attachments,
    database_signature,
    delete_event as db_delete_event,
    delete_past_events,
    get_all_events,
    get_event,
    get_inbox_attachments,
    get_max_text_notes,
    get_reminders,
    update_event as db_update_event,
)
from ui.events_tab import EventDialog, EventsTab
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


def send_to_bottom(hwnd):
    if not IS_WINDOWS or not hwnd:
        return
    user32.SetWindowPos(
        hwnd,
        HWND_BOTTOM,
        0,
        0,
        0,
        0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
    )


def open_file(path):
    if IS_WINDOWS:
        os.startfile(path)
    else:
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.call([opener, path])


class NotesApp:
    open_file = staticmethod(open_file)

    def __init__(self, root):
        self.root = root
        self.root.title("Заметки и MAX")
        self.root.geometry(
            "420x600+{}+{}".format(root.winfo_screenwidth() - 440, 30)
        )
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

        self.keep_bottom_job = None
        self.root.after(500, self._ensure_visible)
        self.root.after(1200, self._start_keep_bottom)
        self.root.after(2000, self.auto_refresh_inbox)

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

        self.notebook.add("📥 Из MAX")
        self.tab_max = MaxTab(self.notebook.tab("📥 Из MAX"), self)
        self.tab_max.pack(fill="both", expand=True)
        self.max_tab = self.tab_max
        self.inbox_list = self.tab_max.inbox_list
        self.max_text = self.tab_max.max_text

    def auto_refresh_inbox(self):
        try:
            if os.path.exists(INBOX_DIR):
                current_mtime = os.path.getmtime(INBOX_DIR)
                if current_mtime > self._last_inbox_mtime:
                    self._last_inbox_mtime = current_mtime
                    self.refresh_inbox()

            current_signature = database_signature()
            if current_signature != self._last_db_signature:
                self._last_db_signature = current_signature
                self.refresh_list()
                self.refresh_inbox()
        except (OSError, sqlite3.Error, ValueError) as error:
            self._last_inbox_mtime = 0
            self._last_db_signature = None
            if not self._refresh_error_shown:
                messagebox.showerror(
                    "Ошибка обновления",
                    f"Не удалось обновить заметки или вложения: {error}",
                    parent=self.root,
                )
                self._refresh_error_shown = True
        else:
            self._refresh_error_shown = False
        self.root.after(5000, self.auto_refresh_inbox)

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

        rows = clear_attachments()
        if not rows:
            messagebox.showinfo("Вложения", "Список вложений уже пуст.", parent=self.root)
            return

        deleted_files = 0
        for (file_path,) in rows:
            full_path = os.path.join(INBOX_DIR, file_path)
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
        messagebox.showinfo(
            "Очищено",
            f"Удалено записей в БД: {len(rows)}\n"
            f"Удалено файлов с диска: {deleted_files}",
            parent=self.root,
        )

    def open_inbox_file(self, event=None):
        if event is not None and event.widget is not self.inbox_list:
            return
        selection = self.inbox_list.curselection()
        if not selection:
            return
        filepath = os.path.realpath(
            os.path.join(APP_DATA_DIR, self.tab_max.inbox_files[selection[0]])
        )
        app_data_path = os.path.realpath(APP_DATA_DIR)
        if os.path.commonpath((app_data_path, filepath)) != app_data_path:
            messagebox.showerror(
                "Ошибка", "Недопустимый путь к вложению.", parent=self.root
            )
            return
        if os.path.isfile(filepath):
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

    def clear_past_events(self):
        now = datetime.now().isoformat(timespec="seconds")
        delete_past_events(now)
        self.refresh_list()

    def _ensure_visible(self):
        if not IS_WINDOWS:
            return
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.update_idletasks()
            hwnd = get_hwnd(self.root)
            if hwnd:
                show_window(hwnd)
        except tk.TclError:
            return

    def _start_keep_bottom(self):
        if not IS_WINDOWS:
            return
        self.keep_bottom_job = self.root.after(2000, self._keep_bottom_tick)

    def _keep_bottom_tick(self):
        if not IS_WINDOWS:
            return
        try:
            if self.root.winfo_exists() and self.root.state() != "withdrawn":
                hwnd = get_hwnd(self.root)
                foreground_hwnd = user32.GetForegroundWindow()
                if hwnd and (foreground_hwnd or 0) != hwnd:
                    send_to_bottom(hwnd)
        except tk.TclError:
            return
        self.keep_bottom_job = self.root.after(2000, self._keep_bottom_tick)

    def hide_window(self):
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
            self.tray_icon = pystray.Icon("MyNotes", image, "Заметки", menu)
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
        self.root.after(300, self._ensure_visible)

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
        if HAS_TRAY and self.tray_icon is not None:
            self.tray_icon.stop()
        for job in (self.check_job, self.keep_bottom_job, self.alert_job):
            if job:
                self.root.after_cancel(job)
        self.root.destroy()
