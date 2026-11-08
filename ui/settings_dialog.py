"""Диалог настройки цен на пластик по принтерам."""

import customtkinter as ctk
from tkinter import messagebox

from config import APP_FONT, BG_MAIN, BG_PANEL
from database import get_all_printers, get_filaments_by_printer, update_filament_price


class SettingsDialog(ctk.CTkToplevel):
    """Диалог управления ценами на пластик."""

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Настройки цен на пластик")
        self.geometry("500x520")
        self.configure(fg_color=BG_MAIN)
        self.transient(parent)
        self.grab_set()
        self.lift()

        self._entry_widgets: list[tuple[str, ctk.CTkEntry, int]] = []
        printers = get_all_printers()
        self._printer_ids = {
            f"{printer_id}: {name}": printer_id
            for printer_id, name in printers
        }

        pad = {"padx": 16, "pady": 6}
        ctk.CTkLabel(
            self,
            text="Выберите принтер:",
            font=("Segoe UI", 16, "bold"),
        ).pack(anchor="w", **pad)

        printer_values = list(self._printer_ids)
        self.printer_combo = ctk.CTkComboBox(
            self,
            values=printer_values or ["Нет принтеров"],
            font=APP_FONT,
            state="readonly" if printer_values else "disabled",
            height=40,
            command=self._on_printer_select,
        )
        self.printer_combo.pack(fill="x", padx=16, pady=(0, 4))

        self.filaments_frame = ctk.CTkScrollableFrame(self)
        self.filaments_frame.pack(
            fill="both",
            expand=True,
            padx=16,
            pady=(8, 0),
        )

        buttons_frame = ctk.CTkFrame(self, fg_color="transparent")
        buttons_frame.pack(fill="x", padx=16, pady=12)

        ctk.CTkButton(
            buttons_frame,
            text="Сохранить цены",
            command=self.save_prices,
            font=("Segoe UI", 16, "bold"),
            height=44,
            fg_color=("#2ecc71", "#27ae60"),
            hover_color=("#27ae60", "#219a52"),
        ).pack(side="left", fill="x", expand=True, padx=(0, 4))

        ctk.CTkButton(
            buttons_frame,
            text="Отмена",
            command=self.destroy,
            font=APP_FONT,
            height=44,
            fg_color=("#e74c3c", "#c0392b"),
            hover_color=("#c0392b", "#a93226"),
        ).pack(side="left", fill="x", expand=True, padx=(4, 0))

        if printer_values:
            self.printer_combo.set(printer_values[0])
            self._on_printer_select(printer_values[0])

    def _on_printer_select(self, printer_name: str) -> None:
        for widget in self.filaments_frame.winfo_children():
            widget.destroy()
        self._entry_widgets = []

        printer_id = self._printer_ids.get(printer_name)
        if printer_id is None:
            return

        filaments = get_filaments_by_printer(printer_id)
        if not filaments:
            ctk.CTkLabel(
                self.filaments_frame,
                text="Для этого принтера нет записей о пластике.\n"
                "Создайте их в базе данных.",
                font=("Segoe UI", 14),
                text_color="#999999",
            ).pack(pady=30)
            return

        for filament_id, material, price in filaments:
            row = ctk.CTkFrame(
                self.filaments_frame,
                fg_color=BG_PANEL,
                corner_radius=8,
            )
            row.pack(fill="x", pady=3)

            ctk.CTkLabel(
                row,
                text=material,
                font=("Segoe UI", 16, "bold"),
                width=100,
                anchor="w",
            ).pack(side="left", padx=8, pady=8, fill="y")

            entry = ctk.CTkEntry(
                row,
                width=140,
                font=("Segoe UI", 16),
                placeholder_text="руб/г",
            )
            entry.pack(side="left", padx=8, pady=8)
            if price is not None:
                entry.insert(0, str(round(price, 2)))

            self._entry_widgets.append((material, entry, filament_id))

    def save_prices(self) -> None:
        saved = 0
        skipped = 0

        for material, entry, filament_id in self._entry_widgets:
            value = entry.get().strip().replace(",", ".")
            if not value:
                skipped += 1
                continue

            try:
                price = float(value)
                if price < 0:
                    raise ValueError("Отрицательное значение")
            except ValueError:
                messagebox.showwarning(
                    "Некорректное значение",
                    f"Поле '{material}' содержит нечисловое значение.\n"
                    "Оно будет пропущено.",
                    parent=self,
                )
                continue

            update_filament_price(filament_id, price)
            saved += 1

        message = f"Сохранено: {saved}"
        if skipped:
            message += f"\nПропущено (пустые): {skipped}"
        messagebox.showinfo("Готово", message, parent=self)
        self.destroy()
