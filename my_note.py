import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
import sqlite3
import os
import sys
import subprocess
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timedelta

ctk.set_appearance_mode("Light")
ctk.set_default_color_theme("blue")

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
        wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, wintypes.UINT,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND
    IS_WINDOWS = True
except (AttributeError, OSError):
    user32 = None
    IS_WINDOWS = False

# --- Настройки путей ---
APP_DATA_DIR = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'MyNotesApp')
os.makedirs(APP_DATA_DIR, exist_ok=True)
DB_FILE = os.path.join(APP_DATA_DIR, "notes.db")
INBOX_DIR = os.path.join(APP_DATA_DIR, "inbox")
os.makedirs(INBOX_DIR, exist_ok=True)

CHECK_INTERVAL = 30
WARN_BEFORE = 60

# ---- Палитра ----
BG_MAIN    = "#f2f2f2"
BG_PANEL   = "#ffffff"
BG_BUTTON  = "#e0e0e0"
FG_TEXT    = "#090202"
COLOR_DONE = "red"
HWND_BOTTOM    = 1
SWP_NOSIZE     = 0x0001
SWP_NOMOVE     = 0x0002
SWP_NOACTIVATE = 0x0010
SW_SHOW        = 5
SW_RESTORE     = 9


@contextmanager
def _connect_db() -> Generator[sqlite3.Connection, None, None]:
    connection = sqlite3.connect(DB_FILE, timeout=10)
    try:
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            yield connection
    finally:
        connection.close()


def get_hwnd(tk_window):
    if not IS_WINDOWS:
        return 0
    hwnd = user32.GetParent(tk_window.winfo_id())
    if hwnd == 0:
        hwnd = tk_window.winfo_id()
    return hwnd

def show_window(hwnd):
    if not IS_WINDOWS or not hwnd: return
    user32.ShowWindow(hwnd, SW_SHOW)
    user32.ShowWindow(hwnd, SW_RESTORE)

def send_to_bottom(hwnd):
    if not IS_WINDOWS or not hwnd: return
    user32.SetWindowPos(hwnd, HWND_BOTTOM, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)


def _database_signature():
    signature = []
    for path in (DB_FILE, f"{DB_FILE}-wal"):
        try:
            stat = os.stat(path)
        except FileNotFoundError:
            signature.append(None)
        else:
            signature.append((stat.st_mtime_ns, stat.st_size))
    return tuple(signature)


def open_file(path):
    if IS_WINDOWS:
        os.startfile(path)
    else:
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.call([opener, path])


class NotesApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Заметки и MAX")
        self.root.geometry("420x600+{}+{}".format(root.winfo_screenwidth() - 440, 30))
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

        self.init_db()
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

    def init_db(self):
        """Создает таблицы, если их нет."""
        with _connect_db() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT,
                    description TEXT,
                    created_at TEXT,
                    remind_at TEXT,
                    status TEXT DEFAULT 'active'
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS attachments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    note_id INTEGER,
                    file_path TEXT,
                    file_type TEXT,
                    original_name TEXT,
                    FOREIGN KEY(note_id) REFERENCES notes(id) ON DELETE CASCADE
                )
            ''')
            conn.commit()

    # ---------------- UI ----------------
    def build_ui(self):
        self.notebook = ctk.CTkTabview(self.root)
        self.notebook.pack(fill="both", expand=True, padx=4, pady=4)

        self.notebook.add("📅 События")
        self.tab_events = self.notebook.tab("📅 События")
        self.build_events_tab()

        self.notebook.add("📥 Из MAX")
        self.tab_max = self.notebook.tab("📥 Из MAX")
        self.build_max_tab()

    def build_events_tab(self):
        top = ctk.CTkFrame(self.tab_events, fg_color="transparent")
        top.pack(side="top", fill="x")

        ctk.CTkButton(top, text="+ Добавить", command=self.open_add_dialog).pack(side="left", padx=2, pady=6)
        ctk.CTkButton(top, text="✎ Изменить", command=self.edit_selected).pack(side="left", padx=2, pady=6)
        ctk.CTkButton(top, text="✖ Удалить", command=self.delete_selected).pack(side="left", padx=2, pady=6)
        ctk.CTkButton(top, text="Свернуть", command=self.hide_window).pack(side="right", padx=2, pady=6)

        list_frame = ctk.CTkFrame(self.tab_events, fg_color="transparent")
        list_frame.pack(fill="both", expand=True, padx=6, pady=4)

        scrollbar = tk.Scrollbar(list_frame, orient="vertical")
        scrollbar.pack(side="right", fill="y")

        self.event_list = tk.Listbox(
            list_frame, bg=BG_PANEL, fg=FG_TEXT, selectbackground="#bcd6f0",
            selectforeground="#000000", font=("Arial", 10),
            yscrollcommand=scrollbar.set, relief="flat", highlightthickness=1,
            highlightbackground="#cccccc"
        )
        self.event_list.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.event_list.yview)
        self.event_list.bind("<<ListboxSelect>>", self.show_details)

        self.desc = ctk.CTkTextbox(self.tab_events, height=120, wrap="word")
        self.desc.pack(fill="x", padx=6, pady=(0, 6))
        self.desc.configure(state="disabled")

    def build_max_tab(self):
        top = ctk.CTkFrame(self.tab_max, fg_color="transparent")
        top.pack(side="top", fill="x")
        ctk.CTkButton(top, text="🔄 Обновить", command=self.refresh_inbox).pack(side="left", padx=2, pady=6)
        ctk.CTkButton(top, text="🗑 Очистить", command=self.clear_inbox_list).pack(side="left", padx=2, pady=6)
        ctk.CTkButton(
            top, text="📂 Открыть папку", command=lambda: open_file(INBOX_DIR)
        ).pack(side="left", padx=6, pady=6)

        self.inbox_list = tk.Listbox(
            self.tab_max, bg=BG_PANEL, fg=FG_TEXT, selectbackground="#bcd6f0",
            font=("Arial", 10), relief="flat", highlightthickness=1, highlightbackground="#cccccc"
        )
        self.inbox_list.pack(fill="both", expand=True, padx=6, pady=4)
        self.inbox_list.bind("<Double-1>", self.open_inbox_file)
        self.inbox_files = []

        ctk.CTkLabel(self.tab_max, text="Текст заметки из бота:").pack(anchor="w", padx=6)
        self.max_text = ctk.CTkTextbox(self.tab_max, height=120, wrap="word")
        self.max_text.pack(fill="x", padx=6, pady=(0, 6))
        self.max_text.configure(state="disabled")

    # ---------------- Логика вкладки MAX ----------------
    def auto_refresh_inbox(self):
        try:
            # Проверяем папку с файлами
            if os.path.exists(INBOX_DIR):
                current_mtime = os.path.getmtime(INBOX_DIR)
                if current_mtime > self._last_inbox_mtime:
                    self._last_inbox_mtime = current_mtime
                    self.refresh_inbox()

            # Проверяем базу данных (вдруг бот добавил текст)
            current_db_signature = _database_signature()
            if current_db_signature != self._last_db_signature:
                self._last_db_signature = current_db_signature
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
        self.inbox_list.delete(0, tk.END)

        with _connect_db() as conn:
            cursor = conn.cursor()
            # Показываем прикрепленные файлы
            cursor.execute('''
                SELECT a.file_path, a.original_name, n.title
                FROM attachments a
                JOIN notes n ON a.note_id = n.id
            ''')
            attachments = cursor.fetchall()
            self.inbox_files = []
            for file_path, orig_name, note_title in attachments:
                self.inbox_list.insert(tk.END, f"📎 {orig_name} (к: {note_title})")
                self.inbox_files.append(file_path)

            # Показываем текст заметок из MAX
            cursor.execute("SELECT created_at, description FROM notes WHERE title LIKE 'Заметка из MAX%' ORDER BY id DESC")
            max_notes = cursor.fetchall()

        self.max_text.configure(state="normal")
        self.max_text.delete("1.0", "end")
        if max_notes:
            for created_at, description in max_notes:
                dt = datetime.fromisoformat(created_at)
                self.max_text.insert(tk.END, f"[{dt.strftime('%d.%m %H:%M')}] {description}\n\n")
        else:
            self.max_text.insert(tk.END, "Текстовых заметок из бота пока нет.")
        self.max_text.configure(state="disabled")

    def clear_inbox_list(self):
        """Очищает список вложений из MAX: удаляет записи из БД и файлы с диска."""
        if not messagebox.askyesno(
            "Очистка вложений",
            "Вы уверены, что хотите очистить список поступивших файлов?\n"
            "Сами файлы будут удалены с диска.",
            parent=self.root,
        ):
            return

        deleted_count = 0
        deleted_files = 0

        with _connect_db() as conn:
            cursor = conn.cursor()
            # Получаем список файлов перед удалением
            cursor.execute("SELECT file_path FROM attachments")
            rows = cursor.fetchall()

            if not rows:
                messagebox.showinfo("Вложения", "Список вложений уже пуст.", parent=self.root)
                return

            # Удаляем физические файлы
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

            # Удаляем записи из БД
            cursor.execute("DELETE FROM attachments")
            conn.commit()

        # Обновляем интерфейс
        self.refresh_inbox()

        messagebox.showinfo(
            "Очищено",
            f"Удалено записей в БД: {len(rows)}\n"
            f"Удалено файлов с диска: {deleted_files}",
            parent=self.root,
        )

    def open_inbox_file(self, event):
        if event is not None and event.widget is not self.inbox_list:
            return
        sel = self.inbox_list.curselection()
        if not sel: return
        filepath = os.path.realpath(os.path.join(APP_DATA_DIR, self.inbox_files[sel[0]]))
        app_data_path = os.path.realpath(APP_DATA_DIR)
        if os.path.commonpath((app_data_path, filepath)) != app_data_path:
            messagebox.showerror("Ошибка", "Недопустимый путь к вложению.", parent=self.root)
            return
        if os.path.isfile(filepath):
            open_file(filepath)
        else:
            messagebox.showerror("Ошибка", "Файл вложения не найден.", parent=self.root)

    # ---------------- События ----------------
    def show_details(self, event=None):
        if event is not None and event.widget is not self.event_list:
            return
        sel = self.event_list.curselection()
        self.desc.configure(state="normal")
        self.desc.delete("1.0", "end")
        if sel:
            ev = self.sorted_events[sel[0]]
            self.desc.insert("1.0", ev[2] if ev[2] else "(нет описания)")
        self.desc.configure(state="disabled")

    def refresh_list(self):
        self.event_list.delete(0, tk.END)

        with _connect_db() as conn:
            cursor = conn.cursor()
            # Исключаем заметки из MAX из списка событий
            cursor.execute("SELECT id, title, description, remind_at FROM notes WHERE title NOT LIKE 'Заметка из MAX%' ORDER BY remind_at")
            rows = cursor.fetchall()

        self.sorted_events = rows

        for i, row in enumerate(rows):
            title, remind_at = row[1], row[3]
            if remind_at:
                dt = datetime.fromisoformat(remind_at)
                display_text = f" {dt.strftime('%d.%m.%Y')}  {dt.strftime('%H:%M')}   {title}"
            else:
                display_text = f" Без даты                  {title}"

            self.event_list.insert(tk.END, display_text)

            if remind_at and datetime.fromisoformat(remind_at) <= datetime.now():
                self.event_list.itemconfig(i, foreground=COLOR_DONE)

    def open_add_dialog(self):
        EventDialog(self.root, on_save=self.add_event)

    def add_event(self, data):
        with _connect_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO notes (title, description, remind_at, created_at, status)
                VALUES (?, ?, ?, ?, 'active')
            ''', (data["title"], data["description"], data["datetime"], datetime.now().isoformat()))
            conn.commit()
        self.refresh_list()
        return True

    def edit_selected(self):
        sel = self.event_list.curselection()
        if not sel: return
        nid = self.sorted_events[sel[0]][0]
        with _connect_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, title, description, remind_at FROM notes WHERE id = ?", (nid,))
            row = cursor.fetchone()
            if row:
                ev_dict = {"id": row[0], "title": row[1], "description": row[2], "datetime": row[3]}
                EventDialog(self.root, on_save=lambda data: self.update_event(nid, data), initial=ev_dict)

    def update_event(self, event_id, data):
        with _connect_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE notes SET title = ?, description = ?, remind_at = ? WHERE id = ?
            ''', (data["title"], data["description"], data["datetime"], event_id))
            conn.commit()
        self.warned.pop(event_id, None)
        self.refresh_list()
        return True

    def delete_selected(self):
        sel = self.event_list.curselection()
        if not sel: return
        if not messagebox.askyesno("Заметки", "Удалить выбранное событие?"): return
        nid = self.sorted_events[sel[0]][0]
        with _connect_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM notes WHERE id = ?", (nid,))
            conn.commit()
        self.warned.pop(nid, None)
        self.refresh_list()

    def clear_past_events(self):
        now = datetime.now().isoformat(timespec="seconds")
        with _connect_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM notes WHERE remind_at <= ? AND title NOT LIKE 'Заметка из MAX%'", (now,))
            conn.commit()
        self.refresh_list()

    # ---------------- Трей и окна ----------------
    def _ensure_visible(self):
        if not IS_WINDOWS: return
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.update_idletasks()
            hwnd = get_hwnd(self.root)
            if hwnd: show_window(hwnd)
        except tk.TclError:
            return

    def _start_keep_bottom(self):
        if not IS_WINDOWS: return
        self.keep_bottom_job = self.root.after(2000, self._keep_bottom_tick)

    def _keep_bottom_tick(self):
        if not IS_WINDOWS: return
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
            image = Image.new('RGB', (64, 64), color=(240, 240, 240))
            d = ImageDraw.Draw(image)
            d.rectangle([10, 10, 54, 54], outline="black", width=3)
            menu = pystray.Menu(
                pystray.MenuItem('Открыть', self._tray_restore),
                pystray.MenuItem('Выход', self._tray_exit)
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

    # ---------------- Напоминания ----------------
    def check_events(self, initial=False):
        self.check_job = None
        now = datetime.now()

        with _connect_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, title, description, remind_at FROM notes WHERE remind_at IS NOT NULL AND title NOT LIKE 'Заметка из MAX%'")
            for nid, title, desc, remind_at in cursor.fetchall():
                event_dt = datetime.fromisoformat(remind_at)
                flags = self.warned.setdefault(nid, set())
                delta = (event_dt - now).total_seconds()

                if delta <= 0:
                    if initial: flags.add("done")
                    elif "done" not in flags:
                        flags.add("done")
                        self.schedule_alert("🔔 Событие наступило", f"{title}\n\n{desc}", count=3)
                        self.refresh_list()
                elif delta <= WARN_BEFORE and "warn" not in flags:
                    flags.add("warn")
                    self.schedule_alert("⏰ Скоро событие", f"{title}\nНачнётся в {event_dt.strftime('%H:%M:%S')}", count=3)

        self.check_job = self.root.after(CHECK_INTERVAL * 1000, self.check_events)

    def schedule_alert(self, title, text, count=3):
        self.pending_alerts.append({"title": title, "text": text, "left": count})
        if self.alert_job is None: self.show_next_alert()

    def show_next_alert(self):
        if not self.pending_alerts:
            self.alert_job = None
            return
        alert = self.pending_alerts[0]
        messagebox.showwarning(alert["title"], alert["text"])
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
            if job: self.root.after_cancel(job)
        self.root.destroy()


class EventDialog(ctk.CTkToplevel):
    def __init__(self, parent, on_save, initial=None):
        super().__init__(parent)
        self.on_save = on_save
        self.title("Событие")
        self.geometry("340x330")
        self.configure(fg_color=BG_MAIN)
        self.attributes("-alpha", 1.0)
        self.resizable(False, False)

        pad = {"padx": 10, "pady": 4}

        ctk.CTkLabel(self, text="Название:").pack(anchor="w", **pad)
        self.title_entry = ctk.CTkEntry(self)
        self.title_entry.pack(fill="x", padx=10)

        ctk.CTkLabel(self, text="Описание:").pack(anchor="w", **pad)
        self.desc_text = ctk.CTkTextbox(self, height=100, wrap="word")
        self.desc_text.pack(fill="x", padx=10)

        ctk.CTkLabel(self, text="Дата (ДД.ММ.ГГГГ):").pack(anchor="w", **pad)
        self.date_entry = ctk.CTkEntry(self)
        self.date_entry.pack(fill="x", padx=10)

        ctk.CTkLabel(self, text="Время (ЧЧ:ММ):").pack(anchor="w", **pad)
        self.time_entry = ctk.CTkEntry(self)
        self.time_entry.pack(fill="x", padx=10)

        ctk.CTkButton(self, text="Сохранить", command=self.save).pack(pady=10)

        if initial:
            self.title_entry.insert(0, initial.get("title", ""))
            self.desc_text.insert("1.0", initial.get("description", "") or "")
            if initial.get("datetime"):
                dt = datetime.fromisoformat(initial["datetime"])
                self.date_entry.insert(0, dt.strftime("%d.%m.%Y"))
                self.time_entry.insert(0, dt.strftime("%H:%M"))
        else:
            now = datetime.now() + timedelta(minutes=5)
            self.date_entry.insert(0, now.strftime("%d.%m.%Y"))
            self.time_entry.insert(0, now.strftime("%H:%M"))

    def save(self):
        title = self.title_entry.get().strip()
        if not title:
            messagebox.showerror("Ошибка", "Введите название события", parent=self)
            return
        try:
            dt = datetime.strptime(f"{self.date_entry.get().strip()} {self.time_entry.get().strip()}", "%d.%m.%Y %H:%M")
        except ValueError:
            messagebox.showerror("Ошибка", "Неверный формат даты/времени.\nИспользуйте ДД.ММ.ГГГГ и ЧЧ:ММ", parent=self)
            return
        data = {
            "title": title,
            "description": self.desc_text.get("1.0", "end").strip(),
            "datetime": dt.isoformat(timespec="minutes"),
        }
        if self.on_save(data):
            self.destroy()

_INSTANCE_MUTEX_HANDLE = None


def is_already_running():
    if not IS_WINDOWS: return False
    global _INSTANCE_MUTEX_HANDLE
    mutex_name = "Global\\MyNotesAppMutex_UniqueName123"
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
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

if __name__ == "__main__":
    if is_already_running():
        root = ctk.CTk()
        root.withdraw()
        messagebox.showwarning("Заметки", "Программа уже запущена!")
        sys.exit(0)

    root = ctk.CTk()
    app = NotesApp(root)
    root.mainloop()