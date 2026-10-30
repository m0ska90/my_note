import tkinter as tk
from tkinter import ttk, messagebox
import json
import os
import tempfile
from datetime import datetime, timedelta

# ================= Windows API =================
try:
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    IS_WINDOWS = True
except Exception:
    IS_WINDOWS = False

DATA_FILE = "notes_data.json"
CHECK_INTERVAL = 30
WARN_BEFORE = 60

# ---- Светлая палитра ----
BG_MAIN    = "#f2f2f2"   
BG_PANEL   = "#ffffff"   
BG_BUTTON  = "#e0e0e0"   
FG_TEXT    = "#202020"   
COLOR_DONE = "red"       # Цвет для наступивших событий
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
        self.root.geometry("360x520+{}+{}".format(
            root.winfo_screenwidth() - 380, 30))
        self.root.configure(bg=BG_MAIN)
        
        self.root.attributes("-alpha", ALPHA)
        self.root.attributes("-topmost", False)

        self.events = []
        self.load_error = None
        self.load_data()

        self.warned = {}
        self.pending_alerts = []  # Очередь для отложенных напоминаний

        self.build_ui()
        self.refresh_list()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.check_job = None
        self.alert_job = None
        self.ensure_visible_job = None
        self.check_events(initial=True)

        self.keep_bottom_job = None
        self.ensure_visible_job = self.root.after(500, self._ensure_visible)
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

        self.desc = tk.Text(self.root, height=5, bg=BG_PANEL,
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
        self.load_error = None
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
                f"Не удалось загрузить заметки из {DATA_FILE}:\n{error}\n\n"
                "Приложение откроется с пустым списком.\n"
                "После исправления файла можно сохранить заметки снова.")

    def save_data(self, events):
        if self.load_error is not None:
            answer = messagebox.askyesno(
                "Ошибка чтения",
                f"Файл заметок повреждён ({self.load_error}).\n"
                "Перезаписать его новыми данными?")
            if not answer:
                return False
        temporary_path = None
        try:
            directory = os.path.dirname(os.path.abspath(DATA_FILE))
            with tempfile.NamedTemporaryFile(
                    "w", encoding="utf-8", dir=directory, delete=False) as f:
                temporary_path = f.name
                json.dump(events, f, ensure_ascii=False, indent=2)
            os.replace(temporary_path, DATA_FILE)
            self.load_error = None
            return True
        except (OSError, TypeError, ValueError) as error:
            messagebox.showerror("Ошибка сохранения",
                                 f"Не удалось сохранить заметки:\n{error}")
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
            
            # Красим в красный, если событие уже наступило
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

    # ---------------- Скрытие / восстановление ----------------
    def hide_window(self):
        if getattr(self, "tray", None) is not None and self.tray.winfo_exists():
            return
        self.root.withdraw()
        self.tray = tk.Toplevel(self.root)
        self.tray.title("Заметки")
        self.tray.geometry("60x28+{}+{}".format(
            self.root.winfo_screenwidth() - 80, 10))
        self.tray.configure(bg=BG_MAIN)
        self.tray.attributes("-alpha", ALPHA)

        btn = tk.Button(self.tray, text="📝", command=self.restore_window,
                        bg=BG_BUTTON, fg=FG_TEXT, bd=0, font=("Arial", 12))
        btn.pack(fill="both", expand=True)

    def restore_window(self):
        if getattr(self, "tray", None) is not None and self.tray.winfo_exists():
            self.tray.destroy()
            self.tray = None
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
                    # Обновляем список, чтобы событие стало красным
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
        """Добавляет оповещение в очередь и запускает процесс показа"""
        self.pending_alerts.append({"title": title, "text": text, "left": count})
        if self.alert_job is None:
            self.show_next_alert()

    def show_next_alert(self):
        """Показывает следующее оповещение из очереди"""
        if not self.pending_alerts:
            self.alert_job = None
            return

        alert = self.pending_alerts[0]
        messagebox.showwarning(alert["title"], alert["text"])
        
        alert["left"] -= 1
        if alert["left"] > 0:
            # Ждем 10 секунд и показываем снова
            self.alert_job = self.root.after(10000, self.show_next_alert)
        else:
            # Оповещение завершено, удаляем из очереди
            self.pending_alerts.pop(0)
            self.alert_job = None
            # Если есть следующие — показываем сразу
            if self.pending_alerts:
                self.alert_job = self.root.after(100, self.show_next_alert)

    def on_close(self):
        if self.ensure_visible_job is not None:
            self.root.after_cancel(self.ensure_visible_job)
            self.ensure_visible_job = None
        if self.check_job is not None:
            self.root.after_cancel(self.check_job)
            self.check_job = None
        if self.keep_bottom_job is not None:
            self.root.after_cancel(self.keep_bottom_job)
            self.keep_bottom_job = None
        if self.alert_job is not None:
            self.root.after_cancel(self.alert_job)
            self.alert_job = None
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
                                    insertbackground=FG_TEXT, relief="solid",
                                    bd=1)
        self.title_entry.pack(fill="x", padx=10)

        tk.Label(self, text="Описание:", bg=BG_MAIN, fg=FG_TEXT)\
            .pack(anchor="w", **pad)
        self.desc_text = tk.Text(self, height=4, wrap="word",
                                 bg=BG_PANEL, fg=FG_TEXT,
                                 insertbackground=FG_TEXT, relief="solid",
                                 bd=1)
        self.desc_text.pack(fill="x", padx=10)

        tk.Label(self, text="Дата (ДД.ММ.ГГГГ):", bg=BG_MAIN, fg=FG_TEXT)\
            .pack(anchor="w", **pad)
        self.date_entry = tk.Entry(self, bg=BG_PANEL, fg=FG_TEXT,
                                   insertbackground=FG_TEXT, relief="solid",
                                   bd=1)
        self.date_entry.pack(fill="x", padx=10)

        tk.Label(self, text="Время (ЧЧ:ММ):", bg=BG_MAIN, fg=FG_TEXT)\
            .pack(anchor="w", **pad)
        self.time_entry = tk.Entry(self, bg=BG_PANEL, fg=FG_TEXT,
                                   insertbackground=FG_TEXT, relief="solid",
                                   bd=1)
        self.time_entry.pack(fill="x", padx=10)

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
            messagebox.showerror("Ошибка", "Введите название события",
                                 parent=self)
            return
        try:
            dt = datetime.strptime(
                f"{self.date_entry.get().strip()} {self.time_entry.get().strip()}",
                "%d.%m.%Y %H:%M")
        except ValueError:
            messagebox.showerror("Ошибка",
                                 "Неверный формат даты/времени.\n"
                                 "Используйте ДД.ММ.ГГГГ и ЧЧ:ММ",
                                 parent=self)
            return
        data = {
            "title": title,
            "description": self.desc_text.get("1.0", "end").strip(),
            "datetime": dt.isoformat(timespec="minutes"),
        }
        if self.on_save(data):
            self.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = NotesApp(root)
    root.mainloop()