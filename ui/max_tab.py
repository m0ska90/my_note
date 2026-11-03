from datetime import datetime

import tkinter as tk

import customtkinter as ctk

from config import APP_FONT, BG_PANEL, FG_TEXT, INBOX_DIR


class MaxTab(ctk.CTkFrame):
    def __init__(self, parent, main_app):
        super().__init__(parent, fg_color="transparent")
        self.main_app = main_app
        self.inbox_files = []
        self._build_ui()

    def _build_ui(self):
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(side="top", fill="x")
        ctk.CTkButton(
            top, text="🔄 Обновить", command=self.main_app.refresh_inbox,
            font=APP_FONT,
        ).pack(side="left", padx=2, pady=6)
        ctk.CTkButton(
            top, text="🗑 Очистить", command=self.main_app.clear_inbox_list,
            font=APP_FONT,
        ).pack(side="left", padx=2, pady=6)
        ctk.CTkButton(
            top,
            text="📂 Открыть папку",
            command=lambda: self.main_app.open_file(INBOX_DIR),
            font=APP_FONT,
        ).pack(side="left", padx=6, pady=6)

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
