import os
import re
import sqlite3
from datetime import datetime
from tkinter import filedialog, messagebox

import customtkinter as ctk
from tkinter import messagebox as tk_messagebox

from config import APP_FONT, BG_MAIN
from database import add_order
from pricing import calculate_price


def parse_gcode(file_path: str) -> dict | None:
    """Парсит G-code файл и возвращает вес и время.

    Ищет строки:
      ; filament used [g]: 123.4
      ; total estimated time: 2h 15m (или просто минуты)

    Returns:
        dict с ключами 'weight_grams' и 'time_hours' или None.
    """
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except (OSError, IOError):
        return None

    weight: float | None = None
    time_minutes: float | None = None

    for line in lines:
        line_lower = line.strip().lower()

        # filament used [g]: 123.4
        if "filament used [g]" in line_lower:
            match = re.search(r"[\:\=\s]+([\d\.]+)", line_lower)
            if match:
                try:
                    weight = float(match.group(1))
                except ValueError:
                    pass

        # total estimated time
        # Форматы:
        #   ; total estimated time: 2h 15m
        #   ; total estimated time: 135 min
        #   ; total estimated time: 02:15:00
        if "total estimated time" in line_lower:
            # Часы и минуты: 2h 15m
            hm = re.search(r"(\d+)\s*h(?:ours?|ч)?", line_lower)
            total_minutes = 0
            if hm:
                hours = float(hm.group(1))
                total_minutes = hours * 60
                # Ищем минуты после часов — начинаем поиск с конца строки часа
                after_h = line_lower[hm.end():]
                min_match = re.search(r"(\d+)\s*m(?:in(?:utes?|ут)?)?", after_h)
                if min_match:
                    total_minutes += float(min_match.group(1))

            if total_minutes > 0:
                time_minutes = total_minutes
                continue

            # Формат ЧЧ:ММ:СС или ММ:СС
            time_match = re.search(r"(\d+):(\d+)(?::(\d+))?", line_lower)
            if time_match:
                h = int(time_match.group(1))
                m = int(time_match.group(2))
                s = int(time_match.group(3)) if time_match.group(3) else 0
                time_minutes = h * 60 + m + s / 60
                continue

            # Просто число минут: 135
            num_match = re.search(r"[\:\=\s]+([\d\.]+)", line_lower)
            if num_match:
                try:
                    time_minutes = float(num_match.group(1))
                except ValueError:
                    pass

    if weight is not None and time_minutes is not None:
        return {
            "weight_grams": round(weight, 1),
            "time_hours": round(time_minutes / 60, 2),
        }

    return None


