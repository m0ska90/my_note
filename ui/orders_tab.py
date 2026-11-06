"""Вкладка заказов с таблицей ttk.Treeview."""

import tkinter.ttk as ttk

import customtkinter as ctk
from tkinter import messagebox

from config import APP_FONT, BG_MAIN, BG_PANEL, COLOR_DONE, FG_TEXT
from database import delete_order, get_all_orders


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
            columns=("id", "customer", "deadline", "weight", "time", "price"),
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
        ]

        for col in self._columns:
            self.tree.heading(col["name"], text=col["text"])
            self.tree.column(col["name"], width=col["width"], anchor=col["anchor"])

        # Подсветка строк — цвет фона по умолчанию
        self.tree.tag_configure("_row", background=BG_PANEL, foreground=FG_TEXT)
        # Просроченные заказы — красным текстом
        self.tree.tag_configure("_overdue", foreground="#e74c3c", background=BG_PANEL)

        self.tree.pack(fill="both", expand=True)

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
        self.orders = get_all_orders()
        self.tree.delete(*self.tree.get_children())

        now_date = None
        try:
            from datetime import date
            now_date = date.today()
        except Exception:
            pass

        for row in self.orders:
            # row: (id, customer, deadline, file_path, weight, time, material, extra, price)
            tag = "_overdue" if now_date else "_row"
            if now_date:
                try:
                    dl = __import__("datetime").date.fromisoformat(row[2])
                    if dl < now_date:
                        tag = "_overdue"
                    else:
                        tag = "_row"
                except (ValueError, TypeError):
                    tag = "_row"

            self.tree.insert(
                "",
                "end",
                values=(
                    row[0],                    # id (скрытая колонка)
                    row[1] or "",              # customer
                    row[2] or "",              # deadline
                    f"{row[4]:.0f}",           # weight
                    f"{row[5]:.1f}",           # time
                    f"{row[8]:.2f}",           # price
                ),
                tags=(tag,),
            )

    # --------------------------------------------------------------- #
    # Действия
    # --------------------------------------------------------------- #
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
        pass

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
        order_id, customer, deadline, weight, time, price = values

        dialog = ctk.CTkToplevel(self.main_app.root)
        dialog.title(f"Заказ #{order_id}")
        dialog.geometry("400x320")
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

