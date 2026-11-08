"""Вкладка заказов с таблицей ttk.Treeview."""

import sqlite3
import tkinter.ttk as ttk
from datetime import date

import customtkinter as ctk
from tkinter import messagebox

from config import APP_FONT, BG_MAIN, BG_PANEL, FG_TEXT
from database import (
    ORDER_STATUSES,
    delete_order,
    get_all_orders,
    get_note_text_by_order_id,
    update_order_status,
)
from ui.settings_dialog import SettingsDialog


ORDER_STATUS_TAGS = {
    "Новый": ("_status_new", "#FFFFFF"),
    "В печати": ("_status_printing", "#FFFACD"),
    "Готов": ("_status_ready", "#E0FFE0"),
    "Выдан": ("_status_issued", "#E0E0E0"),
    "Отменен": ("_status_cancelled", "#FFE0E0"),
}
ORDER_STATUS_LABELS = {
    "Новый": "🟦 Новый",
    "В печати": "🟨 В печати",
    "Готов": "🟩 Готов",
    "Выдан": "🟥 Выдан",
    "Отменен": "⬛ Отменен",
}


class OrdersTab(ctk.CTkFrame):
    """Вкладка для просмотра и управления заказами."""

    def __init__(self, parent, main_app):
        super().__init__(parent, fg_color=BG_MAIN)
        self.main_app = main_app
        self.orders: list[tuple] = []  # Все строки orders из БД
        self.refresh_job = None
        self._build_ui()
        # Загружаем данные при создании вкладки
        self.refresh()
        # Запускаем автообновление каждые 30 секунд
        self.auto_refresh()

    # ------------------------------------------------------------------ #
    # UI
    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        # Настраиваем стиль для таблицы: крупный шрифт и увеличенные строки
        style = ttk.Style()
        style.theme_use("default")
        style.configure(
            "Orders.Treeview",
            font=("Segoe UI", 18),
            rowheight=50,
            background=BG_PANEL,
        )
        style.configure(
            "Orders.Treeview.Heading",
            font=("Segoe UI", 18, "bold"),
            background="#e0e0e0",
        )
        style.map(
            "Orders.Treeview",
            background=[("selected", "#a8d5ff")],
            foreground=[("selected", "#000000")],
        )

        # --- Панель кнопок ---
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=6, pady=(6, 2))

        ctk.CTkButton(
            btn_frame,
            text="💲 Цены",
            command=self._open_settings,
            font=APP_FONT,
            width=140,
            height=40,
            fg_color=("#f39c12", "#d68910"),
            hover_color=("#d68910", "#bf780e"),
        ).pack(side="left", padx=4)

        ctk.CTkButton(
            btn_frame,
            text="🔄 Обновить",
            command=self.refresh,
            font=APP_FONT,
            width=140,
            height=40,
        ).pack(side="left", padx=4)

        ctk.CTkButton(
            btn_frame,
            text="🗑 Удалить заказ",
            command=self._delete_selected,
            font=APP_FONT,
            width=150,
            height=40,
            fg_color=("#e74c3c", "#c0392b"),
            hover_color=("#c0392b", "#a93226"),
        ).pack(side="left", padx=4)

        ctk.CTkButton(
            btn_frame,
            text="🔄 Сменить статус",
            command=self._change_selected_status,
            font=APP_FONT,
            width=170,
            height=40,
        ).pack(side="left", padx=4)

        # --- Таблица ---
        table_frame = ctk.CTkFrame(self, fg_color="transparent")
        table_frame.pack(fill="both", expand=True, padx=6, pady=4)

        # Scrollbars
        y_scroll = ttk.Scrollbar(table_frame, orient="vertical")
        y_scroll.pack(side="right", fill="y")
        x_scroll = ttk.Scrollbar(table_frame, orient="horizontal")
        x_scroll.pack(side="bottom", fill="x")

        self.tree = ttk.Treeview(
            table_frame,
            columns=("id", "customer", "deadline", "weight", "time", "price", "status"),
            show="headings",
            style="Orders.Treeview",
            yscrollcommand=y_scroll.set,
            xscrollcommand=x_scroll.set,
            selectmode="extended",
        )

        # Колонки: (название, ширина, anchor, скрытая?)
        self._columns: list[dict] = [
            {"name": "id",         "text": "#",    "width": 50,  "anchor": "c", "hidden": True},
            {"name": "customer",   "text": "Заказчик",   "width": 200, "anchor": "w", "hidden": False},
            {"name": "deadline",   "text": "Срок",   "width": 110, "anchor": "c", "hidden": False},
            {"name": "weight",     "text": "Вес (г)",  "width": 110, "anchor": "c", "hidden": False},
            {"name": "time",       "text": "Время (ч)", "width": 110, "anchor": "c", "hidden": False},
            {"name": "price",      "text": "Цена (руб)", "width": 120, "anchor": "e", "hidden": False},
            {"name": "status",     "text": "Статус", "width": 170, "anchor": "c", "hidden": False},
        ]

        for col in self._columns:
            self.tree.heading(col["name"], text=col["text"])
            self.tree.column(col["name"], width=col["width"], anchor=col["anchor"])

        for tag, background in ORDER_STATUS_TAGS.values():
            self.tree.tag_configure(tag, background=background, foreground=FG_TEXT)
        # Просроченные заказы — красным текстом
        self.tree.tag_configure("_overdue", foreground="#e74c3c")

        self.tree.pack(fill="both", expand=True)

        # --- Текстовое поле с описанием заказа ---
        details_header = ctk.CTkLabel(
            table_frame,
            text="Описание заказа:",
            font=("Segoe UI", 14, "bold"),
        )
        details_header.pack(fill="x", padx=6, pady=(6, 2))

        self.order_details_text = ctk.CTkTextbox(
            table_frame,
            height=120,
            wrap="word",
            font=("Segoe UI", 15),
        )
        self.order_details_text.pack(
            fill="x", padx=6, pady=(0, 4)
        )
        self.order_details_text.configure(state="disabled")

        # Привязка двойного клика — показать детали
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", self._on_double_click)

        y_scroll.config(command=self.tree.yview)
        x_scroll.config(command=self.tree.xview)

    # --------------------------------------------------------------- #
    # Обновление данных
    # --------------------------------------------------------------- #
    def refresh(self) -> None:
        """Загрузить все заказы из БД и отобразить в таблице."""
        selected_ids = {
            str(self.tree.item(item, "values")[0])
            for item in self.tree.selection()
            if self.tree.item(item, "values")
        }
        self.orders = get_all_orders()
        self.tree.delete(*self.tree.get_children())
        inserted_ids = []

        now_date = date.today()

        for row in self.orders:
            # row: (id, customer, deadline, file_path, weight, time, material, extra,
            #       price, note_id, filament_id, printer_id, status)
            status = row[12] or "Новый"
            status_label = ORDER_STATUS_LABELS.get(status, status)
            status_tag = ORDER_STATUS_TAGS.get(status, ORDER_STATUS_TAGS["Новый"])[0]
            tags = [status_tag]
            try:
                if date.fromisoformat(row[2]) < now_date:
                    tags.append("_overdue")
            except (ValueError, TypeError):
                pass

            order_id = str(row[0])
            self.tree.insert(
                "",
                "end",
                iid=order_id,
                values=(
                    row[0],                    # id (скрытая колонка)
                    row[1] or "",              # customer
                    row[2] or "",              # deadline
                    f"{row[4]:.0f}",           # weight
                    f"{row[5]:.1f}",           # time
                    f"{row[8]:.2f}",           # price
                    status_label,              # status
                ),
                tags=tuple(tags),
            )
            inserted_ids.append(order_id)

        restored_selection = [
            order_id for order_id in inserted_ids if order_id in selected_ids
        ]
        if restored_selection:
            self.tree.selection_set(restored_selection)
        elif selected_ids and inserted_ids:
            self.tree.selection_set(inserted_ids[0])
        self.tree.yview_moveto(0)

    # --------------------------------------------------------------- #
    # Действия
    # --------------------------------------------------------------- #
    def _open_settings(self) -> None:
        """Открыть диалог настроек цен."""
        SettingsDialog(self.main_app.root)

    def _change_selected_status(self) -> None:
        """Открыть диалог и сохранить новый статус выбранного заказа."""
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo(
                "Заказы",
                "Выберите заказ для смены статуса.",
                parent=self.main_app.root,
            )
            return

        order_id = int(selected[0])
        values = self.tree.item(selected[0], "values")
        displayed_status = values[6] if len(values) > 6 else ORDER_STATUSES[0]
        current_status = next(
            (
                status
                for status, label in ORDER_STATUS_LABELS.items()
                if label == displayed_status
            ),
            displayed_status,
        )

        dialog = ctk.CTkToplevel(self.main_app.root)
        dialog.title(f"Статус заказа #{order_id}")
        dialog.geometry("320x170")
        dialog.resizable(False, False)
        dialog.transient(self.main_app.root)
        dialog.grab_set()

        ctk.CTkLabel(dialog, text="Выберите новый статус:", font=APP_FONT).pack(
            padx=20, pady=(20, 8)
        )
        status_menu = ctk.CTkOptionMenu(dialog, values=list(ORDER_STATUSES), font=APP_FONT)
        status_menu.pack(fill="x", padx=20, pady=4)
        status_menu.set(
            current_status if current_status in ORDER_STATUSES else ORDER_STATUSES[0]
        )

        def save_status() -> None:
            try:
                update_order_status(order_id, status_menu.get())
            except (sqlite3.Error, ValueError) as error:
                messagebox.showerror(
                    "Ошибка",
                    f"Не удалось изменить статус заказа: {error}",
                    parent=dialog,
                )
                return

            dialog.destroy()
            self.refresh()

        ctk.CTkButton(
            dialog,
            text="Сохранить",
            command=save_status,
            font=APP_FONT,
        ).pack(pady=(12, 16))

    def _delete_selected(self) -> None:
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("Заказы", "Выберите заказ для удаления.", parent=self.main_app.root)
            return
        if not messagebox.askyesno(
            "Удаление заказа",
            "Удалить выбранный заказ?\nЭто действие нельзя отменить.",
            parent=self.main_app.root,
        ):
            return
        item = self.tree.item(selected[0])
        order_id = item["values"][0]
        try:
            delete_order(order_id)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось удалить заказ: {e}", parent=self.main_app.root)
            return
        self.tree.delete(selected)
        # Обновить данные
        self.refresh()

    def _on_select(self, _event=None) -> None:
        """При выборе заказа — показать текст заметки в текстовом поле."""
        selected = self.tree.selection()
        if not selected:
            return

        item = self.tree.item(selected[0])
        values = item["values"]
        if not values:
            return

        order_id = values[0]
        note_text = get_note_text_by_order_id(order_id)

        # Очищаем и вставляем текст
        self.order_details_text.configure(state="normal")
        self.order_details_text.delete("1.0", "end")
        if note_text:
            self.order_details_text.insert("1.0", note_text)
        else:
            self.order_details_text.insert(
                "1.0", "Нет описания из MAX для этого заказа."
            )
        self.order_details_text.configure(state="disabled")

    def _on_double_click(self, event) -> None:
        """Двойной клик — показать полное описание заказа в диалоге."""
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        selected = self.tree.selection()
        if not selected:
            return
        item = self.tree.item(selected[0])
        values = item["values"]
        if not values:
            return
        self._show_order_details(values)

    def _show_order_details(self, values: tuple) -> None:
        order_id, customer, deadline, weight, time, price, status = values

        dialog = ctk.CTkToplevel(self.main_app.root)
        dialog.title(f"Заказ #{order_id}")
        dialog.geometry("400x350")
        dialog.attributes("-topmost", True)
        dialog.transient(self.main_app.root)
        dialog.resizable(False, False)

        pad = {"padx": 20, "pady": 8}

        info_lines = [
            f"ID:            {order_id}",
            f"Заказчик:      {customer}",
            f"Срок:          {deadline}",
            f"Вес:           {weight} г",
            f"Время печати:  {time} ч",
            f"Цена:          {price} руб.",
            f"Статус:        {status}",
        ]

        ctk.CTkLabel(
            dialog,
            text="\n".join(info_lines),
            font=("Segoe UI", 15),
            justify="left",
        ).pack(fill="x", **pad)

        ctk.CTkButton(
            dialog,
            text="Закрыть",
            font=APP_FONT,
            command=dialog.destroy,
        ).pack(pady=(0, 15))

    # --------------------------------------------------------------- #
    # Автообновление
    # --------------------------------------------------------------- #
    def auto_refresh(self) -> None:
        """Периодически обновлять данные из БД."""
        # Сначала отменяем старый таймер, если он есть
        if self.refresh_job is not None:
            self.main_app.root.after_cancel(self.refresh_job)
        # Планируем следующее обновление через 30 секунд
        self.refresh_job = self.main_app.root.after(
            30000, self._auto_refresh_callback
        )

    def _auto_refresh_callback(self) -> None:
        """Вызывается таймером для обновления данных."""
        self.refresh_job = None
        self.refresh()
        # Запускаем следующий цикл
        self.auto_refresh()

    def stop_auto_refresh(self) -> None:
        """Останавливает автообновление (вызывать при закрытии приложения)."""
        if self.refresh_job is not None:
            self.main_app.root.after_cancel(self.refresh_job)
            self.refresh_job = None
