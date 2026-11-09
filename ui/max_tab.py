from datetime import datetime

import tkinter as tk

import customtkinter as ctk
from tkinter import messagebox

from config import APP_FONT, BG_PANEL, INBOX_DIR
from database import clear_max_text_notes, is_note_processed
from ui.bot_settings_dialog import BotSettingsDialog
from ui.order_dialog import OrderDialog


class MaxTab(ctk.CTkFrame):
    def __init__(self, parent, main_app):
        super().__init__(parent, fg_color="transparent")
        self.main_app = main_app
        self.selected_card: ctk.CTkFrame | None = None
        self.selected_max_text: str = ""  # Текст выбранной карточки
        self.selected_note_id: int = None  # ID выбранной заметки
        self.all_cards: list[ctk.CTkFrame] = []  # Список всех карточек
        self._build_ui()

    def _build_ui(self):
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(side="top", fill="x")

        action_row = ctk.CTkFrame(top, fg_color="transparent")
        action_row.pack(side="top", anchor="w")
        
        # Увеличены размеры кнопок под новый крупный шрифт
        ctk.CTkButton(
            action_row,
            text="🔄 Обновить",
            command=self.main_app.refresh_inbox,
            width=180,
            height=45,
            font=APP_FONT,
        ).pack(side="left", padx=5, pady=6)
        ctk.CTkButton(
            action_row,
            text="⚙ Настроить бота",
            command=lambda: BotSettingsDialog(self.main_app),
            width=220,
            height=45,
            font=APP_FONT,
        ).pack(side="left", padx=5, pady=6)
        ctk.CTkButton(
            action_row,
            text="🗑 Очистить",
            command=self.main_app.clear_inbox_list,
            width=180,
            height=45,
            font=APP_FONT,
        ).pack(side="left", padx=5, pady=6)
        ctk.CTkButton(
            action_row,
            text="📦 Оформить заказ",
            command=lambda: self._open_order_dialog(
                note_text=getattr(self, "selected_max_text", ""),
                note_id=getattr(self, "selected_note_id", None),
            ),
            width=180,
            height=45,
            font=APP_FONT,
        ).pack(side="left", padx=5, pady=6)
        ctk.CTkButton(
            action_row,
            text="➡ В события",
            command=self._open_add_event_from_selected,
            width=180,
            height=45,
            font=APP_FONT,
        ).pack(side="left", padx=5, pady=6)

        folder_row = ctk.CTkFrame(top, fg_color="transparent")
        folder_row.pack(side="top", anchor="w")
        ctk.CTkButton(
            folder_row,
            text="📂 Открыть папку",
            command=lambda: self.main_app.open_file(INBOX_DIR),
            width=220,
            height=45,
            font=APP_FONT,
        ).pack(side="left", padx=5, pady=6)

        attachments_header = ctk.CTkLabel(
            self,
            text="Файлы из MAX:",
            font=APP_FONT,
            anchor="w",
        )
        attachments_header.pack(fill="x", padx=6, pady=(4, 0))
        self.inbox_list = ctk.CTkScrollableFrame(
            self,
            height=60,
            corner_radius=8,
            border_width=1,
            border_color="#cccccc",
        )
        self.inbox_list.pack(fill="x", padx=6, pady=4)

        # --- Блок: Текст заказа из MAX ---
        self._build_max_notes_ui()

    def _build_max_notes_ui(self):
        """Создать UI для текстовых заметок из бота (карточки)."""
        pad = {"padx": 6, "pady": (0, 4)}

        # Заголовок + кнопка
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.pack(fill="x", **pad)

        ctk.CTkLabel(
            header_frame,
            text="Текст заказа из MAX:",
            font=APP_FONT,
            anchor="w",
        ).pack(side="left", fill="x", expand=True)

        ctk.CTkButton(
            header_frame,
            text="🗑 Очистить",
            command=self._show_clear_confirmation,
            width=100,
            font=APP_FONT,
        ).pack(side="right", padx=(6, 0))

        # Скроллируемая область с карточками
        self.max_text = ctk.CTkScrollableFrame(
            self,
            height=380,
            corner_radius=8,
            border_width=1,
            border_color="#cccccc",
        )
        self.max_text.pack(fill="both", expand=True, **pad)

    def refresh(self, attachments, max_notes):
        for widget in self.inbox_list.winfo_children():
            widget.destroy()
        for file_path, original_name, note_title in attachments:
            self._create_attachment_card(file_path, original_name, note_title)

        # Очищаем карточки
        for widget in self.max_text.winfo_children():
            try:
                widget.destroy()
            except tk.TclError:
                pass  # виджет уже удалён или недоступен
        self.all_cards = []
        self.selected_card = None
        self.selected_max_text = ""  # Сбрасываем при обновлении
        self.selected_note_id = None

        if not max_notes:
            ctk.CTkLabel(
                self.max_text,
                text="Текстовых заметок из бота пока нет.",
                font=("Segoe UI", 13),
                text_color="#999999",
            ).pack(pady=30)
            return

        for i, (note_id, created_at, description) in enumerate(max_notes):
            dt = datetime.fromisoformat(created_at)
            card = self._create_note_card(dt, description, note_id, i)
            self.all_cards.append(card)

    def _create_attachment_card(
        self, file_path: str, original_name: str, note_title: str
    ) -> None:
        card = ctk.CTkFrame(self.inbox_list, corner_radius=8, fg_color=BG_PANEL)
        card.pack(fill="x", padx=4, pady=3)

        ctk.CTkLabel(
            card,
            text=f"📎 {original_name} (к: {note_title})",
            font=("Segoe UI", 13),
            anchor="w",
        ).pack(side="left", fill="x", expand=True, padx=8, pady=6)

        ctk.CTkButton(
            card,
            text="Открыть",
            width=75,
            command=lambda path=file_path: self.main_app.open_inbox_file(path),
        ).pack(side="right", padx=(4, 6), pady=4)

    def _create_note_card(self, dt: datetime, text: str, note_id: int = None, index: int = 0) -> ctk.CTkFrame:
        """Создать карточку для одной текстовой заметки."""
        note_processed = is_note_processed(note_id)
        card = ctk.CTkFrame(
            self.max_text,
            corner_radius=8,
            border_width=0,  # Без рамки по умолчанию
            fg_color="#E8F5E9" if note_processed else "transparent",
        )
        card.pack(fill="x", padx=4, pady=(0, 6))
        card.configure(cursor="hand2")  # Курсор-рука при наведении

        # Сохраняем текст и ID заметки в атрибут карточки
        card.note_text = text
        card.note_id = note_id
        card.note_processed = note_processed

        # Создаём все дочерние элементы с крупным шрифтом, прижаты к левому краю
        time_label = self._create_child_label(
            card,
            text=(
                f"📅  {dt.strftime('%d.%m.%Y  %H:%M:%S')}"
                f"{'  ✅' if note_processed else ''}"
            ),
            font=("Segoe UI", 16),  # Увеличено для читаемости
            text_color="#888888",
            anchor="w",
        )
        time_label.pack(fill="x", padx=4, pady=(8, 0))

        # Разделитель
        divider = self._create_child_frame(
            card, height=1, fg_color="#e8e8e8"
        )
        divider.pack(fill="x", padx=4, pady=(4, 0))

        # Текст заметки — крупный шрифт, на всю ширину карточки, прижат к левому краю
        content_label = self._create_child_label(
            card,
            text=text,
            font=("Segoe UI", 20),  # Увеличено для читаемости
            justify="left",
            anchor="w",
        )
        content_label.pack(fill="x", padx=4, pady=(4, 8))

        # Привязываем события мыши КО ВСЕМ внутренним элементам
        # Чтобы клик по тексту тоже считался кликом по карточке
        self._bind_card_events(card, text, note_id)

        return card

    def _open_order_dialog(self, file_path: str = "", note_text: str = "", note_id: int = None) -> None:
        OrderDialog(
            self.main_app.root,
            file_path=file_path,
            note_text=note_text,
            note_id=note_id,
            on_saved=self.main_app.refresh_inbox,
        )

    def _bind_card_events(self, card: ctk.CTkFrame, text: str, note_id: int = None) -> None:
        """Привязать события мыши ко всем элементам карточки.

        Это нужно, потому что внутренние CTkLabel перехватывают события мыши,
        и клик по тексту не доходит до CTkFrame.
        """
        # Обработчики для самой карточки
        card.bind("<Button-1>", lambda e: self._on_card_click(card, text, note_id))
        card.bind("<Enter>", lambda e: self._on_card_hover(card, True))
        card.bind("<Leave>", lambda e: self._on_card_hover(card, False))

        # Рекурсивно привязываем ко всем дочерним элементам
        for child in card.winfo_children():
            self._bind_events_recursive(child, card, text, note_id)

    def _bind_events_recursive(self, widget, card: ctk.CTkFrame, text: str, note_id: int = None) -> None:
        """Рекурсивно привязать события ко всем вложенным виджетам."""
        # Привязываем события мыши
        widget.bind("<Button-1>", lambda e: self._on_card_click(card, text, note_id))
        widget.bind("<Enter>", lambda e: self._on_card_hover(card, True))
        widget.bind("<Leave>", lambda e: self._on_card_hover(card, False))

        # Рекурсия для вложенных элементов
        for child in widget.winfo_children():
            self._bind_events_recursive(child, card, text, note_id)

    def _create_child_label(self, parent, **kwargs) -> ctk.CTkLabel:
        """Создать CTkLabel с курсором-рукой."""
        label = ctk.CTkLabel(parent, **kwargs)
        label.configure(cursor="hand2")
        return label

    def _create_child_frame(self, parent, **kwargs) -> ctk.CTkFrame:
        """Создать CTkFrame с курсором-рукой."""
        frame = ctk.CTkFrame(parent, **kwargs)
        frame.configure(cursor="hand2")
        return frame

    def _on_card_hover(self, card: ctk.CTkFrame, is_enter: bool) -> None:
        """Обработка наведения мыши на карточку.
        
        При наведении меняем фон, но НЕ сбрасываем выделение,
        если карточка выбрана.
        """
        if card is None:
            return

        try:
            if not card.winfo_exists():
                return
        except tk.TclError:
            return

        if is_enter:
            # При наведении - чуть затемняем, но не переопределяем выделение
            if card == self.selected_card:
                # Если карточка выбрана - оставляем синий фон
                pass
            else:
                # Если не выбрана - слегка затемняем
                card.configure(fg_color="#f0f0f0")
        else:
            # При уходе мыши возвращаем исходный фон, не сбрасывая выделение.
            if card != self.selected_card:
                card.configure(
                    fg_color="#E8F5E9"
                    if getattr(card, "note_processed", False)
                    else "transparent"
                )

    def _on_card_click(self, card: ctk.CTkFrame, text: str, note_id: int = None) -> None:
        """Обработка клика по карточке (вызывается при нажатии мыши)."""
        self._select_card(card, text, note_id)

    def _select_card(self, selected_card: ctk.CTkFrame, text: str, note_id: int = None) -> None:
        """Выделить карточку и сохранить текст сообщения.

        В один момент времени выделена ТОЛЬКО ОДНА карточка.
        """
        if selected_card is None:
            return

        # 1. Сбросить выделение со ВСЕХ карточек
        for card in self.all_cards:
            if card is not None:
                try:
                    if card.winfo_exists():
                        card.configure(
                            fg_color="#E8F5E9"
                            if getattr(card, "note_processed", False)
                            else "transparent"
                        )
                        card.configure(border_width=0)
                        card.configure(border_color="#d0d0d0")
                except tk.TclError:
                    continue

        # 2. Выделить выбранную карточку
        try:
            if selected_card.winfo_exists():
                selected_card.configure(fg_color="#e8f0fe")
                selected_card.configure(border_width=2)
                selected_card.configure(border_color="#1f538d")
                self.selected_card = selected_card
                self.selected_max_text = text  # Сохраняем текст выбранного сообщения
                self.selected_note_id = note_id  # Сохраняем ID заметки
        except tk.TclError:
            pass

    def _get_default_card_color(self) -> str:
        """Возвращает default цвет карточки (зависит от темы)."""
        return "#f8f8f8" if ctk.get_appearance_mode() == "Light" else "#2b2b2b"

    def _open_add_event_from_selected(self) -> None:
        """Открыть диалог добавления события из выбранной карточки."""
        if self.selected_card is None:
            messagebox.showinfo(
                "Выберите сообщение",
                "Кликните на карточку чтобы выбрать её, затем нажмите «В события».",
                parent=self.main_app.root,
            )
            return

        # Используем сохранённый текст выбранной карточки
        text = getattr(self, "selected_max_text", "")

        initial = {
            "title": "",  # Поле название будет пустым
            "description": text,  # Текст из карточки
            "datetime": datetime.now().isoformat(timespec="minutes"),  # Текущие дата и время
        }

        # Импортируем здесь чтобы не было circular import
        from ui.events_tab import EventDialog

        def on_save(data: dict) -> bool:
            self.main_app.add_event(data)
            return True

        EventDialog(self.main_app.root, on_save=on_save, initial=initial)

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
