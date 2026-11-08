import os
import re
import sqlite3
from datetime import datetime
from tkinter import filedialog, messagebox

import customtkinter as ctk
from tkinter import messagebox as tk_messagebox

from config import APP_FONT, BG_MAIN
from database import add_order, get_all_printers, get_filaments_by_printer, get_filament_by_type
from pricing import calculate_price


def parse_gcode(file_path: str) -> dict | None:
    """Парсит G-code файл и возвращает вес и время.

    Поддерживаемые форматы:
    
    Вес:
      ; filament used [g]: 123.4          (PrusaSlicer, Bambu Studio)
      ; filament used [g] = 150.33        (Elegoo Slicer)
      ; Filament used: 0.4m               (Cura - метры, нужно перевести)
    
    Время:
      ; total estimated time: 2h 15m      (PrusaSlicer, Bambu Studio)
      ; estimated printing time = 7h 29m 45s  (Elegoo Slicer)
      ; Print time: 7:30                  (Cura)

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

        # ========================================================
        # РАСЧЁТ ВЕСА
        # ========================================================

        # 1) filament used [g] = 150.33  (Elegoo Slicer)
        # 2) filament used [g]: 123.4      (PrusaSlicer)
        if "filament used [g]" in line_lower:
            # Ищем число после = или :
            match = re.search(r"[\=\:\s]+([\d\.]+)", line_lower)
            if match:
                try:
                    weight = float(match.group(1))
                except ValueError:
                    pass

        # 3) filament used: 0.4m           (Cura - в метрах!)
        # 4) Filament: 1.23 m              (Elegoo 3D Builder)
        if weight is None and ("filament used:" in line_lower or "filament:" in line_lower):
            if "[g]" not in line_lower:  # не вес в граммах
                # Ищем число и единицы
                match = re.search(r"([\d\.]+)\s*([mMgGkK])", line_lower)
                if match:
                    try:
                        value = float(match.group(1))
                        unit = match.group(2).lower()
                        if unit == "m":
                            # 1m PLA ~ 5g (при 1.75mm диаметре, плотность 1.24)
                            # Приблизительно: 1m ≈ 5g
                            weight = round(value * 5.0, 1)
                        elif unit == "g":
                            weight = value
                    except ValueError:
                        pass

        # ========================================================
        # РАСЧЁТ ВРЕМЕНИ
        # ========================================================

        # 1) estimated printing time (normal mode) = 7h 29m 45s  (Elegoo Slicer)
        if "estimated printing time" in line_lower and "first layer" not in line_lower:
            total_minutes = 0

            # Часы: 7h
            h_match = re.search(r"(\d+)\s*h(?:ours?|ч)?", line_lower)
            if h_match:
                total_minutes += float(h_match.group(1)) * 60

            # Минуты: 29m (но не в секундах)
            m_match = re.search(r"(\d+)\s*m(?!in\s*s|s)", line_lower)
            if m_match:
                total_minutes += float(m_match.group(1))

            # Секунды: 45s
            s_match = re.search(r"(\d+)\s*s(econ?|)?\b", line_lower)
            if s_match:
                total_minutes += float(s_match.group(1)) / 60

            if total_minutes > 0:
                time_minutes = total_minutes
                continue

        # 2) total estimated time: 2h 15m  (PrusaSlicer, Bambu Studio)
        if "total estimated time" in line_lower:
            total_minutes = 0

            # Часы и минуты: 2h 15m
            hm = re.search(r"(\d+)\s*h(?:ours?|ч)?", line_lower)
            if hm:
                hours = float(hm.group(1))
                total_minutes = hours * 60
                # Ищем минуты после часов
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

        # 3) Print time: 7:30  (Cura)
        if "print time:" in line_lower or ";print time:" in line_lower:
            time_match = re.search(r":\s*(\d+):(\d+)(?::(\d+))?", line_lower)
            if time_match:
                h = int(time_match.group(1))
                m = int(time_match.group(2))
                time_minutes = h * 60 + m

    if weight is not None and time_minutes is not None:
        return {
            "weight_grams": round(weight, 1),
            "time_hours": round(time_minutes / 60, 2),
        }

    return None


class OrderDialog(ctk.CTkToplevel):
    def __init__(self, parent, file_path: str = "", note_text: str = "", note_id: int = None, printer_id: int = None):
        super().__init__(parent)
        self.file_path = file_path
        self.note_text = note_text
        self.note_id = note_id
        self.printer_id = printer_id
        self.filament_id = None
        self.main_app = parent  # Сохраняем ссылку на главное окно
        self.title("Оформление 3D-заказа")
        window_width = min(520, self.winfo_screenwidth() - 40)
        window_height = min(700, self.winfo_screenheight() - 60)
        window_width = max(window_width, 1)
        window_height = max(window_height, 1)
        x = (self.winfo_screenwidth() - window_width) // 2
        y = (self.winfo_screenheight() - window_height) // 2
        self.geometry(f"{window_width}x{window_height}+{x}+{y}")
        self.configure(fg_color=BG_MAIN)
        self.resizable(False, False)
        self.transient(parent)
        self.attributes("-topmost", True)
        self.grab_set()
        self.lift()

        content_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        content_frame.pack(fill="both", expand=True, padx=4, pady=(4, 0))

        pad = {"padx": 12, "pady": 4}

        # --- Блок: Текст заметки из MAX (только для чтения) ---
        if note_text:
            note_frame = ctk.CTkFrame(content_frame, fg_color="#f0f0f0")
            note_frame.pack(fill="x", padx=12, pady=(4, 0))

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
        ctk.CTkLabel(content_frame, text="Имя заказчика:", font=APP_FONT).pack(
            anchor="w", **pad
        )
        self.customer_entry = ctk.CTkEntry(content_frame, font=APP_FONT)
        self.customer_entry.pack(fill="x", padx=12)

        ctk.CTkLabel(
            content_frame, text="Срок исполнения (ДД.ММ.ГГГГ):", font=APP_FONT
        ).pack(anchor="w", **pad)
        self.deadline_entry = ctk.CTkEntry(content_frame, font=APP_FONT)
        self.deadline_entry.pack(fill="x", padx=12)
        # Вставляем текущую дату по умолчанию
        self.deadline_entry.insert(0, datetime.now().strftime("%d.%m.%Y"))

        # --- Выбор принтера ---
        ctk.CTkLabel(content_frame, text="Принтер:", font=APP_FONT).pack(anchor="w", **pad)
        self.printer_combo = ctk.CTkComboBox(
            content_frame,
            values=[],
            font=APP_FONT,
            state="readonly",
            command=self._on_printer_change,
        )
        self.printer_combo.pack(fill="x", padx=12)

        # --- Выбор пластика ---
        ctk.CTkLabel(content_frame, text="Пластик:", font=APP_FONT).pack(anchor="w", **pad)
        self.filament_combo = ctk.CTkComboBox(
            content_frame,
            values=[],
            font=APP_FONT,
            state="readonly",
            command=self._on_filament_change,
        )
        self.filament_combo.pack(fill="x", padx=12)
        self._load_printers()

        # --- Группа: Вес и Время с кнопкой загрузки ---
        weight_time_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
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

        ctk.CTkLabel(content_frame, text="Доп. услуги (руб.):", font=APP_FONT).pack(
            anchor="w", **pad
        )
        self.extra_entry = ctk.CTkEntry(content_frame, font=APP_FONT)
        self.extra_entry.pack(fill="x", padx=12)

        ctk.CTkButton(
            self,
            text="Рассчитать и сохранить",
            command=self.save_order,
            font=APP_FONT,
        ).pack(pady=(18, 18))

        self.customer_entry.focus_set()

    # ---------------------------------------------------------------
    # Выбор принтера и пластика
    # ---------------------------------------------------------------
    def _load_printers(self) -> None:
        """Загрузить список принтеров в комбо-бокс."""
        printers = get_all_printers()
        if not printers:
            self.printer_id = None
            self.filament_id = None
            self.printer_combo.configure(values=["Нет принтеров"], state="disabled")
            self.printer_combo.set("Нет принтеров")
            self.filament_combo.configure(values=[""], state="disabled")
            self.filament_combo.set("")
            return
        printer_values = [f"{pid}: {name}" for pid, name in printers]
        self.printer_combo.configure(values=printer_values, state="readonly")

        # Предвыбираем первый или заданный принтер
        if self.printer_id:
            for pid, name in printers:
                if pid == self.printer_id:
                    self.printer_combo.set(f"{pid}: {name}")
                    self.printer_id = pid
                    self._load_filaments_for_printer()
                    return
        # Выбираем первый
        self.printer_combo.set(f"{printers[0][0]}: {printers[0][1]}")
        self.printer_id = printers[0][0]
        self._load_filaments_for_printer()

    def _on_printer_change(self, _value: str) -> None:
        """Обработчик смены принтера — загружаем пластики."""
        parts = _value.split(":", 1)
        if parts:
            try:
                self.printer_id = int(parts[0])
            except ValueError:
                pass
        self._load_filaments_for_printer()

    def _load_filaments_for_printer(self) -> None:
        """Загрузить список пластиков для текущего принтера."""
        if not self.printer_id:
            return
        filaments = get_filaments_by_printer(self.printer_id)
        if filaments:
            filament_values = [f"{fid}: {mat}" for fid, mat, _ in filaments]
            self.filament_combo.configure(values=filament_values, state="readonly")
            default_fid = filaments[0][0]
            default_mat = filaments[0][1]
            self.filament_combo.set(f"{default_fid}: {default_mat}")
            self.filament_id = default_fid
        else:
            self.filament_combo.configure(values=[""], state="disabled")
            self.filament_combo.set("")
            self.filament_id = None

    def _on_filament_change(self, _value: str) -> None:
        """Обработчик смены пластика — извлекаем ID."""
        self.filament_id = None
        parts = _value.split(":", 1)
        if parts:
            try:
                self.filament_id = int(parts[0])
            except ValueError:
                pass

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
            filament_id=self.filament_id,
            extra_services=extra_services,
        )

        # Получаем материал из комбо-бокса для хранения в orders
        filament_name = self.filament_combo.get().split(":", 1)[1].strip() if self.filament_combo.get() else "PLA"

        try:
            add_order(
                customer_name=customer_name,
                deadline=deadline.isoformat(),
                file_path=self.file_path,
                weight_grams=weight_grams,
                print_time_hours=time_hours,
                material_type=filament_name,
                extra_services=extra_services,
                total_price=total_price,
                note_id=self.note_id,
                filament_id=self.filament_id,
                printer_id=self.printer_id,
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
