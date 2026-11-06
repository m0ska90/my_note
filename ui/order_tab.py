from datetime import datetime

import tkinter as tk

import customtkinter as ctk
from tkinter import messagebox

from config import APP_FONT, BG_MAIN, BG_PANEL, COLOR_DONE, FG_TEXT
from database import delete_order, get_all_orders


class OrderTab(ctk.CTkFrame):
    def __init__(self, parent, main_app):
        super().__init__(parent, fg_color="transparent")
        self.main_app = main_app
        self.sorted_orders = []
        self._build_ui()

    def _build_ui(self):
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(side="top", fill="x")

        actions = ctk.CTkFrame(top, fg_color="transparent")
        actions.pack(expand=True)
        for column in range(2):
            actions.grid_columnconfigure(
                column, weight=0, uniform="action_buttons"
            )

        ctk.CTkButton(
            actions,
            text="✖ Удалить",
            command=self.main_app.delete_selected_order,
            width=120,
            font=APP_FONT,
        ).grid(row=0, column=0, padx=5, pady=5, sticky="w")
        ctk.CTkButton(
            actions,
            text="🗑 Очистить",
            command=self._show_clear_confirmation,
            width=120,
            font=APP_FONT,
        ).grid(row=0, column=1, padx=5, pady=5, sticky="w")

        list_frame = ctk.CTkFrame(self, fg_color="transparent")
        list_frame.pack(fill="both", expand=True, padx=6, pady=4)

        scrollbar = tk.Scrollbar(list_frame, orient="vertical")
        scrollbar.pack(side="right", fill="y")
        self.order_list = tk.Listbox(
            list_frame,
            bg=BG_PANEL,
            fg=FG_TEXT,
            selectbackground="#bcd6f0",
            selectforeground="#000000",
            font=("Segoe UI", 20),
            yscrollcommand=scrollbar.set,
            relief="flat",
            highlightthickness=1,
            highlightbackground="#cccccc",
        )
        self.order_list.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.order_list.yview)
        self.order_list.bind("<<ListboxSelect>>", self.show_details)

        # Поле деталей заказа
        self.desc = ctk.CTkTextbox(
            self,
            height=120,
            wrap="word",
            font=("Segoe UI", 20),
        )
        self.desc.pack(fill="x", padx=6, pady=(0, 6))
        self.desc.configure(state="disabled")

    def refresh(self, orders):
        self.order_list.delete(0, tk.END)
        self.sorted_orders = orders

        for index, row in enumerate(orders):
            order_id, customer_name, deadline, file_path, weight, print_time, material, extra, total = row

            display_text = (
                f"📦 Заказ: {customer_name}  |  "
                f"Срок: {deadline}  |  "
                f"{weight:.0f}г  |  "
                f"{total:.2f} руб."
            )
            self.order_list.insert(tk.END, display_text)

            # Подсвечиваем просроченные заказы
            try:
                dl_date = datetime.strptime(deadline, "%Y-%m-%d").date()
                if dl_date < datetime.now().date():
                    self.order_list.itemconfig(index, foreground=COLOR_DONE)
            except (ValueError, TypeError):
                pass

    def show_details(self, event=None):
        if event is not None and event.widget is not self.order_list:
            return
        selection = self.order_list.curselection()
        self.desc.configure(state="normal")
        self.desc.delete("1.0", "end")
        if selection:
            order_row = self.sorted_orders[selection[0]]
            order_id, customer_name, deadline, file_path, weight, print_time, material, extra, total = order_row

            details = (
                f"👤 Заказчик: {customer_name}\n"
                f"📅 Срок: {deadline}\n"
                f"⚖️ Вес: {weight:.0f} г\n"
                f"⏱ Время печати: {print_time:.1f} ч\n"
                f"🔧 Материал: {material}\n"
                f"➕ Доп. услуги: {extra:.2f} руб.\n"
                f"💰 Итого: {total:.2f} руб."
            )
            if file_path:
                details += f"\n\n📁 Файл: {file_path}"
            self.desc.insert("1.0", details)
        self.desc.configure(state="disabled")

    def _show_clear_confirmation(self) -> None:
        """Открыть модальное окно для подтверждения очистки всех заказов."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("Очистка заказов")
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
            text="Для очистки всех заказов,\nвведите 'очистить' и нажмите Ввод",
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
                    conn = self._get_db_connection()
                    count = conn.execute("SELECT count(*) FROM orders").fetchone()[0]
                    conn.execute("DELETE FROM orders")
                    conn.commit()
                    messagebox.showinfo(
                        "Очищено",
                        f"Удалено {count} заказов.",
                        parent=dialog,
                    )
                    self.main_app.refresh_orders()
                except Exception as e:
                    messagebox.showerror(
                        "Ошибка",
                        f"Не удалось удалить заказы: {e}",
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

        entry.bind("<Return>", lambda event: on_submit())

        ctk.CTkButton(
            dialog,
            text="ОК",
            font=APP_FONT,
            command=on_submit,
        ).pack(pady=(0, 15))

    def _get_db_connection(self):
        """Вспомогательный метод для подключения к БД."""
        from database import _connect_db
        return _connect_db()
