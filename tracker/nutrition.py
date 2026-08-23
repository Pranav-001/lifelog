"""Deterministic nutrition math over the personal foods table.

The AI extracts diet items as {name, grams}. When every item matches a
stored food and has grams, totals are computed here instead of trusting
model arithmetic; otherwise the model's own estimates are kept.
"""

from tracker.storage import Food


def enrich_diet(data: dict, foods: dict[str, Food]) -> dict:
    items = data.get("items")
    if not isinstance(items, list) or not items:
        return data

    calories = protein = fat = carbs = 0.0
    for item in items:
        if not isinstance(item, dict):
            return data
        name = str(item.get("name") or "").strip().lower()
        grams = item.get("grams")
        food = foods.get(name)
        if food is None or not isinstance(grams, (int, float)) or grams <= 0:
            return data
        factor = grams / 100.0
        calories += (food.calories_per_100g or 0.0) * factor
        protein += (food.protein_per_100g or 0.0) * factor
        fat += (food.fat_per_100g or 0.0) * factor
        carbs += (food.carbs_per_100g or 0.0) * factor

    return {
        **data,
        "calories_estimate": round(calories),
        "protein_g": round(protein, 1),
        "fat_g": round(fat, 1),
        "carbs_g": round(carbs, 1),
        "computed": True,
    }
