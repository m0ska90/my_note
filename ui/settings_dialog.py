"""Диалог настройки цен на пластик по принтерам."""

import logging
import math

import customtkinter as ctk
from tkinter import messagebox

from config import APP_FONT, BG_MAIN, BG_PANEL
from database import (
    SETTING_DEFAULTS,
    get_all_printers,
    get_filaments_by_printer,
    get_setting,
    set_setting,
    update_filament_price,
)

logger = logging.getLogger(__name__)


class SettingsDialog(ctk.CTkToplevel):
    """Диалог управления ценами на пластик и коэффициентами расчета."""

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Настройки цен на пластик")

        # --- Геометрия окна -------------------------------------------
        screen_h = self.winfo_screenheight()
        max_h = max(400, screen_h - 100)  # минус панель задач и отступы
        self.geometry(f"650x{max_h}")
        self.configure(fg_color=BG_MAIN)
        self.transient(parent)
        self.grab_set()
        self.lift()

        self._entry_widgets: list[tuple[str, ctk.CTkEntry, int]] = []
        self._setting_entries: dict[str, ctk.CTkEntry] = {}

        # --- Главный вертикальный фрейм (скролл + кнопки) ---------------
        main_frame = ctk.CTkFrame(self, fg_color=BG_MAIN)
        main_frame.pack(fill="both", expand=True)

        # --- Скроллируемая область со всем контентом -------------------
        scroll = ctk.CTkScrollableFrame(main_frame, fg_color=BG_MAIN)
        scroll.pack(side="top", fill="both", expand=True, padx=8, pady=8)

        self._printer_ids: dict[str, int] = {}
        pad = {"padx": 16, "pady": 6}

        # --- Загрузка принтеров ---------------------------------------
        printers = get_all_printers()
        print(f"[DB] get_all_printers(): {len(printers)} записей — {printers}", flush=True)
        logger.info(
            "SettingsDialog: получено %d принтеров из БД — %s",
            len(printers), printers,
        )
        self._printer_ids = {
            f"{printer_id}: {name}": printer_id
            for printer_id, name in printers
        }

        # --- Выбор принтера -------------------------------------------
        ctk.CTkLabel(
            scroll,
            text="Выберите принтер:",
            font=("Segoe UI", 16, "bold"),
        ).pack(anchor="w", **pad)

        printer_values = list(self._printer_ids)
        logger.info("SettingsDialog: ключи для ComboBox — %s", printer_values)
        self.printer_combo = ctk.CTkComboBox(
            scroll,
            values=printer_values or ["Нет принтеров"],
            font=APP_FONT,
            state="readonly" if printer_values else "disabled",
            height=40,
            command=self._on_printer_select,
        )
        self.printer_combo.pack(fill="x", padx=16, pady=(0, 4))

        # --- Коэффициенты расчета --------------------------------------
        settings_frame = ctk.CTkFrame(scroll, fg_color=BG_PANEL, corner_radius=8)
        settings_frame.pack(fill="x", padx=16, pady=(8, 0))

        ctk.CTkLabel(
            settings_frame,
            text="Коэффициенты расчета",
            font=("Segoe UI", 16, "bold"),
        ).pack(anchor="w", padx=10, pady=(8, 4))

        ctk.CTkLabel(
            settings_frame,
            text=(
                "Формула: (Вес × Цена_пластика × Коэф_брака) + "
                "(Время × Работа) + (Время × Амортизация) + "
                "(Время × Электричество) + Доп.услуги"
            ),
            font=("Segoe UI", 13),
            wraplength=500,
            justify="left",
            anchor="w",
        ).pack(fill="x", padx=10, pady=(0, 6))

        setting_labels = {
            "labor_rate": "Ставка за час работы (руб/ч)",
            "depreciation_rate": "Амортизация принтера (руб/ч)",
            "electricity_rate": "Электричество (руб/ч)",
            "waste_factor": "Коэффициент брака",
        }
        self._setting_labels = setting_labels
        for key, label in setting_labels.items():
            row = ctk.CTkFrame(settings_frame, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=3)

            ctk.CTkLabel(
                row,
                text=label,
                font=APP_FONT,
                anchor="w",
            ).pack(side="left", fill="x", expand=True, padx=(0, 8))

            entry = ctk.CTkEntry(row, width=140, font=("Segoe UI", 16))
            entry.pack(side="right")
            entry.insert(0, str(get_setting(key, SETTING_DEFAULTS[key])))
            self._setting_entries[key] = entry

        # --- Пояснительная записка -------------------------------------
        ctk.CTkLabel(
            settings_frame,
            text=(
                "Почему такие цифры по умолчанию?\n"
                "• Работа (250 руб/ч): Средняя рыночная ставка для домашней "
                "мастерской. Включает подготовку, нарезку и наблюдение за печатью.\n"
                "• Амортизация (15 руб/ч): Компенсация износа принтера, "
                "сопел и замены ремней. Рассчитана на ~15 000 часов работы.\n"
                "• Электричество (1 руб/ч): Принтер потребляет ~150 Вт. "
                "При тарифе ~6 руб/кВт·ч это меньше 1 рубля в час.\n"
                "• Брак (1.15): Закладывает 15% на возможные неудачи "
                "(отрыв от стола, поддержки, дефекты)."
            ),
            font=("Segoe UI", 12),
            wraplength=500,
            justify="left",
            anchor="w",
        ).pack(fill="x", padx=10, pady=(8, 10))

        # --- Пластик (динамически обновляется при смене принтера) -------
        self.filaments_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        self.filaments_frame.pack(fill="x", padx=16, pady=(8, 0))

        # --- Кнопки (вне скролла, прижаты к низу окна) -----------------
        buttons_frame = ctk.CTkFrame(main_frame, fg_color=BG_MAIN)
        buttons_frame.pack(fill="x", side="bottom", padx=8, pady=8)

        ctk.CTkButton(
            buttons_frame,
            text="Сохранить настройки",
            command=self.save_settings,
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

        # --- Автовыбор первого принтера --------------------------------
        if printer_values:
            logger.info("SettingsDialog: автовыбор первого принтера — '%s'", printer_values[0])
            self.printer_combo.set(printer_values[0])
            self._on_printer_select(printer_values[0])
        else:
            logger.warning("SettingsDialog: список принтеров пуст — ComboBox отключён")

    def _on_printer_select(self, printer_name: str) -> None:
        logger.info("SettingsDialog: выбран принтер — '%s'", printer_name)
        for widget in self.filaments_frame.winfo_children():
            widget.destroy()
        self._entry_widgets = []

        printer_id = self._printer_ids.get(printer_name)
        logger.info("SettingsDialog: printer_id = %r", printer_id)
        if printer_id is None:
            logger.warning("SettingsDialog: printer_id не найден для '%s'", printer_name)
            return

        filaments = get_filaments_by_printer(printer_id)
        logger.info("SettingsDialog: получено %d пластиков для printer_id=%d", len(filaments), printer_id)
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

    def save_settings(self) -> None:
        setting_values: dict[str, float] = {}
        for key, entry in self._setting_entries.items():
            value = entry.get().strip().replace(",", ".")
            try:
                setting_value = float(value)
                if (
                    not math.isfinite(setting_value)
                    or setting_value < 0
                    or (key == "waste_factor" and setting_value == 0)
                ):
                    raise ValueError("Недопустимое значение")
            except ValueError:
                messagebox.showwarning(
                    "Некорректное значение",
                    f"Поле '{self._setting_labels[key]}' должно содержать "
                    "неотрицательное число (коэффициент брака — больше нуля).",
                    parent=self,
                )
                return
            setting_values[key] = setting_value

        saved = 0
        skipped = 0

        for material, entry, filament_id in self._entry_widgets:
            value = entry.get().strip().replace(",", ".")
            if not value:
                skipped += 1
                continue

            try:
                price = float(value)
                if not math.isfinite(price) or price < 0:
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

        for key, value in setting_values.items():
            set_setting(key, value)

        message = (
            f"Сохранено настроек: {len(setting_values)}"
            f"\nСохранено цен на пластик: {saved}"
        )
        if skipped:
            message += f"\nПропущено (пустые): {skipped}"
        messagebox.showinfo("Готово", message, parent=self)
        self.destroy()
