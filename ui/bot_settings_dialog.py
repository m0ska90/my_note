"""Диалог настройки токена MAX-бота."""

import customtkinter as ctk
from tkinter import TclError, messagebox

from config import APP_FONT, BG_MAIN, CERT_PATH
from crypto_utils import load_token, save_token


class BotSettingsDialog(ctk.CTkToplevel):
    """Просмотр и сохранение токена MAX-бота."""

    def __init__(self, main_app):
        self.main_app = main_app
        super().__init__(main_app.root)
        self.title("Настройка MAX-бота")
        self.geometry("520x230")
        self.resizable(False, False)
        self.configure(fg_color=BG_MAIN)
        self.transient(main_app.root)
        self.grab_set()

        ctk.CTkLabel(
            self,
            text="Токен бота MAX:",
            font=APP_FONT,
            anchor="w",
        ).pack(fill="x", padx=20, pady=(20, 6))

        entry_row = ctk.CTkFrame(self, fg_color="transparent")
        entry_row.pack(fill="x", padx=20)

        self.token_entry = ctk.CTkEntry(
            entry_row,
            font=("Segoe UI", 16),
            show="*",
            state="normal",
        )
        self.token_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.token_entry.bind("<Button-3>", self._paste_token)
        self.token_entry.bind("<Control-v>", self._paste_token)
        self.token_entry.bind("<Control-V>", self._paste_token)
        self.token_entry.bind("<Shift-Insert>", self._paste_token)

        self._token_visible = False
        ctk.CTkButton(
            entry_row,
            text="📋 Вставить",
            command=self._paste_token,
            font=("Segoe UI", 14),
            width=120,
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            entry_row,
            text="👁 Показать/Скрыть",
            command=self._toggle_token_visibility,
            font=("Segoe UI", 14),
            width=160,
        ).pack(side="right")

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(fill="x", padx=20, pady=20)
        ctk.CTkButton(
            buttons,
            text="Сохранить токен",
            command=self._save,
            font=APP_FONT,
            height=42,
        ).pack(side="left", fill="x", expand=True, padx=(0, 5))
        ctk.CTkButton(
            buttons,
            text="Проверить",
            command=self._check_token,
            font=APP_FONT,
            height=42,
        ).pack(side="left", fill="x", expand=True, padx=(5, 0))

        try:
            token = load_token()
        except (OSError, RuntimeError, UnicodeError, ValueError) as error:
            messagebox.showerror(
                "Ошибка",
                f"Не удалось загрузить сохранённый токен: {error}",
                parent=self,
            )
        else:
            if token:
                self.token_entry.insert(0, token)

        self.token_entry.focus_set()
        self.token_entry.select_range(0, "end")

    def _paste_token(self, _event=None) -> str:
        try:
            clipboard_text = self.clipboard_get()
        except TclError:
            messagebox.showwarning(
                "Буфер обмена",
                "Не удалось получить текст из буфера обмена.",
                parent=self,
            )
            return "break"

        entry = self.token_entry._entry
        if entry.selection_present():
            start = self.token_entry.index("sel.first")
            end = self.token_entry.index("sel.last")
            self.token_entry.delete(start, end)
        else:
            start = self.token_entry.index("insert")

        self.token_entry.insert(start, clipboard_text)
        self.token_entry.icursor(start + len(clipboard_text))
        return "break"

    def _toggle_token_visibility(self) -> None:
        self._token_visible = not self._token_visible
        self.token_entry.configure(show="" if self._token_visible else "*")

    def _save(self) -> None:
        token = self.token_entry.get().strip()
        if not token:
            messagebox.showwarning(
                "Пустой токен",
                "Введите токен бота MAX.",
                parent=self,
            )
            return

        try:
            save_token(token)
        except (OSError, RuntimeError, ValueError) as error:
            messagebox.showerror(
                "Ошибка",
                f"Не удалось сохранить токен: {error}",
                parent=self,
            )
            return

        bot_restarted = self.main_app.restart_bot()
        if bot_restarted:
            messagebox.showinfo(
                "Успех",
                "Токен сохранен, бот перезапущен.",
                parent=self,
            )
        else:
            messagebox.showwarning(
                "Токен сохранен",
                "Токен сохранен, но бота не удалось перезапустить.",
                parent=self,
            )
        self.destroy()

    def _check_token(self) -> None:
        token = self.token_entry.get().strip()
        if not token:
            messagebox.showwarning(
                "Пустой токен",
                "Введите токен бота MAX для проверки.",
                parent=self,
            )
            return

        try:
            import requests

            response = requests.get(
                "https://platform-api2.max.ru/me",
                headers={"Authorization": token},
                verify=CERT_PATH,
                timeout=10,
            )
        except requests.RequestException as error:
            messagebox.showerror(
                "Ошибка проверки",
                f"Не удалось проверить токен: {error}",
                parent=self,
            )
            return

        if response.status_code == 200:
            messagebox.showinfo("Проверка токена", "Токен принят API MAX.", parent=self)
        elif response.status_code == 401:
            messagebox.showwarning(
                "Проверка токена",
                "API MAX отклонил токен (401 Unauthorized).",
                parent=self,
            )
        else:
            messagebox.showwarning(
                "Проверка токена",
                f"API MAX вернул HTTP {response.status_code}.",
                parent=self,
            )
