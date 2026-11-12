"""
Генератор иконки для приложения 'Заказики и MAX'.
Создаёт icon.ico (256x256) на основе SVG-дизайна.
"""
import os
from PIL import Image, ImageDraw, ImageFont

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_PATH = os.path.join(OUTPUT_DIR, "icon.ico")
PNG_PATH = os.path.join(OUTPUT_DIR, "icon.png")

SIZE = 512

# Цвета из SVG
BG_GRADIENT_START = (26, 26, 46)
BG_GRADIENT_END = (22, 33, 62)
BORDER_COLOR_START = (0, 210, 255)
BORDER_COLOR_END = (58, 123, 213)
TEXT_COLOR_START = (255, 255, 255)
TEXT_COLOR_END = (168, 237, 234)
TEXT_BOTTOM = (0, 210, 255)
CASE_COLOR = (26, 32, 44)
CASE_STROKE = (74, 85, 104)
BASE_COLOR = (45, 55, 72)
SCREEN_BG = (13, 17, 23)
HEAD_COLOR = (229, 62, 62)
LED_GREEN = (72, 187, 120)
LED_YELLOW = (236, 201, 75)
GRID_COLOR = (0, 210, 255)


def lerp_color(c1, c2, t):
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def create_rounded_rect(draw, bbox, radius, fill=None, outline=None, width=1):
    """Рисует прямоугольник со скруглёнными углами."""
    x0, y0, x1, y1 = bbox
    r = min(radius, (x1 - x0) // 2, (y1 - y0) // 2)
    if fill is None:
        fill = "transparent"
    draw.rounded_rectangle(bbox, radius=r, fill=fill, outline=outline, width=width)


def draw_gradient_background(img):
    """Рисует градиентный фон с скруглёнными углами."""
    draw = ImageDraw.Draw(img)
    w, h = img.size
    radius = 60

    # Рисуем фон с закруглением через mask
    for y in range(h):
        t = y / h
        color = lerp_color(BG_GRADIENT_START, BG_GRADIENT_END, t)
        draw.line([(0, y), (w, y)], fill=color)

    # Создаём маску для скругления
    mask = Image.new("L", (w, h), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
    img.putalpha(mask)
    return img


def draw_gradient_border(img):
    """Рисует градиентную рамку."""
    draw = ImageDraw.Draw(img)
    w, h = img.size
    thickness = 4
    radius = 56

    for i in range(thickness):
        t = i / thickness
        color = lerp_color(BORDER_COLOR_START, BORDER_COLOR_END, t)
        bbox = [i, i, w - 1 - i, h - 1 - i]
        draw.rounded_rectangle(bbox, radius=radius - i, outline=color, width=1)


def draw_grid_lines(img):
    """Рисует декоративные линии сетки."""
    draw = ImageDraw.Draw(img)
    w, h = img.size
    color = (*GRID_COLOR, 64)  # low opacity

    for y in range(100, 410, 50):
        draw.line([(50, y), (w - 50, y)], fill=color, width=1)
    for x in range(100, 410, 50):
        draw.line([(x, 50), (x, h - 50)], fill=color, width=1)


def draw_3d_printer(img):
    """Рисует стилизованный 3D-принтер."""
    draw = ImageDraw.Draw(img)
    cx, cy = SIZE // 2, 230

    # Ножки
    for x_off in [-110, 80]:
        draw.rounded_rectangle(
            [cx + x_off, cy + 88, cx + x_off + 30, cy + 100],
            radius=4, fill=BASE_COLOR
        )

    # Основание
    draw.rounded_rectangle(
        [cx - 140, cy + 60, cx + 140, cy + 90],
        radius=8, fill=BASE_COLOR, outline=CASE_STROKE, width=2
    )

    # LED индикаторы
    for i, (x_off, color) in enumerate([(-110, LED_GREEN), (-95, LED_GREEN), (-80, LED_YELLOW)]):
        draw.ellipse([cx + x_off - 4, cy + 48, cx + x_off + 4, cy + 56], fill=color)

    # Корпус
    draw.rounded_rectangle(
        [cx - 120, cy - 60, cx + 120, cy + 60],
        radius=12, fill=CASE_COLOR, outline=CASE_STROKE, width=2
    )

    # Верхняя и нижняя рамки корпуса
    draw.rounded_rectangle(
        [cx - 130, cy - 70, cx + 130, cy - 55],
        radius=6, fill=BASE_COLOR, outline=CASE_STROKE, width=2
    )
    draw.rounded_rectangle(
        [cx - 130, cy + 45, cx + 130, cy + 60],
        radius=6, fill=BASE_COLOR, outline=CASE_STROKE, width=2
    )

    # Окно печати
    draw.rounded_rectangle(
        [cx - 100, cy - 45, cx + 100, cy + 45],
        radius=8, fill=SCREEN_BG, outline=CASE_STROKE, width=2
    )

    # Светодиод внутри (полупрозрачный)
    overlay = Image.new("RGBA", (SIZE, SIZE), (*BG_GRADIENT_START, 204))
    overlay_mask = Image.new("L", (SIZE, SIZE), 0)
    overlay_draw = ImageDraw.Draw(overlay_mask)
    overlay_draw.rounded_rectangle(
        [cx - 95, cy - 40, cx + 95, cy + 40],
        radius=6, fill=255
    )
    img.paste(overlay, (0, 0), overlay_mask)

    # Печатающая голова (полупрозрачная)
    head_overlay = Image.new("RGBA", (SIZE, SIZE), (*HEAD_COLOR, 204))
    head_mask = Image.new("L", (SIZE, SIZE), 0)
    head_draw = ImageDraw.Draw(head_mask)
    head_draw.rounded_rectangle(
        [cx - 15, cy - 55, cx + 15, cy - 43],
        radius=3, fill=255
    )
    img.paste(head_overlay, (0, 0), head_mask)
    draw.line(
        [(cx, cy - 43), (cx, cy - 10)],
        fill=(*HEAD_COLOR, 230), width=3
    )

    # Печатаемый объект (треугольник-звезда)
    points = [
        (cx, cy - 10),
        (cx + 12, cy + 15),
        (cx - 12, cy + 15),
    ]
    draw.polygon(points, fill=(0, 210, 255, 230))
    draw.polygon(points, fill=(255, 255, 255, 128))


def draw_text(img):
    """Рисует текст 'Заказики' и 'и MAX'."""
    draw = ImageDraw.Draw(img)

    # Попытка использовать системный шрифт
    font_candidates = [
        "C:/Windows/Fonts/seguiis.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/Arial.ttf",
        "C:/Windows/Fonts/calibri.ttf",
    ]

    font_big = None
    font_small = None
    for font_path in font_candidates:
        if os.path.exists(font_path):
            try:
                font_big = ImageFont.truetype(font_path, 52)
                font_small = ImageFont.truetype(font_path, 42)
                break
            except Exception:
                continue

    if font_big is None:
        font_big = ImageFont.load_default()
        font_small = font_big

    # Текст "Заказики"
    text1 = "Заказики"
    bbox = draw.textbbox((0, 0), text1, font=font_big)
    tw = bbox[2] - bbox[0]
    draw.text(
        (SIZE // 2 - tw // 2, 370),
        text1,
        fill=TEXT_COLOR_END,
        font=font_big,
    )

    # Текст "и MAX"
    text2 = "и MAX"
    bbox = draw.textbbox((0, 0), text2, font=font_small)
    tw = bbox[2] - bbox[0]
    draw.text(
        (SIZE // 2 - tw // 2, 425),
        text2,
        fill=TEXT_BOTTOM,
        font=font_small,
    )


def draw_decorative_dots(img):
    """Рисует декоративные точки."""
    draw = ImageDraw.Draw(img)
    mid = SIZE // 2
    color = (*TEXT_BOTTOM, 153)  # semi-transparent

    dots = [
        (mid - 136, 370), (mid + 136, 370),
        (mid - 136, 430), (mid + 136, 430),
    ]
    for x, y in dots:
        draw.ellipse([x - 3, y - 3, x + 3, y + 3], fill=color)


def main():
    print(f"Генерация иконки {SIZE}x{SIZE}...")

    # Создаём изображение
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))

    draw_gradient_background(img)
    draw_grid_lines(img)
    draw_3d_printer(img)
    draw_text(img)
    draw_decorative_dots(img)
    draw_gradient_border(img)

    # Сохраняем PNG
    img.save(PNG_PATH, "PNG")
    print(f"PNG сохранён: {PNG_PATH}")

    # Конвертируем в ICO (PyInstaller поддерживает ICO)
    img_ico = img.resize((256, 256))
    img_ico.save(ICON_PATH, "ICO")
    print(f"ICO сохранён: {ICON_PATH}")

    print("Готово!")


if __name__ == "__main__":
    main()
