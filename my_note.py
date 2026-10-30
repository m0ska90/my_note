import tkinter as tk
from tkinter import ttk, messagebox
import json
import os
import tempfile
import threading
import time
from datetime import datetime, timedelta
import sys

# --- НОВОЕ: Библиотеки для трея ---
try:
    import pystray
    from PIL import Image, ImageDraw
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

# ================= Windows API =================
try:
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    IS_WINDOWS = True
except Exception:
    IS_WINDOWS = False

# --- НОВОЕ: Путь к данным в AppData, чтобы не терять заметки при переносе exe ---
APP_DATA_DIR = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'MyNotesApp')
os.makedirs(APP_DATA_DIR, exist_ok=True)
DATA_FILE = os.path.join(APP_DATA_DIR, "notes_data.json")

CHECK_INTERVAL = 30
WARN_BEFORE = 60

# ---- Светлая палитра ----
BG_MAIN    = "#f2f2f2"   
BG_PANEL   = "#ffffff"   
BG_BUTTON  = "#e0e0e0"   
FG_TEXT    = "#202020"   
COLOR_DONE = "red"       
ALPHA      = 0.65        

HWND_BOTTOM    = 1
SWP_NOSIZE     = 0x0001
SWP_NOMOVE     = 0x0002
SWP_NOACTIVATE = 0x0010
SW_SHOW        = 5
SW_RESTORE     = 9

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
        hwnd, HWND_BOTTOM, 0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)


