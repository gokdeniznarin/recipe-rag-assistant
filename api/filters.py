import re


def extract_filters(query_text: str) -> dict:
    """Kullanıcı sorgusundan diyet ve süre filtrelerini çıkarır.
    Dönen değer, ChromaDB'nin 'where' parametresine uygun bir sözlüktür.
    """
    query_lower = query_text.lower()
    conditions = []

    # --- Diyet etiketleri ---
    diet_keywords = {
        "gluten_free": ["gluten free", "gluten-free", "glutenfree"],
        "dairy_free": ["dairy free", "dairy-free", "lactose free", "lactose-free"],
        "nut_free": ["nut free", "nut-free"],
        "vegetarian": ["vegetarian"],
        "pescatarian": ["pescatarian"],
        "vegan": ["vegan"],
    }

    for tag, keywords in diet_keywords.items():
        if any(kw in query_lower for kw in keywords):
            conditions.append({tag: True})

    # --- Süre kısıtı ---
    time_match = re.search(r'(\d+)\s*(?:minutes?|mins?)', query_lower)
    if time_match:
        max_minutes = int(time_match.group(1))
        conditions.append({"total_time_min": {"$lte": max_minutes}})

    quick_words = ["quick", "fast", "speedy"]
    if not time_match and any(w in query_lower for w in quick_words):
        conditions.append({"total_time_min": {"$lte": 30}})

    # --- Kalori kısıtı ---
    if "low calorie" in query_lower or "low-calorie" in query_lower:
        conditions.append({"calories": {"$lte": 400}})

    # --- Yağ kısıtı ---
    if "low fat" in query_lower or "low-fat" in query_lower:
        conditions.append({"fat_content": {"$lte": 10}})

    if len(conditions) == 0:
        return None
    elif len(conditions) == 1:
        return conditions[0]
    else:
        return {"$and": conditions}


# --- TEST ---
if __name__ == "__main__":
    test_queries = [
        "gluten free and quick chicken dinner",
        "vegan dessert under 20 minutes",
        "low calorie vegetarian lunch",
        "just a regular pasta dish",
    ]

    for q in test_queries:
        print(f"Query: '{q}'")
        print(f"Filters: {extract_filters(q)}")
        print()