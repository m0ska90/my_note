def calculate_price(
    weight_grams: float,
    time_hours: float,
    material_price_per_gram: float = 2.0,
    extra_services: float = 0.0,
) -> float:
    material_cost = weight_grams * material_price_per_gram * 1.15
    labor_cost = time_hours * 250
    depreciation_cost = time_hours * 15
    electricity_cost = time_hours * 1
    return material_cost + labor_cost + depreciation_cost + electricity_cost + extra_services
