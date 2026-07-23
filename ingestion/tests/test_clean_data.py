"""clean_data.py'deki saf temizleme fonksiyonları için birim testleri.

Bu fonksiyonlar projenin veri kalitesi iddialarının dayanağı: diyet etiketleri,
süreler ve malzeme listeleri buradan çıkıp ChromaDB'ye gömülüyor. Bir hata
burada yapılırsa 4886 tarifin tamamına yayılıyor ve ancak yeniden ingestion ile
düzeliyor.

    python -m pytest ingestion/tests/test_clean_data.py -v
"""
import pytest

from clean_data import (
    build_description,
    clean_text,
    extract_diet_tags,
    parse_duration_to_minutes,
    parse_ingredients,
    parse_instructions,
)


class TestCleanText:
    def test_unescapes_html_entities(self):
        assert clean_text("Salt &amp; Pepper") == "Salt & Pepper"

    def test_smart_quotes(self):
        # &ldquo;/&rdquo; ASCII " değil, tipografik tırnağa çevriliyor
        assert clean_text("&ldquo;Best&rdquo; Cake") == "“Best” Cake"

    def test_missing_value_becomes_empty_string(self):
        assert clean_text(None) == ""


class TestParseIngredients:
    def test_r_vector(self):
        assert parse_ingredients('c("chicken", "pepper")') == ["chicken", "pepper"]

    def test_single_item(self):
        assert parse_ingredients('c("chicken")') == ["chicken"]

    def test_empty_r_vector(self):
        # R'ın boş vektör gösterimi — tırnak içi hiçbir şey yok
        assert parse_ingredients("character(0)") == []

    def test_missing_value(self):
        assert parse_ingredients(None) == []


class TestParseInstructions:
    def test_numbers_the_steps(self):
        assert parse_instructions('c("Heat the pan", "Add oil")') == "1. Heat the pan 2. Add oil"

    def test_empty_r_vector(self):
        assert parse_instructions("character(0)") == ""

    def test_missing_value(self):
        assert parse_instructions(None) == ""


class TestParseDuration:
    @pytest.mark.parametrize("iso, expected", [
        ("PT24H45M", 1485),   # 24*60 + 45
        ("PT30M", 30),
        ("PT2H", 120),        # sadece saat
        ("PT1H5M", 65),
    ])
    def test_iso_to_minutes(self, iso, expected):
        assert parse_duration_to_minutes(iso) == expected

    def test_zero_duration_is_treated_as_missing(self):
        # `total_minutes > 0` kontrolü yüzünden sıfır süre 0 değil None dönüyor.
        # Yani "süre 0 dakika" ile "süre bilinmiyor" aynı kabul ediliyor.
        assert parse_duration_to_minutes("PT0M") is None

    def test_missing_value(self):
        assert parse_duration_to_minutes(None) is None


# ── Diyet etiketleri ──────────────────────────────────────
# Üç kaynaktan çıkarım yapılıyor: malzeme listesi, kategori ve tarif adı.
# Kategori ve ad, malzeme listesindeki eksiklere karşı "güvenlik ağı".

class TestDietTagsMeat:
    def test_meat_in_ingredients(self):
        tags = extract_diet_tags(["chicken", "rice"], "Chicken Breast", "Quick Chicken")
        assert "vegetarian" not in tags
        assert "vegan" not in tags

    def test_meat_detected_from_category_only(self):
        # Malzemede et kelimesi yok, kategori ele veriyor
        tags = extract_diet_tags(["rice", "salt"], "Poultry", "Sunday Dinner")
        assert "vegetarian" not in tags

    def test_meat_detected_from_name_only(self):
        # Malzeme listesi eksik, ad ele veriyor — ADA BAKAN GÜVENLİK AĞI
        tags = extract_diet_tags(["lettuce", "tomato"], "Salad", "Chicken Salad")
        assert "vegetarian" not in tags

    def test_plant_based_name_signal_overrides_meat_word(self):
        # "Vegan Chicken Nuggets" taklit üründür; addaki "chicken" sayılmamalı
        tags = extract_diet_tags(["tofu", "soy sauce"], "Vegan", "Vegan Chicken Nuggets")
        assert "vegetarian" in tags
        assert "vegan" in tags

    def test_seafood_is_pescatarian_not_vegetarian(self):
        tags = extract_diet_tags(["salmon", "lemon"], "Fish", "Grilled Salmon")
        assert "pescatarian" in tags
        assert "vegetarian" not in tags


