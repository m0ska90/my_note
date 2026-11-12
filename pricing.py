"""Расчёт стоимости 3D-печати."""

from database import SETTING_DEFAULTS, get_filament_price, get_setting


def calculate_price(
    weight_grams: float,
    time_hours: float,
    filament_id: int | None = None,
    extra_services: float = 0.0,
) -> float:
    """Рассчитать стоимость печати.

    Args:
        weight_grams: вес модели в граммах.
        time_hours: время печати в часах.
        filament_id: ID пластика из таблицы filaments.
                      Если None — используется дефолтная цена 2.0 руб/г.
        extra_services: стоимость доп. услуг.

    Returns:
        Общая стоимость.
    """
    # Получаем актуальную цену пластика из БД
    if filament_id is not None:
        material_price = get_filament_price(filament_id)
    else:
        material_price = 2.0  # Дефолтная цена

    material_cost = (
        weight_grams
        * material_price
        * get_setting("waste_factor", SETTING_DEFAULTS["waste_factor"])
    )
    labor_cost = time_hours * get_setting(
        "labor_rate",
        SETTING_DEFAULTS["labor_rate"],
    )
    depreciation_cost = time_hours * get_setting(
        "depreciation_rate",
        SETTING_DEFAULTS["depreciation_rate"],
    )
    electricity_cost = time_hours * get_setting(
        "electricity_rate",
        SETTING_DEFAULTS["electricity_rate"],
    )
    return material_cost + labor_cost + depreciation_cost + electricity_cost + extra_services