# ================= Приложение =================
class NotesApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Заметки")
        self.root.geometry("380x540+{}+{}".format(
            root.winfo_screenwidth() - 400, 30))
        self.root.configure(bg=BG_MAIN)
        
        self.root.attributes("-alpha", ALPHA)
        self.root.attributes("-topmost", False)

        self.events = []
        self.load_error = None
        self.load_data()

        self.warned = {}
        self.pending_alerts = []
        
        # --- НОВОЕ: Переменная для иконки трея ---
        self.tray_icon = None
        self.is_hidden = False

        self.build_ui()
        self.refresh_list()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.check_job = None
        self.alert_job = None
        self.check_events(initial=True)

        self.keep_bottom_job = None
        self.root.after(500, self._ensure_visible)
        self.root.after(1200, self._start_keep_bottom)

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
        except Exception as e:
            print("ensure_visible:", e)

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
                if hwnd and user32.GetForegroundWindow() != hwnd:
                    send_to_bottom(hwnd)
        except Exception:
            pass
        self.keep_bottom_job = self.root.after(2000, self._keep_bottom_tick)

    # ---------------- UI ----------------
    def build_ui(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background=BG_MAIN)
        style.configure("TLabel", background=BG_MAIN, foreground=FG_TEXT)
        style.configure("TButton", background=BG_BUTTON, foreground=FG_TEXT)
        style.map("TButton", background=[("active", "#d0d0d0")])

        top = ttk.Frame(self.root, padding=6)
        top.pack(side="top", fill="x")

        ttk.Button(top, text="+ Добавить", command=self.open_add_dialog)\
            .pack(side="left", padx=2)
        ttk.Button(top, text="✎ Изменить", command=self.edit_selected)\
            .pack(side="left", padx=2)
        ttk.Button(top, text="✖ Удалить", command=self.delete_selected)\
            .pack(side="left", padx=2)
            
        # --- НОВОЕ: Кнопка очистки прошедших ---
        ttk.Button(top, text="Очистить", command=self.clear_past_events)\
            .pack(side="left", padx=2)
            
        ttk.Button(top, text="Свернуть", command=self.hide_window)\
            .pack(side="right", padx=2)

        list_frame = tk.Frame(self.root, bg=BG_MAIN)
        list_frame.pack(fill="both", expand=True, padx=6, pady=4)

        scrollbar = tk.Scrollbar(list_frame, orient="vertical")
        scrollbar.pack(side="right", fill="y")

        self.event_list = tk.Listbox(
            list_frame,
            bg=BG_PANEL,
            fg=FG_TEXT,
            selectbackground="#bcd6f0",
            selectforeground="#000000",
            font=("Arial", 10),
            yscrollcommand=scrollbar.set,
            relief="flat",
            highlightthickness=1,
            highlightbackground="#cccccc"
        )
        self.event_list.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.event_list.yview)
        
        self.event_list.bind("<<ListboxSelect>>", lambda e: self.show_details())

        self.desc = tk.Text(self.root, height=6, bg=BG_PANEL,
                            fg=FG_TEXT, insertbackground=FG_TEXT, wrap="word",
                            relief="flat", highlightthickness=1,
                            highlightbackground="#cccccc")
        self.desc.pack(fill="x", padx=6, pady=(0, 6))
        self.desc.config(state="disabled")

    def show_details(self):
        sel = self.event_list.curselection()
        self.desc.config(state="normal")
        self.desc.delete("1.0", "end")
        if sel:
            ev = self.sorted_events[sel[0]]
            self.desc.insert("1.0", ev.get("description", "(нет описания)"))
        self.desc.config(state="disabled")

    # ---------------- Хранилище ----------------
    def load_data(self):
        if not os.path.exists(DATA_FILE):
            self.events = []
            return
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                events = json.load(f)
            if not isinstance(events, list):
                raise ValueError("Корневое значение должно быть списком")
            event_ids = set()
            for event in events:
                if not isinstance(event, dict):
                    raise ValueError("Запись события должна быть объектом")
                if (not isinstance(event.get("id"), int)
                        or isinstance(event.get("id"), bool)
                        or event["id"] in event_ids):
                    raise ValueError("Идентификаторы событий некорректны")
                if not isinstance(event.get("title"), str):
                    raise ValueError("У события отсутствует название")
                if not isinstance(event.get("datetime"), str):
                    raise ValueError("У события отсутствует дата и время")
                event_dt = datetime.fromisoformat(event["datetime"])
                if event_dt.tzinfo is not None:
                    raise ValueError("Дата события должна быть без часового пояса")
                if not isinstance(event.get("description", ""), str):
                    raise ValueError("Описание события должно быть текстом")
                event_ids.add(event["id"])
            self.events = events
        except (OSError, ValueError) as error:
            self.events = []
            self.load_error = error
            messagebox.showerror(
                "Ошибка чтения",
                f"Не удалось загрузить заметки:\n{DATA_FILE}\n\n{error}")

    def save_data(self, events):
        if self.load_error is not None:
            return False
        temporary_path = None
        try:
            directory = os.path.dirname(os.path.abspath(DATA_FILE))
            with tempfile.NamedTemporaryFile(
                    "w", encoding="utf-8", dir=directory, delete=False) as f:
                temporary_path = f.name
                json.dump(events, f, ensure_ascii=False, indent=2)
            os.replace(temporary_path, DATA_FILE)
            return True
        except (OSError, TypeError, ValueError) as error:
            messagebox.showerror("Ошибка сохранения", f"Не удалось сохранить:\n{error}")
            return False
        finally:
            if temporary_path and os.path.exists(temporary_path):
                try:
                    os.remove(temporary_path)
                except OSError:
                    pass

    def next_id(self):
        return max((e.get("id", 0) for e in self.events), default=0) + 1

    def refresh_list(self):
        self.event_list.delete(0, tk.END)
        self.sorted_events = sorted(self.events, key=lambda e: e.get("datetime", ""))
        
        for i, ev in enumerate(self.sorted_events):
            dt = datetime.fromisoformat(ev["datetime"])
            display_text = f" {dt.strftime('%d.%m.%Y')}  {dt.strftime('%H:%M')}   {ev['title']}"
            self.event_list.insert(tk.END, display_text)
            
            if dt <= datetime.now():
                self.event_list.itemconfig(i, foreground=COLOR_DONE)

    # ---------------- CRUD ----------------
    def open_add_dialog(self):
        EventDialog(self.root, on_save=self.add_event)

    def add_event(self, data):
        event = dict(data, id=self.next_id())
        events = [*self.events, event]
        if not self.save_data(events):
            return False
        self.events = events
        self.reset_event_warnings(event)
        self.refresh_list()
        return True

    def edit_selected(self):
        sel = self.event_list.curselection()
        if not sel:
            messagebox.showinfo("Заметки", "Выберите событие для изменения")
            return
        ev = self.sorted_events[sel[0]]
        EventDialog(
            self.root,
            on_save=lambda data, event_id=ev["id"]: self.update_event(
                event_id, data),
            initial=ev)

    def update_event(self, event_id, data):
        events, updated_event = [], None
        for event in self.events:
            if event["id"] == event_id:
                updated_event = dict(data, id=event_id)
                events.append(updated_event)
            else:
                events.append(event)
        if updated_event is None:
            messagebox.showerror("Ошибка", "Событие больше не существует")
            return False
        if not self.save_data(events):
            return False
        self.events = events
        self.reset_event_warnings(updated_event)
        self.refresh_list()
        return True

    def reset_event_warnings(self, event):
        event_id = event["id"]
        self.warned.pop(event_id, None)
        if datetime.fromisoformat(event["datetime"]) <= datetime.now():
            self.warned[event_id] = {"done"}

    def delete_selected(self):
        sel = self.event_list.curselection()
        if not sel:
            return
        if not messagebox.askyesno("Заметки", "Удалить выбранное событие?"):
            return
        event_id = self.sorted_events[sel[0]]["id"]
        events = [e for e in self.events if e["id"] != event_id]
        if not self.save_data(events):
            return
        self.events = events
        self.warned.pop(event_id, None)
        self.refresh_list()

    # --- НОВОЕ: Очистка прошедших ---
    def clear_past_events(self):
        now = datetime.now()
        past_events = [e for e in self.events if datetime.fromisoformat(e["datetime"]) <= now]
        if not past_events:
            messagebox.showinfo("Заметки", "Нет прошедших событий.")
            return
            
        if not messagebox.askyesno("Заметки", f"Удалить все прошедшие события ({len(past_events)} шт.)?"):
            return
            
        self.events = [e for e in self.events if datetime.fromisoformat(e["datetime"]) > now]
        for e in past_events:
            self.warned.pop(e["id"], None)
            
        self.save_data(self.events)
        self.refresh_list()

    # ---------------- Скрытие в трей ----------------
    def hide_window(self):
        self.root.withdraw()
        self.is_hidden = True
        
        if HAS_TRAY:
            if self.tray_icon is None:
                self._create_tray_icon()
            self.tray_icon.run_detached()
        else:
            # Fallback, если pystray не установлен
            self.tray = tk.Toplevel(self.root)
            self.tray.title("Заметки")
            self.tray.geometry("60x28+{}+{}".format(
                self.root.winfo_screenwidth() - 80, 10))
            self.tray.configure(bg=BG_MAIN)
            self.tray.attributes("-alpha", ALPHA)
            btn = tk.Button(self.tray, text="📝", command=self.restore_window,
                            bg=BG_BUTTON, fg=FG_TEXT, bd=0, font=("Arial", 12))
            btn.pack(fill="both", expand=True)

    def _create_tray_icon(self):
        # Создаем простую иконку
        image = Image.new('RGB', (64, 64), color=(240, 240, 240))
        d = ImageDraw.Draw(image)
        d.rectangle([10, 10, 54, 54], outline="black", width=3)
        d.line([20, 25, 44, 25], fill="black", width=3)
        d.line([20, 35, 44, 35], fill="black", width=3)
        d.line([20, 45, 35, 45], fill="black", width=3)
        
        menu = pystray.Menu(
            pystray.MenuItem('Открыть', self._tray_restore),
            pystray.MenuItem('Выход', self._tray_exit)
        )
        self.tray_icon = pystray.Icon("MyNotes", image, "Заметки", menu)

    def _tray_restore(self, icon, item):
        icon.stop()
        self.tray_icon = None
        self.root.after(0, self.restore_window)

    def _tray_exit(self, icon, item):
        icon.stop()
        self.root.after(0, self.on_close)

    def restore_window(self):
        if not HAS_TRAY and hasattr(self, 'tray'):
            self.tray.destroy()
        self.is_hidden = False
        self.root.deiconify()
        self.root.after(300, self._ensure_visible)

    # ---------------- Проверка событий и напоминания ----------------
    def check_events(self, initial=False):
        self.check_job = None
        now = datetime.now()
        for event in self.events:
            event_dt = datetime.fromisoformat(event["datetime"])
            flags = self.warned.setdefault(event["id"], set())
            delta = (event_dt - now).total_seconds()

            if delta <= 0:
                if initial:
                    flags.add("done")
                elif "done" not in flags:
                    flags.add("done")
                    self.schedule_alert(
                        "🔔 Событие наступило",
                        f"{event['title']}\n"
                        f"Время: {event_dt.strftime('%d.%m.%Y %H:%M')}\n\n"
                        f"{event.get('description', '')}",
                        count=3
                    )
                    self.refresh_list()
            elif delta <= WARN_BEFORE and "warn" not in flags:
                flags.add("warn")
                self.schedule_alert(
                    "⏰ Скоро событие",
                    f"{event['title']}\n"
                    f"Начнётся в {event_dt.strftime('%H:%M:%S')}\n\n"
                    f"{event.get('description', '')}",
                    count=3
                )

        self.check_job = self.root.after(
            CHECK_INTERVAL * 1000, self.check_events)

    def schedule_alert(self, title, text, count=3):
        self.pending_alerts.append({"title": title, "text": text, "left": count})
        if self.alert_job is None:
            self.show_next_alert()

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
            
        if self.check_job is not None:
            self.root.after_cancel(self.check_job)
        if self.keep_bottom_job is not None:
            self.root.after_cancel(self.keep_bottom_job)
        if self.alert_job is not None:
            self.root.after_cancel(self.alert_job)
        self.root.destroy()