class OrderDialog(ctk.CTkToplevel):
    def __init__(self, parent, file_path: str = "", note_text: str = "", note_id: int = None):
        super().__init__(parent)
        self.file_path = file_path
        self.note_text = note_text
        self.note_id = note_id
        self.main_app = parent  # Сохраняем ссылку на главное окно
        self.title("Оформление 3D-заказа")
        self.geometry("480x700")
        self.configure(fg_color=BG_MAIN)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.lift()

        pad = {"padx": 12, "pady": 4}

        # --- Блок: Текст заметки из MAX (только для чтения) ---
        if note_text:
            note_frame = ctk.CTkFrame(self, fg_color="#f0f0f0")
            note_frame.pack(fill="both", expand=True, padx=12, pady=(4, 0))

            ctk.CTkLabel(
                note_frame,
                text="📝 Текст заказа из MAX:",
                font=("Segoe UI", 14, "bold"),
                anchor="w",
            ).pack(fill="x", padx=8, pady=(6, 2))

            self.note_display = ctk.CTkTextbox(
                note_frame,
                height=100,
                wrap="word",
                font=("Segoe UI", 14),
            )
            self.note_display.pack(fill="both", expand=True, padx=8, pady=(0, 6))
            # Сначала включаем режим редактирования, вставляем текст, затем блокируем
            self.note_display.configure(state="normal")
            self.note_display.insert("1.0", note_text)
            self.note_display.configure(state="disabled")
        ctk.CTkLabel(self, text="Имя заказчика:", font=APP_FONT).pack(
            anchor="w", **pad
        )
        self.customer_entry = ctk.CTkEntry(self, font=APP_FONT)
        self.customer_entry.pack(fill="x", padx=12)

        ctk.CTkLabel(
            self, text="Срок исполнения (ДД.ММ.ГГГГ):", font=APP_FONT
        ).pack(anchor="w", **pad)
        self.deadline_entry = ctk.CTkEntry(self, font=APP_FONT)
        self.deadline_entry.pack(fill="x", padx=12)

        # --- Группа: Вес и Время с кнопкой загрузки ---
        weight_time_frame = ctk.CTkFrame(self, fg_color="transparent")
        weight_time_frame.pack(fill="x", padx=12, pady=(4, 0))

        # Вес
        ctk.CTkLabel(weight_time_frame, text="Вес в граммах:", font=APP_FONT).pack(
            anchor="w", pady=(4, 0)
        )
        digits_validator = (self.register(self._is_digits_or_empty), "%P")
        self.weight_entry = ctk.CTkEntry(
            weight_time_frame,
            font=APP_FONT,
            validate="key",
            validatecommand=digits_validator,
        )
        self.weight_entry.pack(fill="x", pady=2)

        # Время
        ctk.CTkLabel(weight_time_frame, text="Время печати в часах:", font=APP_FONT).pack(
            anchor="w", pady=(8, 0)
        )
        self.time_entry = ctk.CTkEntry(
            weight_time_frame,
            font=APP_FONT,
            validate="key",
            validatecommand=digits_validator,
        )
        self.time_entry.pack(fill="x", pady=2)

        # Кнопка загрузки G-code
        ctk.CTkButton(
            weight_time_frame,
            text="📂 Загрузить G-code",
            command=self._load_gcode,
            font=("Segoe UI", 14),
            height=36,
        ).pack(fill="x", pady=(8, 4))

        ctk.CTkLabel(self, text="Тип пластика:", font=APP_FONT).pack(
            anchor="w", **pad
        )
        self.material_combo = ctk.CTkComboBox(
            self,
            values=["PLA", "PETG", "ABS"],
            font=APP_FONT,
            state="readonly",
        )
        self.material_combo.pack(fill="x", padx=12)
        self.material_combo.set("PLA")

        ctk.CTkLabel(self, text="Доп. услуги (руб.):", font=APP_FONT).pack(
            anchor="w", **pad
        )
        self.extra_entry = ctk.CTkEntry(self, font=APP_FONT)
        self.extra_entry.pack(fill="x", padx=12)

        ctk.CTkButton(
            self,
            text="Рассчитать и сохранить",
            command=self.save_order,
            font=APP_FONT,
        ).pack(pady=(18, 18))

        self.customer_entry.focus_set()

    def _is_digits_or_empty(self, value: str) -> bool:
        """Разрешает цифры, точку и запятую (для дробных чисел)."""
        if not value:
            return True  # пустое поле допустимо
        dot_count = value.count('.') + value.count(',')
        if dot_count > 1:
            return False  # не более одного разделителя
        return all("0" <= ch <= "9" or ch in ".," for ch in value)

    def _load_gcode(self) -> None:
        """Открывает диалог выбора G-code файла и парсит его."""
        file_path = filedialog.askopenfilename(
            title="Выберите G-code файл",
            filetypes=[
                ("G-code файлы", "*.gcode *.g *.gco"),
                ("Все файлы", "*.*"),
            ],
        )
        if not file_path:
            return

        # Запоминаем путь к файлу для сохранения в заказе
        self.file_path = file_path

        parsed = parse_gcode(file_path)
        if parsed:
            self.weight_entry.delete(0, "end")
            self.weight_entry.insert(0, str(parsed["weight_grams"]))

            self.time_entry.delete(0, "end")
            self.time_entry.insert(0, str(parsed["time_hours"]))

            messagebox.showinfo(
                "G-code загружен",
                f"Найдено:\n"
                f"Вес: {parsed['weight_grams']} г\n"
                f"Время: {parsed['time_hours']} ч",
                parent=self,
            )
        else:
            messagebox.showwarning(
                "G-code не распознан",
                "В файле не найдены строки:\n"
                "; filament used [g]: ...\n"
                "; total estimated time: ...",
                parent=self,
            )

    def save_order(self) -> None:
        customer_name = self.customer_entry.get().strip()
        if not customer_name:
            tk_messagebox.showerror("Ошибка", "Введите имя заказчика.", parent=self)
            return

        try:
            deadline_text = self.deadline_entry.get().strip()
            if not re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", deadline_text):
                raise ValueError("Дата должна быть в формате ДД.ММ.ГГГГ.")
            deadline = datetime.strptime(
                deadline_text, "%d.%m.%Y"
            ).date()
            weight_text = self.weight_entry.get().strip()
            if not weight_text:
                raise ValueError("Вес не может быть пустым.")
            weight_grams = float(weight_text)
            if weight_grams <= 0:
                raise ValueError("Вес должен быть больше 0.")

            time_text = self.time_entry.get().strip()
            if not time_text:
                raise ValueError("Время не может быть пустым.")
            time_hours = float(time_text)
            if time_hours <= 0:
                raise ValueError("Время должно быть больше 0.")

            extra_text = self.extra_entry.get().strip() or "0"
            if not re.fullmatch(r"\d+(?:[.,]\d+)?", extra_text):
                raise ValueError("Сумма доп. услуг должна быть числом.")
            extra_services = float(extra_text.replace(",", "."))
        except ValueError as error:
            tk_messagebox.showerror(
                "Ошибка",
                f"{error}",
                parent=self,
            )
            return

        total_price = calculate_price(
            weight_grams,
            time_hours,
            extra_services=extra_services,
        )
        try:
            add_order(
                customer_name=customer_name,
                deadline=deadline.isoformat(),
                file_path=self.file_path,
                weight_grams=weight_grams,
                print_time_hours=time_hours,
                material_type=self.material_combo.get(),
                extra_services=extra_services,
                total_price=total_price,
                note_id=self.note_id,
            )
        except (OSError, sqlite3.Error, ValueError) as error:
            tk_messagebox.showerror(
                "Ошибка сохранения",
                f"Не удалось сохранить заказ: {error}",
                parent=self,
            )
            return

        tk_messagebox.showinfo(
            "Заказ сохранён",
            f"Заказ заказчика '{customer_name}' успешно сохранён.\n\n"
            f"Сумма: {total_price:.2f} руб.",
            parent=self,
        )
        # Обновляем вкладку заказов в главном окне ДО закрытия
        if hasattr(self.main_app, 'refresh_orders'):
            self.main_app.refresh_orders()
        self.destroy()
