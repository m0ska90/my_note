from datetime import datetime

import tkinter as tk

import customtkinter as ctk
from tkinter import messagebox

from config import APP_FONT, BG_PANEL, FG_TEXT, INBOX_DIR
from database import clear_max_text_notes


class MaxTab(ctk.CTkFrame):
    def __init__(self, parent, main_app):
        super().__init__(parent, fg_color="transparent")
        self.main_app = main_app
        self.inbox_files = []
        self._build_ui()

    def _build_ui(self):
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(side="top", fill="x")

        action_row = ctk.CTkFrame(top, fg_color="transparent")
        action_row.pack(side="top", anchor="w")
        ctk.CTkButton(
            action_row,
            text="🔄 Обновить",
            command=self.main_app.refresh_inbox,
            width=130,
            font=APP_FONT,
        ).pack(side="left", padx=5, pady=6)
        ctk.CTkButton(
            action_row,
            text="🗑 Очистить",
            command=self.main_app.clear_inbox_list,
            width=130,
            font=APP_FONT,
        ).pack(side="left", padx=5, pady=6)

        folder_row = ctk.CTkFrame(top, fg_color="transparent")
        folder_row.pack(side="top", anchor="w")
        ctk.CTkButton(
            folder_row,
            text="📂 Открыть папку",
            command=lambda: self.main_app.open_file(INBOX_DIR),
            width=170,
            font=APP_FONT,
        ).pack(side="left", padx=5, pady=6)

        self.inbox_list = tk.Listbox(
            self,
            bg=BG_PANEL,
            fg=FG_TEXT,
            selectbackground="#bcd6f0",
            font=APP_FONT,
            relief="flat",
            highlightthickness=1,
            highlightbackground="#cccccc",
        )
        self.inbox_list.pack(fill="both", expand=True, padx=6, pady=4)
        self.inbox_list.bind("<Double-1>", self.main_app.open_inbox_file)

        ctk.CTkLabel(self, text="Текст заметки из бота:", font=APP_FONT).pack(
            anchor="w", padx=6
        )
        
        # Кнопка очистки истории текстовых заметок
        ctk.CTkButton(
            self,
            text="🗑 Очистить",
            command=self._show_clear_confirmation,
            width=100,
            font=APP_FONT,
        ).pack(anchor="e", padx=6, pady=(0, 4))
        
        self.max_text = ctk.CTkTextbox(
            self, height=120, wrap="word", font=APP_FONT
        )
        self.max_text.pack(fill="x", padx=6, pady=(0, 6))
        self.max_text.configure(state="disabled")

    def refresh(self, attachments, max_notes):
        self.inbox_list.delete(0, tk.END)
        self.inbox_files = []
        for file_path, original_name, note_title in attachments:
            self.inbox_list.insert(
                tk.END, f"📎 {original_name} (к: {note_title})"
            )
            self.inbox_files.append(file_path)

        self.max_text.configure(state="normal")
        self.max_text.delete("1.0", "end")
        if max_notes:
            for created_at, description in max_notes:
                dt = datetime.fromisoformat(created_at)
                self.max_text.insert(
                    tk.END,
                    f"[{dt.strftime('%d.%m %H:%M')}] {description}\n\n",
                )
        else:
            self.max_text.insert(tk.END, "Текстовых заметок из бота пока нет.")
        self.max_text.configure(state="disabled")

    def _show_clear_confirmation(self) -> None:
        """Открыть модальное окно для подтверждения очистки текстовых заметок."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("Очистка истории")
        dialog.geometry("420x200")
        dialog.attributes("-topmost", True)
        dialog.transient(self.main_app.root)
        dialog.resizable(False, False)

        # Центрируем окно относительно главного окна
        dialog.update_idletasks()
        x = self.main_app.root.winfo_x() + (self.main_app.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.main_app.root.winfo_y() + (self.main_app.root.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")

        pad = {"padx": 20, "pady": 10}
        
        ctk.CTkLabel(
            dialog,
            text="Для очистки истории текста из бота,\nвведите 'очистить' и нажмите Ввод",
            font=APP_FONT,
            justify="center",
        ).pack(fill="x", **pad)

        entry = ctk.CTkEntry(
            dialog,
            font=("Segoe UI", 14),
            width=300,
        )
        entry.pack(pady=(0, 10))
        entry.focus_set()

        def on_submit():
            value = entry.get().lower().strip()
            if value == "очистить":
                try:
                    deleted_count = clear_max_text_notes()
                    messagebox.showinfo(
                        "Очищено",
                        f"Удалено {deleted_count} записей из бота.",
                        parent=dialog,
                    )
                    self.main_app.refresh_inbox()
                except Exception as e:
                    messagebox.showerror(
                        "Ошибка",
                        f"Не удалось удалить записи: {e}",
                        parent=dialog,
                    )
                finally:
                    dialog.destroy()
            else:
                messagebox.showerror(
                    "Ошибка",
                    "Для подтверждения введите 'очистить'.",
                    parent=dialog,
                )
                entry.delete(0, "end")
                entry.focus_set()

        # Привязываем Enter к submit
        entry.bind("<Return>", lambda event: on_submit())
        
        ctk.CTkButton(
            dialog,
            text="ОК",
            font=APP_FONT,
            command=on_submit,
        ).pack(pady=(0, 15))