# ================= Диалог события =================
class EventDialog(tk.Toplevel):
    def __init__(self, parent, on_save, initial=None):
        super().__init__(parent)
        self.on_save = on_save
        self.title("Событие")
        self.geometry("340x330")
        self.configure(bg=BG_MAIN)
        self.attributes("-alpha", 1.0)
        self.resizable(False, False)

        pad = {"padx": 10, "pady": 4}

        tk.Label(self, text="Название:", bg=BG_MAIN, fg=FG_TEXT)\
            .pack(anchor="w", **pad)
        self.title_entry = tk.Entry(self, bg=BG_PANEL, fg=FG_TEXT,
                                    insertbackground=FG_TEXT, relief="solid", bd=1)
        self.title_entry.pack(fill="x", padx=10)
        # НОВОЕ: Привязка Enter к сохранению
        self.title_entry.bind("<Return>", lambda e: self.save())

        tk.Label(self, text="Описание:", bg=BG_MAIN, fg=FG_TEXT)\
            .pack(anchor="w", **pad)
        self.desc_text = tk.Text(self, height=4, wrap="word",
                                 bg=BG_PANEL, fg=FG_TEXT,
                                 insertbackground=FG_TEXT, relief="solid", bd=1)
        self.desc_text.pack(fill="x", padx=10)

        tk.Label(self, text="Дата (ДД.ММ.ГГГГ):", bg=BG_MAIN, fg=FG_TEXT)\
            .pack(anchor="w", **pad)
        self.date_entry = tk.Entry(self, bg=BG_PANEL, fg=FG_TEXT,
                                   insertbackground=FG_TEXT, relief="solid", bd=1)
        self.date_entry.pack(fill="x", padx=10)
        self.date_entry.bind("<Return>", lambda e: self.save())

        tk.Label(self, text="Время (ЧЧ:ММ):", bg=BG_MAIN, fg=FG_TEXT)\
            .pack(anchor="w", **pad)
        self.time_entry = tk.Entry(self, bg=BG_PANEL, fg=FG_TEXT,
                                   insertbackground=FG_TEXT, relief="solid", bd=1)
        self.time_entry.pack(fill="x", padx=10)
        self.time_entry.bind("<Return>", lambda e: self.save())

        tk.Button(self, text="Сохранить", command=self.save,
                  bg=BG_BUTTON, fg=FG_TEXT, relief="flat").pack(pady=10)

        if initial:
            self.title_entry.insert(0, initial.get("title", ""))
            self.desc_text.insert("1.0", initial.get("description", ""))
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
            dt = datetime.strptime(
                f"{self.date_entry.get().strip()} {self.time_entry.get().strip()}",
                "%d.%m.%Y %H:%M")
        except ValueError:
            messagebox.showerror("Ошибка",
                                 "Неверный формат даты/времени.\n"
                                 "Используйте ДД.ММ.ГГГГ и ЧЧ:ММ", parent=self)
            return
        data = {
            "title": title,
            "description": self.desc_text.get("1.0", "end").strip(),
            "datetime": dt.isoformat(timespec="minutes"),
        }
        if self.on_save(data):
            self.destroy()


# --- НОВОЕ: Защита от запуска двух копий ---
def is_already_running():
    if not IS_WINDOWS:
        return False
    mutex_name = "Global\\MyNotesAppMutex_UniqueName123"
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, mutex_name)
    # 183 = ERROR_ALREADY_EXISTS
    return kernel32.GetLastError() == 183

if __name__ == "__main__":
    if is_already_running():
        root = tk.Tk()
        root.withdraw()
        messagebox.showwarning("Заметки", "Программа уже запущена!")
        sys.exit(0)

    root = tk.Tk()
    app = NotesApp(root)
    root.mainloop()