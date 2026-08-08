"""filters.extract_filters için birim testleri.

Saf fonksiyon: ağ yok, mock yok, container gerekmiyor.
    python -m pytest api/tests/test_filters.py -v
"""
import pytest

from filters import extract_filters


# ── Dönüş şekli ───────────────────────────────────────────
# Fonksiyon üç FARKLI tip döndürüyor: None / düz dict / {"$and": [...]}.
# Dönen değer doğrudan ChromaDB'nin where= parametresine veriliyor, yani şekil
# yanlış olursa arama hata vermeden bozulur.

class TestReturnShape:
    def test_no_keyword_returns_none(self):
        assert extract_filters("just a regular pasta dish") is None

    def test_single_condition_is_flat_dict(self):
        # Tek koşul $and'e sarılMAmalı
        assert extract_filters("gluten free chicken") == {"gluten_free": True}

    def test_multiple_conditions_wrapped_in_and(self):
        result = extract_filters("gluten free and quick chicken dinner")
        assert result == {
            "$and": [
                {"gluten_free": True},
                {"total_time_min": {"$lte": 30}},
            ]
        }

    def test_empty_query(self):
        assert extract_filters("") is None


# ── Diyet etiketleri ──────────────────────────────────────

class TestDietKeywords:
    @pytest.mark.parametrize("query, expected_tag", [
        ("gluten free bread", "gluten_free"),
        ("gluten-free bread", "gluten_free"),
        ("glutenfree bread", "gluten_free"),
        ("dairy free ice cream", "dairy_free"),
        ("dairy-free ice cream", "dairy_free"),
        ("nut free cookies", "nut_free"),
        ("nut-free cookies", "nut_free"),
        ("vegetarian lasagna", "vegetarian"),
        ("pescatarian dinner", "pescatarian"),
        ("vegan brownies", "vegan"),
    ])
    def test_keyword_variants(self, query, expected_tag):
        assert extract_filters(query) == {expected_tag: True}

    @pytest.mark.parametrize("query", ["lactose free dessert", "lactose-free dessert"])
    def test_lactose_maps_to_dairy_free(self, query):
        # Kullanıcı "lactose" yazıyor, metadata alanının adı "dairy_free"
        assert extract_filters(query) == {"dairy_free": True}

    def test_case_insensitive(self):
        result = extract_filters("FAST GLUTEN-FREE meal")
        assert {"gluten_free": True} in result["$and"]

    def test_vegan_does_not_imply_vegetarian_filter(self):
        # Veri tarafında vegan tarifler vegetarian da etiketli, ama filtre
        # çıkarımı bu çıkarımı yapmıyor — sorgudaki kelime ne ise o.
        assert extract_filters("vegan pasta") == {"vegan": True}

    def test_vegetarian_does_not_add_vegan_filter(self):
        assert extract_filters("vegetarian pasta") == {"vegetarian": True}


# ── Süre kısıtı ───────────────────────────────────────────

class TestTimeConstraint:
    @pytest.mark.parametrize("query, expected_max", [
        ("dinner in 45 minutes", 45),
        ("dinner in 45 mins", 45),
        ("dinner in 45 min", 45),
        ("something under 20 minute", 20),
    ])
    def test_explicit_duration(self, query, expected_max):
        assert extract_filters(query) == {"total_time_min": {"$lte": expected_max}}

    @pytest.mark.parametrize("word", ["quick", "fast", "speedy"])
    def test_quick_words_default_to_30(self, word):
        assert extract_filters(f"{word} dinner") == {"total_time_min": {"$lte": 30}}

    def test_explicit_number_beats_quick_word(self):
        """filters.py:32'deki `not time_match` koşulunun testi.

        Sorguda hem "quick" hem açık bir sayı varsa SAYI kazanmalı. Koşul
        kaldırılırsa $and içine aynı alan için iki çelişkili koşul girer
        ($lte 20 ve $lte 30) ve bu hata vermeden sonuçları değiştirir.
        """
        result = extract_filters("quick vegan dessert under 20 minutes")
        time_conditions = [c for c in result["$and"] if "total_time_min" in c]
        assert time_conditions == [{"total_time_min": {"$lte": 20}}]


