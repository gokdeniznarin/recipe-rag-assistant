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

    def test_nut_in_name_only_should_not_be_nut_free(self):
        """Faz 7'de fark edilen, Faz 15b'de kök sebebi bulunan, FAZ 29'DA
        DÜZELTİLEN hata. Uzun süre `xfail(strict=True)` olarak duruyordu.

        Kök sebep: ada bakan güvenlik ağı yalnızca ET için kurulmuştu;
        nuts/dairy/gluten sadece malzeme + kategoriye bakıyordu. Malzeme
        listesi ["flour","sugar"] olan bir tarif, adı açıkça "Almond" dese
        bile fıstıksız sayılıyordu."""
        tags = extract_diet_tags(["flour", "sugar"], "Cookie", "Pine Nut and Almond Cookies")
        assert "nut_free" not in tags

    def test_the_other_half_of_the_same_bug(self):
        """İkinci canlı örnek (Faz 7): "wheat free peanut butter cookies"."""
        tags = extract_diet_tags(["flour", "sugar"], "Dessert", "wheat free peanut butter cookies")
        assert "nut_free" not in tags


class TestWordBoundaryMatching:
    """Faz 29 — eşleştirme DÜZ ALT-DİZİ'den TAM KELİME'ye geçti.

    Her test gerçek veri setinde ÖLÇÜLEN bir vakayı sabitliyor. Düz alt-dizi
    aramasına dönülürse hepsi kırılır.
    """

    def test_graham_crackers_are_not_meat(self):
        """🔴 En pahalı tuzak: `ham` et listesine eklenecekti ve düz alt-dizi
        aramasında **graham** kelimesine takılıyordu — 9.795 tarifte 101 kez,
        yani 101 tatlı "et içeriyor" sayılacaktı. Düzeltmekten daha kötü."""
        tags = extract_diet_tags(["graham cracker", "sugar", "lemon"], "Pie", "5 Minute Lemon Pie")
        assert "vegetarian" in tags

    def test_champagne_and_bechamel_are_not_ham_either(self):
        for ingredient in ["champagne", "bechamel sauce", "chambord"]:
            tags = extract_diet_tags([ingredient, "sugar"], "Dessert", "Something Sweet")
            assert "vegetarian" in tags, ingredient

    def test_beefsteak_tomatoes_are_a_tomato(self):
        """Ölçümde çıktı: `Calzones of Tomato, Mozzarella and Basil` etli
        sayılıyordu, çünkü "beef" **beefsteak tomatoes** içinde eşleşiyordu."""
        tags = extract_diet_tags(["beefsteak tomatoes", "olive oil"], "Vegetable", "Tomato Salad")
        assert "vegetarian" in tags

    def test_aceitunas_does_not_contain_tuna(self):
        """`Marinated Olives - Aceitunas Aliñadas` pescatarian etiketliydi:
        "tuna" kelimesi ace-TUNA-s içinde eşleşiyordu."""
        tags = extract_diet_tags(["olives", "olive oil"], "Peppers", "Marinated Olives - Aceitunas Aliñadas")
        assert "vegan" in tags
        assert "pescatarian" not in tags

    def test_crabapple_is_not_a_crab(self):
        tags = extract_diet_tags(["crabapple", "sugar"], "Jam", "Crabapple Jam")
        assert "pescatarian" not in tags
        assert "vegetarian" in tags

    def test_goat_cheese_contains_no_oats(self):
        """"oat" kelimesi **goat** içinde eşleşiyordu, yani keçi peynirli her
        tarif "gluten içeriyor" sayılıyordu."""
        tags = extract_diet_tags(["goat cheese", "tomato"], "Cheese", "Goat Cheese Salad")
        assert "gluten_free" in tags

    def test_compound_words_still_count_as_meat(self):
        """⚠️ Kelime sınırının BEDELİ: `\\bmeats?\\b` artık "meatball" içinde
        eşleşmiyor. Ölçümde yakalandı (`Meatball Casserole` vejetaryene
        düşmüştü), bileşik hâller listeye ayrıca yazıldı."""
        for name in ["Meatball Casserole", "Classic Meatloaf", "Fried Catfish Nuggets"]:
            tags = extract_diet_tags(["onion", "salt"], "Dinner", name)
            assert "vegetarian" not in tags, name

    def test_a_plant_based_signal_still_wins(self):
        """"Tofu Meatloaf" gerçekten vejetaryen — `meatloaf` et listesine
        girince taklit ürün sinyali (`tofu`) korumaya alındı."""
        tags = extract_diet_tags(["tofu", "onion"], "Vegetable", "Tofu Meatloaf")
        assert "vegetarian" in tags


class TestExpandedMeatList:
    """Faz 29 — ölçüldü: 228 tarif vejetaryen etiketliyken içinde et vardı."""

    @pytest.mark.parametrize("meat", [
        "ham", "sausage", "prosciutto", "pancetta", "salami",
        "veal", "duck", "venison", "chorizo", "pepperoni",
    ])
    def test_missing_meats_are_now_caught(self, meat):
        assert "vegetarian" not in extract_diet_tags([meat, "onion"], "Dinner", "Some Dish")

    def test_the_recipe_that_started_it(self):
        """`Cheesy Asparagus And Ham` (id 25500) — adında AÇIKÇA ham geçiyor
        ve yine de vejetaryen etiketliydi."""
        tags = extract_diet_tags(
            ["butter", "flour", "milk", "cheddar", "asparagus", "ham"],
            "Ham", "Cheesy Asparagus And Ham")
        assert "vegetarian" not in tags

    @pytest.mark.parametrize("seafood", ["clam", "prawn", "scallop", "mussel", "oyster"])
    def test_expanded_seafood_is_caught(self, seafood):
        tags = extract_diet_tags([seafood, "garlic"], "Seafood", "Some Dish")
        assert "vegetarian" not in tags
        assert "pescatarian" in tags


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
