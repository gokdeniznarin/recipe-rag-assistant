import re


def extract_filters(query_text: str) -> dict:
    """Kullanıcı sorgusundan diyet ve süre filtrelerini çıkarır.
    Dönen değer, ChromaDB'nin 'where' parametresine uygun bir sözlüktür.
    """
    query_lower = query_text.lower()
    conditions = []

    # --- Diyet etiketleri ---
    #
    # OLUMSUZ İFADELER ("without gluten", "no nuts") BİLEREK BURADA, exclusions.py'de
    # DEĞİL: bu üç alerjen için küratörlü boolean etiketlerimiz var ve onlar malzeme
    # metnindeki alt-dizi aramasından daha güvenilir (etiketler ada, kategoriye ve
    # malzemeye birlikte bakıyor). exclusions.py bu dört terimi bu yüzden atlıyor —
    # iki farklı kural aynı sorguya uygulanırsa sonuç gereksiz daralır.
    diet_keywords = {
        "gluten_free": [
            "gluten free", "gluten-free", "glutenfree",
            "without gluten", "no gluten",
        ],
        "dairy_free": [
            "dairy free", "dairy-free", "lactose free", "lactose-free",
            "without dairy", "no dairy", "without lactose", "no lactose",
        ],
        # ⚠️ TEKİL biçim ("without nut") BİLEREK YOK: bu kontrol alt-dizi araması
        # yapıyor ve "without nutmeg" ifadesi "without nut" içeriyor — muskatsız
        # bir kek isteyen kullanıcıya fıstıksız filtresi uygulanırdı.
        "nut_free": [
            "nut free", "nut-free",
            "without nuts", "no nuts",
        ],
        "vegetarian": ["vegetarian"],
        "pescatarian": ["pescatarian"],
        "vegan": ["vegan"],
    }

    for tag, keywords in diet_keywords.items():
        if any(kw in query_lower for kw in keywords):
            conditions.append({tag: True})

    # "meatless lasagna" / "no meat" → vegetarian.
    #
    # BU NEDEN exclusions.py'DE DEĞİL: orası bir malzeme ADINI metinde arıyor,
    # oysa "meat" bir KATEGORİ. Ölçüldü — "meatless lasagna" sorgusunda dönen
    # tariflerin malzemesinde literal "meat" kelimesi geçmiyor, `ground beef` ve
    # `italian sausage` geçiyor; kelime bazlı dışlama 5 sonucun 4'ünü elemekte
    # başarısızdı. Kategoriyi kapsayan tek şey vejetaryen etiketi.
    #
    # ⚠️ REGEX, ALT-DİZİ DEĞİL: "no meat" düz alt-dizi olarak arandığında
    # "no meatballs" ifadesinin İÇİNDE eşleşiyor ve köftesiz bir tarif isteyen
    # kullanıcıya vejetaryen filtresi uygulanırdı. `\b` bunu engelliyor —
    # `nutmeg`/`without nut` tuzağının aynı ailesi.
    if re.search(r"\b(?:meatless|meat[-\s]free|(?:without|no)\s+meat)\b", query_lower):
        if {"vegetarian": True} not in conditions:
            conditions.append({"vegetarian": True})

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

    # --- Protein kısıtı ---
    #
    # 🔴 BU FİLTRE GÖRÜNÜR BİR HATAYI KAPATIYOR: "high protein meal" araması
    # "Low Protein" KATEGORİSİNDEKİ tarifleri döndürüyordu (Macaroni Salad,
    # Mashed Potatoes). Sebep, embedding'lerin bilinen zayıflığı — karşıt anlam
    # duyarsızlığı: gömme metni "Category: Low Protein" içeriyor ve sorguyla
    # paylaştığı baskın sinyal "protein" kelimesi; "high"/"low" karşıtlığı
    # vektör uzayında çok daha zayıf kalıyor. Kart "Low Protein" yazarken
    # sorgunun "high protein" demesi, zayıf sıralama değil AÇIK BİR ÇELİŞKİ.
    #
    # İki katman, çünkü tek başına ikisi de yetmiyor:
    #   - Kategori dışlaması çelişkiyi kesin bitiriyor ama yalnızca Food.com'un
    #     etiketlediği 127 tarifi kapsıyor (107 Low + 20 High).
    #   - Sayısal eşik etiketsiz tarifleri de eliyor.
    #
    # ⚠️ Eşikler ÖLÇÜME dayanıyor (9.795 tarif): protein medyanı 8.8 g,
    # p75 24.4 g. 20 g "bir öğünde anlamlı protein" için makul bir taban ve
    # koleksiyonun ~%28'ini bırakıyor — arama sonuçsuz kalmayacak kadar geniş.
    # ⚠️ `protein_content`'in tabanı da kalori gibi belirsiz (porsiyon mu tarif
    # mi). Burada kabul edilebilir: bu bir SIRALAMA yardımı, dışarıya
    # yayınlanan bir iddia değil (schema.org kararıyla farkı bu) ve hata yönü
    # "büyük bir tarif yüksek proteinli sayılabilir" — Macaroni Salad'ın
    # dönmesinden çok daha iyi.
    if "high protein" in query_lower or "high-protein" in query_lower:
        conditions.append({"protein_content": {"$gte": 20}})
        conditions.append({"category": {"$ne": "Low Protein"}})
    elif "low protein" in query_lower or "low-protein" in query_lower:
        conditions.append({"protein_content": {"$lte": 10}})
        conditions.append({"category": {"$ne": "High Protein"}})

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