# ── Kalori / yağ ──────────────────────────────────────────

class TestNutritionConstraints:
    @pytest.mark.parametrize("query", ["low calorie lunch", "low-calorie lunch"])
    def test_low_calorie(self, query):
        assert extract_filters(query) == {"calories": {"$lte": 400}}

    @pytest.mark.parametrize("query", ["low fat snack", "low-fat snack"])
    def test_low_fat(self, query):
        assert extract_filters(query) == {"fat_content": {"$lte": 10}}

    def test_all_constraints_combined(self):
        result = extract_filters("low calorie low fat vegan meal")
        conditions = result["$and"]
        assert len(conditions) == 3
        assert {"vegan": True} in conditions
        assert {"calories": {"$lte": 400}} in conditions
        assert {"fat_content": {"$lte": 10}} in conditions


# ── Protein (Faz 29) ──────────────────────────────────────
# 🔴 GÖRÜNÜR BİR HATAYI KAPATIYOR: "high protein meal" araması "Low Protein"
# KATEGORİSİNDEKİ tarifleri döndürüyordu. Sebep embedding'lerin karşıt anlam
# duyarsızlığı — gömme metni "Category: Low Protein" içeriyor ve sorguyla
# paylaştığı baskın sinyal "protein" kelimesi. Kart "Low Protein" derken
# sorgunun "high protein" demesi zayıf sıralama değil, açık bir çelişki.

class TestProteinFilter:
    def test_high_protein_sets_a_floor(self):
        conditions = extract_filters("high protein meal")["$and"]
        assert {"protein_content": {"$gte": 20}} in conditions

    def test_high_protein_excludes_the_contradicting_category(self):
        """Sayısal eşik tek başına yetmiyor: kullanıcı kartta "Low Protein"
        yazısını görüyor ve bu, sayı ne olursa olsun çelişki gibi okunuyor."""
        conditions = extract_filters("high protein meal")["$and"]
        assert {"category": {"$ne": "Low Protein"}} in conditions

    def test_low_protein_is_the_mirror_image(self):
        conditions = extract_filters("low protein dinner")["$and"]
        assert {"protein_content": {"$lte": 10}} in conditions
        assert {"category": {"$ne": "High Protein"}} in conditions

    def test_hyphenated_forms_work(self):
        assert extract_filters("high-protein snack") is not None
        assert extract_filters("low-protein snack") is not None

    def test_the_two_are_mutually_exclusive(self):
        """Aynı sorguda ikisi birden çıkarsa filtre kendi kendiyle çelişir ve
        ChromaDB hiçbir sonuç döndüremez."""
        conditions = extract_filters("high protein and low protein")["$and"]
        floors = [c for c in conditions if "protein_content" in c]
        assert len(floors) == 1

    def test_plain_protein_adds_no_constraint(self):
        """"protein" tek başına bir yön belirtmiyor — filtre uydurmak,
        kullanıcının istemediği tarifleri elemek olurdu."""
        assert extract_filters("protein shake") is None

    def test_it_combines_with_other_filters(self):
        conditions = extract_filters("quick high protein gluten free meal")["$and"]
        assert {"gluten_free": True} in conditions
        assert {"total_time_min": {"$lte": 30}} in conditions
        assert {"protein_content": {"$gte": 20}} in conditions


# ── Bilinen sınırlar ──────────────────────────────────────
# Bunlar hata değil, kabul edilmiş sınırlar. Teste yazılmalarının sebebi:
# filters.py ileride geliştirilirse bu testlerin KASTEN kırılması gerekiyor —
# yani sınırın nerede olduğu kodda görünür kalıyor.

class TestKnownLimitations:
    def test_negation_is_not_understood(self):
        # "no nuts" mantıken nut_free demek, ama kural bazlı çıkarım
        # olumsuzlama anlamıyor. "nut free" yazılmalı.
        assert extract_filters("no nuts please") is None

    def test_hour_based_duration_is_not_parsed(self):
        # Regex sadece dakika yakalıyor (minutes?|mins?) — "2 hours" kaçıyor.
        assert extract_filters("something in 2 hours") is None