class TestDietTagsGluten:
    def test_flour_blocks_gluten_free(self):
        assert "gluten_free" not in extract_diet_tags(["flour", "sugar"], "Dessert", "Cake")

    def test_gluten_category_blocks_gluten_free(self):
        assert "gluten_free" not in extract_diet_tags(["eggs", "milk"], "Pie", "Custard Pie")

    def test_explicitly_labeled_gluten_free_category_wins(self):
        # Kategori "Gluten Free ..." diyorsa malzemedeki un görmezden geliniyor
        tags = extract_diet_tags(["flour", "water"], "Gluten Free Breads", "GF Bread")
        assert "gluten_free" in tags


class TestDietTagsDairyAndVegan:
    def test_butter_blocks_dairy_free(self):
        assert "dairy_free" not in extract_diet_tags(["butter", "sugar"], "Dessert", "Shortbread")

    def test_egg_blocks_vegan_but_not_vegetarian(self):
        tags = extract_diet_tags(["flour", "sugar", "egg"], "Dessert", "Cake")
        assert "vegetarian" in tags
        assert "vegan" not in tags

    def test_honey_blocks_vegan(self):
        tags = extract_diet_tags(["oats", "honey"], "Snack", "Granola")
        assert "vegetarian" in tags
        assert "vegan" not in tags

    def test_fully_plant_based_gets_vegan(self):
        tags = extract_diet_tags(["lettuce", "tomato"], "Salad", "Garden Salad")
        assert "vegan" in tags


class TestDietTagsNuts:
    def test_nut_in_ingredients(self):
        assert "nut_free" not in extract_diet_tags(["almond", "sugar"], "Dessert", "Marzipan")

    def test_nut_in_category(self):
        assert "nut_free" not in extract_diet_tags(["sugar", "butter"], "Peanut Butter", "Fudge")

    @pytest.mark.xfail(
        reason="BİLİNEN HATA: nut kontrolü tarif adına bakmıyor (clean_data.py:121). "
               "Ada bakan güvenlik ağı yalnızca et için kurulmuş (satır 77-80); "
               "nuts, dairy ve gluten yalnızca malzeme + kategoriye bakıyor. "
               "validate_tags.py de aynı kör noktayı paylaşıyor (satır 48-51 "
               "sadece RecipeCategory'ye bakıyor), o yüzden 0 çelişki raporluyor.",
        strict=True,
    )
    def test_nut_in_name_only_should_not_be_nut_free(self):
        # Gerçek örnekler (canlı aramada görüldü): "Pine Nut and Almond Cookies"
        # ve "wheat free peanut butter cookies" nut_free: True etiketli.
        tags = extract_diet_tags(["flour", "sugar"], "Cookie", "Pine Nut and Almond Cookies")
        assert "nut_free" not in tags


class TestBuildDescription:
    def _row(self, **overrides):
        row = {
            "name_clean": "Test Cake",
            "RecipeCategory": "Dessert",
            "ingredients_clean": ["flour", "sugar"],
            "total_time_min": 45,
            "diet_tags": ["vegetarian"],
        }
        row.update(overrides)
        return row

    def test_contains_all_fields(self):
        # Embedding'e giden metin bu — alanlardan biri düşerse semantic arama
        # sessizce kötüleşir, hiçbir yerde hata görünmez.
        text = build_description(self._row())
        assert "Test Cake" in text
        assert "Dessert" in text
        assert "flour, sugar" in text
        assert "45 minutes" in text
        assert "vegetarian" in text

    def test_missing_time_falls_back(self):
        assert "unknown time" in build_description(self._row(total_time_min=None))

    def test_no_diet_tags_falls_back(self):
        assert "no specific diet" in build_description(self._row(diet_tags=[]))
