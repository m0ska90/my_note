from datetime import datetime, timedelta

import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox

from config import APP_FONT, BG_MAIN, BG_PANEL, COLOR_DONE, FG_TEXT


class EventsTab(ctk.CTkFrame):
    def __init__(self, parent, main_app):
        super().__init__(parent, fg_color="transparent")
        self.main_app = main_app
        self.sorted_events = []
        self._build_ui()

    def _build_ui(self):
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(side="top", fill="x")

        actions = ctk.CTkFrame(top, fg_color="transparent")
        actions.pack(expand=True)
        for column in range(3):
            actions.grid_columnconfigure(
                column, weight=0, uniform="action_buttons"
            )

        ctk.CTkButton(
            actions,
            text="+ Добавить",
            command=self.main_app.open_add_dialog,
            width=100,
            font=APP_FONT,
        ).grid(row=0, column=0, padx=5, pady=5, sticky="w")
        ctk.CTkButton(
            actions,
            text="✎ Изменить",
            command=self.main_app.edit_selected,
            width=100,
            font=APP_FONT,
        ).grid(row=0, column=1, padx=5, pady=5, sticky="w")
        ctk.CTkButton(
            actions,
            text="✖ Удалить",
            command=self.main_app.delete_selected,
            width=100,
            font=APP_FONT,
        ).grid(row=0, column=2, padx=5, pady=5, sticky="w")

        list_frame = ctk.CTkFrame(self, fg_color="transparent")
        list_frame.pack(fill="both", expand=True, padx=6, pady=4)

        scrollbar = tk.Scrollbar(list_frame, orient="vertical")
        scrollbar.pack(side="right", fill="y")
        self.event_list = tk.Listbox(
            list_frame,
            bg=BG_PANEL,
            fg=FG_TEXT,
            selectbackground="#bcd6f0",
            selectforeground="#000000",
            font=APP_FONT,
            yscrollcommand=scrollbar.set,
            relief="flat",
            highlightthickness=1,
            highlightbackground="#cccccc",
        )
        self.event_list.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.event_list.yview)
        self.event_list.bind("<<ListboxSelect>>", self.show_details)

        self.desc = ctk.CTkTextbox(self, height=120, wrap="word", font=APP_FONT)
        self.desc.pack(fill="x", padx=6, pady=(0, 6))
        self.desc.configure(state="disabled")

    def refresh(self, rows):
        self.event_list.delete(0, tk.END)
        self.sorted_events = rows

        for index, row in enumerate(rows):
            title, remind_at = row[1], row[3]
            if remind_at:
                dt = datetime.fromisoformat(remind_at)
                display_text = (
                    f" {dt.strftime('%d.%m.%Y')}  {dt.strftime('%H:%M')}   {title}"
                )
            else:
                display_text = f" Без даты                  {title}"

            self.event_list.insert(tk.END, display_text)
            if remind_at and datetime.fromisoformat(remind_at) <= datetime.now():
                self.event_list.itemconfig(index, foreground=COLOR_DONE)

    def show_details(self, event=None):
        if event is not None and event.widget is not self.event_list:
            return
        selection = self.event_list.curselection()
        self.desc.configure(state="normal")
        self.desc.delete("1.0", "end")
        if selection:
            event_row = self.sorted_events[selection[0]]
            self.desc.insert("1.0", event_row[2] if event_row[2] else "(нет описания)")
        self.desc.configure(state="disabled")


class EventDialog(ctk.CTkToplevel):
    def __init__(self, parent, on_save, initial=None):
        super().__init__(parent)
        self.on_save = on_save
        self.title("Событие")
        self.geometry("340x380")
        self.configure(fg_color=BG_MAIN)
        self.attributes("-alpha", 1.0)
        self.resizable(False, False)

        pad = {"padx": 10, "pady": 4}
        ctk.CTkLabel(self, text="Название:", font=APP_FONT).pack(anchor="w", **pad)
        self.title_entry = ctk.CTkEntry(self, font=APP_FONT)
        self.title_entry.pack(fill="x", padx=10)

        ctk.CTkLabel(self, text="Описание:", font=APP_FONT).pack(anchor="w", **pad)
        self.desc_text = ctk.CTkTextbox(
            self, height=100, wrap="word", font=APP_FONT
        )
        self.desc_text.pack(fill="x", padx=10)

        ctk.CTkLabel(self, text="Дата (ДД.ММ.ГГГГ):", font=APP_FONT).pack(
            anchor="w", **pad
        )
        self.date_entry = ctk.CTkEntry(self, font=APP_FONT)
        self.date_entry.pack(fill="x", padx=10)

        ctk.CTkLabel(self, text="Время (ЧЧ:ММ):", font=APP_FONT).pack(
            anchor="w", **pad
        )
        self.time_entry = ctk.CTkEntry(self, font=APP_FONT)
        self.time_entry.pack(fill="x", padx=10)

        ctk.CTkButton(
            self, text="Сохранить", command=self.save, font=APP_FONT
        ).pack(pady=10)

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
            dt = datetime.strptime(
                f"{self.date_entry.get().strip()} {self.time_entry.get().strip()}",
                "%d.%m.%Y %H:%M",
            )
        except ValueError:
            messagebox.showerror(
                "Ошибка",
                "Неверный формат даты/времени.\nИспользуйте ДД.ММ.ГГГГ и ЧЧ:ММ",
                parent=self,
            )
            return

        data = {
            "title": title,
            "description": self.desc_text.get("1.0", "end").strip(),
            "datetime": dt.isoformat(timespec="minutes"),
        }
        if self.on_save(data):
            self.destroy()
