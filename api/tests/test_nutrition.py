"""Besin değeri özelliğinin testleri.

KATMAN 1 — saf fonksiyonlar (mock yok): ölçekleme, toplama, FatSecret yanıt
ayrıştırma ve OAuth 1.0 imzalama. İmzalama özellikle kritik: yanlış imza
"invalid signature" olarak döner ve fail-open yüzünden SESSİZCE Gemini tahminine
düşeriz — yani hata hiç görünmez, sadece FatSecret hiç çalışmaz. Bu yüzden imza
BAĞIMSIZ, yayınlanmış bir test vektörüne karşı doğrulanıyor.

KATMAN 1.5 — build_plate, sahte bir lookup_macros ile (ağ yok).

KATMAN 2 — endpoint sözleşmesi: auth, hata yolları (500 DEĞİL 200+error),
ChromaDB'ye dokunulmaması.
"""
import json

import pytest

import nutrition


# ═══════════════════════════════════════════════════════════
#  KATMAN 1 — saf fonksiyonlar
# ═══════════════════════════════════════════════════════════

class TestPieceGrams:
    """TEK PARÇA sağlaması. Kullanılamaz değer 0 sayılıyor — varsayılan bir
    ağırlık uydurmak toplamı şişirirdi, oysa kardeş parçalar ölçeği taşıyor."""

    def test_keeps_a_reasonable_portion(self):
        assert nutrition.piece_grams(150) == 150.0

    def test_accepts_numeric_string(self):
        assert nutrition.piece_grams("180") == 180.0

    @pytest.mark.parametrize("value", [0, -5, 5000, None, "", "chicken", float("nan"), float("inf")])
    def test_unusable_values_contribute_nothing(self, value):
        assert nutrition.piece_grams(value) == 0.0

    def test_boundaries_are_inclusive(self):
        assert nutrition.piece_grams(nutrition.MIN_GRAMS) == nutrition.MIN_GRAMS
        assert nutrition.piece_grams(nutrition.MAX_GRAMS) == nutrition.MAX_GRAMS


class TestPlateGrams:
    """BİRLEŞTİRME SONRASI sağlama. piece_grams'tan kritik farkı: büyük bir
    toplam varsayılana DÜŞÜRÜLMEZ, tavana çekilir."""

    def test_keeps_a_reasonable_total(self):
        assert nutrition.plate_grams(180) == 180.0

    def test_a_large_but_legitimate_total_is_not_reset_to_the_default(self):
        """REGRESYON: 10 dilim pizzanın 2000 g'lık toplamı 150 g'a iniyordu ve
        FatSecret yolunda gram ÇARPAN olduğu için besin değeri 13 kat eksik
        çıkıyordu."""
        assert nutrition.plate_grams(2000) == 2000.0

    def test_an_absurd_total_is_capped_not_defaulted(self):
        assert nutrition.plate_grams(99999) == nutrition.MAX_TOTAL_GRAMS

    @pytest.mark.parametrize("value", [0, -5, None, "", "chicken", float("nan")])
    def test_nothing_usable_falls_back_to_the_default(self, value):
        # Burada gerçekten elde bilgi yok; tahmin etmekten başka seçenek kalmıyor.
        assert nutrition.plate_grams(value) == nutrition.DEFAULT_GRAMS

    def test_the_two_ceilings_are_different(self):
        assert nutrition.MAX_TOTAL_GRAMS > nutrition.MAX_GRAMS


class TestCanonicalFoodName:
    def test_case_and_spacing_are_normalised(self):
        assert nutrition.canonical_food_name("  Cherry Tomato ") == "cherry tomato"

    @pytest.mark.parametrize("plural,singular", [
        ("cherry tomatoes", "cherry tomato"),
        ("eggs", "egg"),
        ("berries", "berry"),
    ])
    def test_plurals_collapse_onto_the_singular(self, plural, singular):
        assert nutrition.canonical_food_name(plural) == nutrition.canonical_food_name(singular)

    def test_double_s_words_are_not_stripped(self):
        # "swiss" çoğul değil — sonundaki s atılırsa "swis" olurdu.
        assert nutrition.canonical_food_name("swiss cheese") == "swiss cheese"

    def test_empty_input_is_safe(self):
        assert nutrition.canonical_food_name(None) == ""


class TestMergeDuplicateItems:
    """GERÇEK MODEL DAVRANIŞI: test fotoğrafında vision aynı kirazdomatesleri
    beş ayrı öğe olarak döndürdü. Prompt sıkılaştırıldı ama asıl koruma burada —
    prompt bir garanti değil (model davranışı sürüm sürüm değişiyor)."""

    def test_the_observed_cherry_tomato_case(self):
        detected = [
            {"name": "cherry tomato", "grams": g, "calories": c, "protein_g": 0.2,
             "carbs_g": 1.0, "fat_g": 0.1}
            for g, c in [(25, 4), (15, 3), (10, 2), (20, 4), (25, 5)]
        ]
        merged = nutrition.merge_duplicate_items(detected)

        assert len(merged) == 1
        assert merged[0]["grams"] == 95.0        # 25+15+10+20+25
        assert merged[0]["calories"] == 18.0     # 4+3+2+4+5

    def test_genuinely_different_foods_stay_separate(self):
        merged = nutrition.merge_duplicate_items([
            {"name": "rice", "grams": 100}, {"name": "chicken", "grams": 150},
        ])
        assert len(merged) == 2

    def test_singular_and_plural_spellings_merge(self):
        merged = nutrition.merge_duplicate_items([
            {"name": "cherry tomato", "grams": 20},
            {"name": "Cherry Tomatoes", "grams": 30},
        ])
        assert len(merged) == 1
        assert merged[0]["grams"] == 50.0

    def test_first_spelling_is_kept_for_display(self):
        merged = nutrition.merge_duplicate_items([
            {"name": "Cherry Tomato", "grams": 20}, {"name": "cherry tomatoes", "grams": 30},
        ])
        assert merged[0]["name"] == "Cherry Tomato"

    def test_order_of_first_appearance_is_preserved(self):
        merged = nutrition.merge_duplicate_items([
            {"name": "rice", "grams": 1}, {"name": "egg", "grams": 1}, {"name": "rice", "grams": 1},
        ])
        assert [i["name"] for i in merged] == ["rice", "egg"]

    def test_broken_numbers_do_not_break_the_merge(self):
        merged = nutrition.merge_duplicate_items([
            {"name": "rice", "grams": "oops", "calories": None},
            {"name": "rice", "grams": 100, "calories": 130},
        ])
        assert merged[0]["grams"] == 100.0
        assert merged[0]["calories"] == 130.0

    def test_one_absurd_piece_does_not_swallow_its_healthy_siblings(self):
        """REGRESYON: 99999 g'lık tek bir bozuk parça toplamı aralık dışına
        itiyor ve sağlıklı 180 g'lık parça kaybolup sonuç 150 g oluyordu."""
        merged = nutrition.merge_duplicate_items([
            {"name": "rice", "grams": 180},
            {"name": "rice", "grams": 99999},
        ])
        assert merged[0]["grams"] == 180.0

    def test_a_large_legitimate_total_survives_the_merge(self):
        merged = nutrition.merge_duplicate_items(
            [{"name": "pizza slice", "grams": 200}] * 10
        )
        assert merged[0]["grams"] == 2000.0

    def test_nameless_entries_are_dropped(self):
        assert nutrition.merge_duplicate_items([{"grams": 10}, {"name": "  "}]) == []

    def test_empty_input(self):
        assert nutrition.merge_duplicate_items([]) == []
        assert nutrition.merge_duplicate_items(None) == []


class TestScaleMacros:
    PER_100G = {"calories": 165.0, "protein_g": 31.0, "carbs_g": 0.0, "fat_g": 3.6}

    def test_scales_to_the_portion(self):
        scaled = nutrition.scale_macros(self.PER_100G, 200)
        assert scaled == {"calories": 330.0, "protein_g": 62.0, "carbs_g": 0.0, "fat_g": 7.2}

    def test_half_portion(self):
        assert nutrition.scale_macros(self.PER_100G, 50)["calories"] == 82.5

    def test_missing_keys_become_zero(self):
        assert nutrition.scale_macros({"calories": 100.0}, 100) == {
            "calories": 100.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0
        }

    def test_non_numeric_values_do_not_raise(self):
        assert nutrition.scale_macros({"calories": "n/a"}, 100)["calories"] == 0.0

    def test_a_large_portion_scales_up_instead_of_collapsing(self):
        """REGRESYON: gram burada ÇARPAN. 2000 g varsayılana düşseydi besin
        değeri sessizce 13 kat eksik çıkardı."""
        assert nutrition.scale_macros(self.PER_100G, 2000)["calories"] == 3300.0

    def test_an_absurd_portion_is_capped(self):
        expected = 165.0 * nutrition.MAX_TOTAL_GRAMS / 100.0
        assert nutrition.scale_macros(self.PER_100G, 99999)["calories"] == pytest.approx(expected)


class TestTotalMacros:
    def test_sums_every_item(self):
        items = [
            {"calories": 100.0, "protein_g": 10.0, "carbs_g": 5.0, "fat_g": 2.0},
            {"calories": 250.5, "protein_g": 5.5, "carbs_g": 30.0, "fat_g": 8.0},
        ]
        assert nutrition.total_macros(items) == {
            "calories": 350.5, "protein_g": 15.5, "carbs_g": 35.0, "fat_g": 10.0
        }

    def test_empty_plate_is_zero_not_an_error(self):
        assert nutrition.total_macros([]) == nutrition.empty_macros()

    def test_broken_item_is_skipped_not_fatal(self):
        totals = nutrition.total_macros([{"calories": 100.0}, {"calories": "oops"}])
        assert totals["calories"] == 100.0


class TestOverallSource:
    """Kullanıcıya 'kaynak' derken karışık durumu gizlememek gerekiyor."""

    def test_all_looked_up(self):
        assert nutrition.overall_source([{"source": "fatsecret"}, {"source": "fatsecret"}]) == "fatsecret"

    def test_all_estimated(self):
        assert nutrition.overall_source([{"source": "estimate"}]) == "estimate"

    def test_partial_lookup_is_reported_as_mixed(self):
        assert nutrition.overall_source([{"source": "fatsecret"}, {"source": "estimate"}]) == "mixed"

    def test_empty_plate_defaults_to_estimate(self):
        assert nutrition.overall_source([]) == "estimate"


class TestAsList:
    """FatSecret tek sonuçta DİZİ DEĞİL doğrudan nesne döndürüyor — bu normalize
    edilmezse hata yalnızca 'tam olarak bir sonuç dönen' sorgularda ortaya çıkar."""

    def test_single_object_becomes_a_list(self):
        assert nutrition.as_list({"food_id": "1"}) == [{"food_id": "1"}]

    def test_list_passes_through(self):
        assert nutrition.as_list([{"a": 1}, {"b": 2}]) == [{"a": 1}, {"b": 2}]

    def test_none_becomes_empty(self):
        assert nutrition.as_list(None) == []


class TestParseFoodDescription:
    """`foods.search` yanıtındaki özet metin — parse edilebilirse ikinci bir
    HTTP turu (food.get) hiç yapılmıyor."""

    def test_per_100g_is_used_directly(self):
        macros = nutrition.parse_food_description(
            "Per 100g - Calories: 165kcal | Fat: 3.57g | Carbs: 0.00g | Protein: 31.02g"
        )
        assert macros == {"calories": 165.0, "protein_g": 31.0, "carbs_g": 0.0, "fat_g": 3.6}

    def test_other_metric_amounts_are_normalised_to_100g(self):
        macros = nutrition.parse_food_description(
            "Per 50g - Calories: 100kcal | Fat: 1.00g | Carbs: 10.00g | Protein: 5.00g"
        )
        assert macros["calories"] == 200.0
        assert macros["protein_g"] == 10.0

    def test_non_metric_serving_returns_none(self):
        # "Per 1 medium" kaç gram belli değil → 100 g'a normalize edilemez,
        # çağıran food.get'e düşmeli.
        assert nutrition.parse_food_description(
            "Per 1 medium - Calories: 95kcal | Fat: 0.31g | Carbs: 25.13g | Protein: 0.47g"
        ) is None

    @pytest.mark.parametrize("text", ["", None, "nonsense", "Per 0g - Calories: 5kcal | Fat: 1g | Carbs: 1g | Protein: 1g"])
    def test_unusable_input_returns_none(self, text):
        assert nutrition.parse_food_description(text) is None


class TestMacrosFromServing:
    def test_metric_serving_is_normalised(self):
        macros = nutrition.macros_from_serving({
            "metric_serving_amount": "200.000", "metric_serving_unit": "g",
            "calories": "330", "protein": "62", "carbohydrate": "0", "fat": "7.2",
        })
        assert macros == {"calories": 165.0, "protein_g": 31.0, "carbs_g": 0.0, "fat_g": 3.6}

    def test_millilitres_are_accepted(self):
        assert nutrition.macros_from_serving({
            "metric_serving_amount": "100", "metric_serving_unit": "ml", "calories": "42",
        })["calories"] == 42.0

    @pytest.mark.parametrize("serving", [
        {"metric_serving_unit": "oz", "metric_serving_amount": "1"},   # metrik değil
        {"metric_serving_amount": "0", "metric_serving_unit": "g"},    # sıfır
        {"metric_serving_unit": "g"},                                  # miktar yok
        "not a dict",
    ])
    def test_unusable_serving_returns_none(self, serving):
        assert nutrition.macros_from_serving(serving) is None


class TestPickServing:
    def test_skips_non_metric_servings(self):
        chosen = nutrition.pick_serving([
            {"metric_serving_unit": "oz", "metric_serving_amount": "1"},
            {"metric_serving_amount": "100", "metric_serving_unit": "g", "calories": "50"},
        ])
        assert chosen["metric_serving_unit"] == "g"

    def test_returns_none_when_nothing_is_metric(self):
        assert nutrition.pick_serving([{"metric_serving_unit": "oz"}]) is None

    def test_handles_single_object(self):
        chosen = nutrition.pick_serving({"metric_serving_amount": "100", "metric_serving_unit": "g"})
        assert chosen is not None


class TestPickBestFood:
    """Fotoğraftan tanınan şey bir ürün değil bir yemek; markalı kayıtlar
    tesadüfen üste çıkabiliyor ve tabaktakini temsil etmiyor."""

    def test_prefers_generic_over_branded(self):
        best = nutrition.pick_best_food([
            {"food_name": "Chicken Breast", "brand_name": "SomeChain"},
            {"food_name": "Grilled Chicken Breast"},
        ])
        assert best["food_name"] == "Grilled Chicken Breast"

    def test_keeps_relevance_order_when_none_are_branded(self):
        best = nutrition.pick_best_food([{"food_name": "First"}, {"food_name": "Second"}])
        assert best["food_name"] == "First"

    def test_falls_back_to_branded_when_that_is_all_there_is(self):
        best = nutrition.pick_best_food([{"food_name": "Only", "brand_name": "Brand"}])
        assert best["food_name"] == "Only"

    def test_empty_returns_none(self):
        assert nutrition.pick_best_food([]) is None
        assert nutrition.pick_best_food(None) is None


class TestPickBestFoodAgainstRealCandidates:
    """CANLI FatSecret'tan alınan GERÇEK aday listeleri (2026-07-27).

    Bunlar uydurulmadı — anahtar eklendikten sonra üç sorgu çalıştırılıp
    dönen sıralama olduğu gibi alındı. FatSecret'ın kendi alaka sırasının
    yetmediğini bu ölçüm gösterdi.
    """

    def test_an_exact_name_match_beats_the_first_result(self):
        """REGRESYON: sorgunun BİREBİR AYNISI listede 2. sıradaydı ve
        seçilmiyordu — "Skinless" ızgara tavuğun yerine geçmez."""
        foods = [
            {"food_name": "Skinless Chicken Breast"},
            {"food_name": "Grilled Chicken Breast"},
            {"food_name": "Grilled Chicken Breast", "brand_name": "HEB"},
            {"food_name": "Fully Cooked Grilled Chicken Breast", "brand_name": "Great Value"},
        ]
        best = nutrition.pick_best_food(foods, "grilled chicken breast")
        assert best["food_name"] == "Grilled Chicken Breast"
        assert not best.get("brand_name")        # markasız olanı seçmeli

    def test_a_plain_entry_beats_a_canned_one(self):
        """REGRESYON: fotoğrafta TAZE biber vardı, "(Canned)" seçiliyordu.
        Parantez içi, fotoğrafın söylemediği bir hazırlanış varsayıyor."""
        foods = [
            {"food_name": "Green Chili Peppers (Canned)"},
            {"food_name": "Green Hot Chili Peppers"},
            {"food_name": "Green Hot Chili Peppers (Excluding Seeds, Canned)"},
            {"food_name": "Pitted Green Olives with Chili", "brand_name": "Gaea"},
        ]
        best = nutrition.pick_best_food(foods, "green chili pepper")
        assert best["food_name"] == "Green Hot Chili Peppers"

    def test_the_plain_exact_match_still_wins_when_it_is_already_first(self):
        foods = [
            {"food_name": "Eggplant"},
            {"food_name": "Cooked Eggplant (Fat Added in Cooking)"},
            {"food_name": "Cooked Eggplant"},
            {"food_name": "Fried Batter Dipped Eggplant"},
        ]
        assert nutrition.pick_best_food(foods, "eggplant")["food_name"] == "Eggplant"

    def test_plural_difference_does_not_break_the_exact_match(self):
        foods = [{"food_name": "Cooked Cherry Tomatoes"}, {"food_name": "Cherry Tomatoes"}]
        best = nutrition.pick_best_food(foods, "cherry tomato")
        assert best["food_name"] == "Cherry Tomatoes"

    def test_a_branded_exact_match_still_loses_to_a_generic_one(self):
        # Marka cezası (-100) tam eşleşme bonusundan (+5) çok daha ağır olmalı.
        foods = [
            {"food_name": "Grilled Chicken Breast", "brand_name": "HEB"},
            {"food_name": "Chicken Breast"},
        ]
        assert nutrition.pick_best_food(foods, "grilled chicken breast")["food_name"] == "Chicken Breast"

    def test_without_a_query_it_falls_back_to_relevance_order(self):
        foods = [{"food_name": "First"}, {"food_name": "Second"}]
        assert nutrition.pick_best_food(foods)["food_name"] == "First"

    def test_the_head_noun_separates_a_food_from_a_dish_made_of_it(self):
        """REGRESYON: ikisi de sorgunun TÜM kelimelerini içeriyor ve ikisi de tam
        eşleşme değil — puanlar eşitti, karar FatSecret'ın sırasına kalıyordu ve
        kızartma kazanıyordu. Ana isim ayırıyor: pepper ≠ fritter."""
        foods = [{"food_name": "Chili Pepper Fritter"}, {"food_name": "Hot Chili Pepper"}]
        assert nutrition.pick_best_food(foods, "chili pepper")["food_name"] == "Hot Chili Pepper"

    def test_a_synonym_in_the_qualifier_still_wins_over_a_branded_exact_match(self):
        """bok choy'un DOĞRU karşılığı ana adında 'choy' geçmiyor — eşanlamlı
        parantezin içinde. Ana isim bonusu bunu bozmamalı."""
        foods = [
            {"food_name": "Chinese Cabbage (Bok-Choy, Pak-Choi)"},
            {"food_name": "Baby Bok Choy", "brand_name": "Some Farm"},
            {"food_name": "Bok Choy", "brand_name": "Other Farm"},
        ]
        best = nutrition.pick_best_food(foods, "bok choy")
        assert best["food_name"] == "Chinese Cabbage (Bok-Choy, Pak-Choi)"


class TestHeadNoun:
    @pytest.mark.parametrize("name,expected", [
        ("grilled chicken breast", "breast"),
        ("Hot Chili Pepper", "pepper"),
        ("Chili Pepper Fritter", "fritter"),
        ("Mushrooms", "mushroom"),                          # tekilleştiriliyor
        ("Chinese Cabbage (Bok-Choy, Pak-Choi)", "cabbage"),  # parantez atılıyor
        ("", ""),
    ])
    def test_head_noun(self, name, expected):
        assert nutrition.head_noun(name) == expected


class TestFoodTokens:
    def test_punctuation_is_a_separator(self):
        """Tire ayraç sayılmazsa "Bok-Choy" tek kelime kalır ve 'choy' hiç
        görünmez — doğru eşleşme alaka tabanında reddedilirdi."""
        tokens = nutrition.food_tokens("Chinese Cabbage (Bok-Choy, Pak-Choi)")
        assert "choy" in tokens and "bok" in tokens and "cabbage" in tokens

    def test_words_are_singularised(self):
        assert "tomato" in nutrition.food_tokens("Cherry Tomatoes")


# ── OAuth 1.0 imzalama ────────────────────────────────────

class TestPercentEncode:
    def test_reserved_characters_are_escaped(self):
        assert nutrition.percent_encode("Hello Ladies + Gentlemen, a signed OAuth request!") == \
            "Hello%20Ladies%20%2B%20Gentlemen%2C%20a%20signed%20OAuth%20request%21"

    def test_slash_is_escaped(self):
        # urllib'in varsayılan safe='/' OAuth için YANLIŞ olurdu.
        assert nutrition.percent_encode("a/b") == "a%2Fb"

    def test_unreserved_characters_are_left_alone(self):
        assert nutrition.percent_encode("aZ0-._~") == "aZ0-._~"


class TestOAuthSignature:
    """BAĞIMSIZ TEST VEKTÖRÜ (Twitter'ın yayınlanmış OAuth 1.0a örneği).

    Kendi HMAC'imizi kendi HMAC'imizle karşılaştırmak totolojik olurdu; bu vektör
    imzalama zincirinin tamamını (yüzde-kodlama + sıralama + normalize + HMAC-SHA1
    + base64) dışarıdan doğruluyor. Yanlış imza sessizce fail-open'a düşeceği
    için başka türlü fark edilmezdi.
    """

    PARAMS = {
        "status": "Hello Ladies + Gentlemen, a signed OAuth request!",
        "include_entities": "true",
        "oauth_consumer_key": "xvz1evFS4wEEPTGEFPHBog",
        "oauth_nonce": "kYjzVBB8Y0ZFabxSWbWovY3uYSQ2pTgmZeNu2VS4cg",
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": "1318622958",
        "oauth_token": "370773112-GmHxMAgYyLbNEtIKZeRNFsMKPR9EyMZeS9weJAEb",
        "oauth_version": "1.0",
    }
    URL = "https://api.twitter.com/1/statuses/update.json"
    EXPECTED_BASE = (
        "POST&https%3A%2F%2Fapi.twitter.com%2F1%2Fstatuses%2Fupdate.json"
        "&include_entities%3Dtrue%26oauth_consumer_key%3Dxvz1evFS4wEEPTGEFPHBog"
        "%26oauth_nonce%3DkYjzVBB8Y0ZFabxSWbWovY3uYSQ2pTgmZeNu2VS4cg"
        "%26oauth_signature_method%3DHMAC-SHA1%26oauth_timestamp%3D1318622958"
        "%26oauth_token%3D370773112-GmHxMAgYyLbNEtIKZeRNFsMKPR9EyMZeS9weJAEb"
        "%26oauth_version%3D1.0%26status%3DHello%2520Ladies%2520%252B%2520Gentlemen"
        "%252C%2520a%2520signed%2520OAuth%2520request%2521"
    )

    def test_base_string_matches_the_published_vector(self):
        assert nutrition.signature_base_string("POST", self.URL, self.PARAMS) == self.EXPECTED_BASE

    def test_signature_matches_the_published_vector(self):
        signature = nutrition.sign(
            self.EXPECTED_BASE,
            "kAcSOqF21Fu85e7zjz7ZN2U4ZRhfV3WpwPAoE3Z7kBw",
            "LswwdoUaIvS8ltyTt5jkRh4J50vUPVVHtR2YPi5kE",
        )
        assert signature == "tnnArxj06cWHq44gCs1OSKk/jLY="

    def test_two_legged_key_keeps_the_trailing_ampersand(self):
        # Kullanıcı token'ı yok ama spec anahtarı iki parçanın birleşimi olarak
        # tanımlıyor; sondaki & atılırsa imza tutmaz.
        assert nutrition.sign("base", "secret") == nutrition.sign("base", "secret", "")

    def test_parameters_are_sorted_by_key(self):
        base = nutrition.signature_base_string("GET", "http://x/y", {"b": "1", "a": "2"})
        assert base.endswith(nutrition.percent_encode("a=2&b=1"))


class TestBuildSignedParams:
    def test_adds_every_required_oauth_field(self):
        params = nutrition.build_signed_params(
            {"method": "foods.search"}, "key", "secret", nonce="abc", timestamp="123",
        )
        assert params["oauth_consumer_key"] == "key"
        assert params["oauth_signature_method"] == "HMAC-SHA1"
        assert params["oauth_version"] == "1.0"
        assert params["format"] == "json"
        assert params["method"] == "foods.search"
        assert params["oauth_signature"]

    def test_signature_is_deterministic_for_a_fixed_nonce(self):
        args = ({"method": "foods.search"}, "key", "secret")
        first = nutrition.build_signed_params(*args, nonce="abc", timestamp="123")
        second = nutrition.build_signed_params(*args, nonce="abc", timestamp="123")
        assert first["oauth_signature"] == second["oauth_signature"]

    def test_different_nonce_changes_the_signature(self):
        args = ({"method": "foods.search"}, "key", "secret")
        first = nutrition.build_signed_params(*args, nonce="abc", timestamp="123")
        second = nutrition.build_signed_params(*args, nonce="xyz", timestamp="123")
        assert first["oauth_signature"] != second["oauth_signature"]

    def test_secret_never_appears_in_the_params(self):
        params = nutrition.build_signed_params({"method": "m"}, "key", "topsecret", nonce="a", timestamp="1")
        assert "topsecret" not in "".join(str(v) for v in params.values())


class TestCredentials:
    """Anahtarlar HER ÇAĞRIDA okunuyor (import anında değil) — bu test tam da
    onu kanıtlıyor: monkeypatch import'tan sonra çalışıyor."""

    def test_missing_credentials_return_none(self, monkeypatch):
        monkeypatch.delenv("FATSECRET_CONSUMER_KEY", raising=False)
        monkeypatch.delenv("FATSECRET_CONSUMER_SECRET", raising=False)
        assert nutrition.credentials() is None

    def test_half_configured_returns_none(self, monkeypatch):
        monkeypatch.setenv("FATSECRET_CONSUMER_KEY", "key")
        monkeypatch.delenv("FATSECRET_CONSUMER_SECRET", raising=False)
        assert nutrition.credentials() is None

    def test_blank_values_count_as_missing(self, monkeypatch):
        monkeypatch.setenv("FATSECRET_CONSUMER_KEY", "   ")
        monkeypatch.setenv("FATSECRET_CONSUMER_SECRET", "secret")
        assert nutrition.credentials() is None

    def test_configured_credentials_are_returned(self, monkeypatch):
        monkeypatch.setenv("FATSECRET_CONSUMER_KEY", "key")
        monkeypatch.setenv("FATSECRET_CONSUMER_SECRET", "secret")
        assert nutrition.credentials() == ("key", "secret")


class TestCallWithoutCredentials:
    def test_no_network_call_is_attempted(self, monkeypatch):
        """Anahtar yoksa ağa HİÇ çıkılmamalı — testler de bu sayede offline."""
        monkeypatch.delenv("FATSECRET_CONSUMER_KEY", raising=False)
        monkeypatch.delenv("FATSECRET_CONSUMER_SECRET", raising=False)

        def explode(*args, **kwargs):
            raise AssertionError("urlopen should not be called without credentials")

        monkeypatch.setattr(nutrition.urllib.request, "urlopen", explode)
        assert nutrition._call({"method": "foods.search"}) is None


# ═══════════════════════════════════════════════════════════
#  KATMAN 1.5 — lookup_macros'un TAM ZİNCİRİ (sahte HTTP)
#  urlopen sahtelendiği için ağ yok, ama _call → pick_best_food →
#  parse_food_description → food.get yolu gerçek kodla çalışıyor. Bu zincir
#  aksi halde yalnızca canlı anahtarla test edilebilirdi.
# ═══════════════════════════════════════════════════════════

class _FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _fake_transport(monkeypatch, payloads):
    """urlopen'i sırayla verilen gövdeleri döndürecek şekilde değiştirir.
    Çağrılan URL'leri de topluyor (kaç istek atıldığını doğrulamak için)."""
    calls = []

    def fake_urlopen(url, timeout=None):
        calls.append(url)
        return _FakeResponse(payloads[min(len(calls) - 1, len(payloads) - 1)])

    monkeypatch.setattr(nutrition.urllib.request, "urlopen", fake_urlopen)
    return calls


@pytest.fixture
def with_credentials(monkeypatch):
    monkeypatch.setenv("FATSECRET_CONSUMER_KEY", "test-key")
    monkeypatch.setenv("FATSECRET_CONSUMER_SECRET", "test-secret")


class TestLookupMacros:
    SEARCH_100G = {"foods": {"food": [{
        "food_id": "33691", "food_name": "Grilled Chicken Breast",
        "food_description": "Per 100g - Calories: 165kcal | Fat: 3.57g | Carbs: 0.00g | Protein: 31.02g",
    }]}}

    def test_metric_description_needs_only_one_request(self, monkeypatch, with_credentials):
        calls = _fake_transport(monkeypatch, [self.SEARCH_100G])

        macros = nutrition.lookup_macros("grilled chicken breast")

        assert len(calls) == 1                     # food.get'e hiç gidilmedi
        assert macros["calories"] == 165.0
        assert macros["protein_g"] == 31.0
        assert macros["matched_food"] == "Grilled Chicken Breast"

    def test_request_is_signed_and_carries_the_method(self, monkeypatch, with_credentials):
        calls = _fake_transport(monkeypatch, [self.SEARCH_100G])

        nutrition.lookup_macros("apple")

        assert "oauth_signature=" in calls[0]
        assert "method=foods.search" in calls[0]
        assert calls[0].startswith(nutrition.FATSECRET_URL)

    def test_secret_is_never_sent_on_the_wire(self, monkeypatch, with_credentials):
        calls = _fake_transport(monkeypatch, [self.SEARCH_100G])
        nutrition.lookup_macros("apple")
        assert "test-secret" not in calls[0]

    def test_non_metric_description_falls_back_to_food_get(self, monkeypatch, with_credentials):
        search = {"foods": {"food": [{
            "food_id": "35718", "food_name": "Apple",
            "food_description": "Per 1 medium - Calories: 95kcal | Fat: 0.31g | Carbs: 25.13g | Protein: 0.47g",
        }]}}
        detail = {"food": {"servings": {"serving": [
            {"metric_serving_unit": "oz", "metric_serving_amount": "1"},
            {"metric_serving_amount": "100", "metric_serving_unit": "g",
             "calories": "52", "protein": "0.26", "carbohydrate": "13.81", "fat": "0.17"},
        ]}}}
        calls = _fake_transport(monkeypatch, [search, detail])

        macros = nutrition.lookup_macros("apple")

        assert len(calls) == 2
        assert "method=food.get" in calls[1]
        assert macros["calories"] == 52.0

    def test_single_object_response_is_handled(self, monkeypatch, with_credentials):
        """FatSecret tek sonuçta dizi DEĞİL doğrudan nesne döndürüyor."""
        _fake_transport(monkeypatch, [{"foods": {"food": {
            "food_id": "1", "food_name": "Rice",
            "food_description": "Per 100g - Calories: 130kcal | Fat: 0.28g | Carbs: 28.17g | Protein: 2.69g",
        }}}])

        assert nutrition.lookup_macros("rice")["calories"] == 130.0

    def test_api_error_body_falls_back_to_none(self, monkeypatch, with_credentials):
        """FatSecret hataları HTTP 200 GÖVDESİNDE dönüyor — durum kodu yetmez."""
        _fake_transport(monkeypatch, [{"error": {"code": 8, "message": "Invalid signature"}}])
        assert nutrition.lookup_macros("apple") is None

    def test_no_match_returns_none(self, monkeypatch, with_credentials):
        _fake_transport(monkeypatch, [{"foods": {}}])
        assert nutrition.lookup_macros("zzzz") is None

    def test_an_unrelated_match_is_rejected_rather_than_shown_as_fact(self, monkeypatch, with_credentials):
        """GÖZLENEN VAKA: "bean sprouts" sorgusuna beş farklı FASULYE dönüyor,
        hiçbirinde 'sprout' geçmiyor. Kabul etmek, yanlış bir sayıyı "aranmış
        veri" etiketiyle göstermek olurdu — dürüst tahminden daha kötü."""
        _fake_transport(monkeypatch, [{"foods": {"food": [
            {"food_id": "1", "food_name": "Black Beans No Salt Added",
             "food_description": "Per 100g - Calories: 92kcal | Fat: 0.3g | Carbs: 16g | Protein: 6g"},
            {"food_id": "2", "food_name": "Peruano Beans",
             "food_description": "Per 100g - Calories: 90kcal | Fat: 0.3g | Carbs: 16g | Protein: 6g"},
        ]}}])

        assert nutrition.lookup_macros("bean sprouts") is None

    def test_a_qualifier_synonym_is_accepted_by_the_relevance_floor(self, monkeypatch, with_credentials):
        """Taban TAM ad üzerinden bakıyor (parantez dahil) — yoksa bok choy'un
        doğru karşılığı reddedilirdi."""
        _fake_transport(monkeypatch, [{"foods": {"food": {
            "food_id": "1", "food_name": "Chinese Cabbage (Bok-Choy, Pak-Choi)",
            "food_description": "Per 100g - Calories: 13kcal | Fat: 0.2g | Carbs: 2.2g | Protein: 1.5g",
        }}}])

        assert nutrition.lookup_macros("bok choy")["calories"] == 13.0

    def test_rejected_match_falls_back_to_the_model_estimate(self, monkeypatch, with_credentials):
        """Taban devreye girince özellik KIRILMIYOR — kaynak değişiyor ve
        arayüz 'estimated' rozetiyle bunu dürüstçe söylüyor."""
        _fake_transport(monkeypatch, [{"foods": {"food": {
            "food_id": "1", "food_name": "Black Beans",
            "food_description": "Per 100g - Calories: 92kcal | Fat: 0.3g | Carbs: 16g | Protein: 6g",
        }}}])

        plate = nutrition.build_plate([
            {"name": "bean sprouts", "grams": 80, "calories": 25, "protein_g": 2.6},
        ])

        assert plate["source"] == "estimate"
        assert plate["items"][0]["calories"] == 25      # Gemini'nin tahmini korundu
        assert plate["attribution"] is None

    def test_network_failure_returns_none(self, monkeypatch, with_credentials):
        def boom(url, timeout=None):
            raise nutrition.urllib.error.URLError("connection refused")

        monkeypatch.setattr(nutrition.urllib.request, "urlopen", boom)
        assert nutrition.lookup_macros("apple") is None

    def test_malformed_json_returns_none(self, monkeypatch, with_credentials):
        class Garbage:
            def read(self): return b"<html>not json</html>"
            def __enter__(self): return self
            def __exit__(self, *a): return False

        monkeypatch.setattr(nutrition.urllib.request, "urlopen", lambda url, timeout=None: Garbage())
        assert nutrition.lookup_macros("apple") is None

    def test_blank_name_makes_no_request(self, monkeypatch, with_credentials):
        calls = _fake_transport(monkeypatch, [self.SEARCH_100G])
        assert nutrition.lookup_macros("   ") is None
        assert calls == []

    def test_plate_uses_looked_up_numbers_end_to_end(self, monkeypatch, with_credentials):
        """build_plate → lookup_macros → HTTP → ayrıştırma → ölçekleme."""
        _fake_transport(monkeypatch, [self.SEARCH_100G])

        plate = nutrition.build_plate([
            {"name": "grilled chicken breast", "grams": 200, "calories": 1},
        ])

        assert plate["source"] == "fatsecret"
        assert plate["items"][0]["calories"] == 330.0     # 165 × 2, tahmin ezildi
        assert plate["attribution"] == nutrition.ATTRIBUTION


# ═══════════════════════════════════════════════════════════
#  KATMAN 1.5 — build_plate (sahte lookup_macros, ağ yok)
# ═══════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def no_fatsecret_credentials(monkeypatch):
    """Geliştiricinin makinesinde anahtar TANIMLI olabilir; testler asla gerçek
    FatSecret'a gitmemeli (yavaş, kotalı ve sonucu değişken)."""
    monkeypatch.delenv("FATSECRET_CONSUMER_KEY", raising=False)
    monkeypatch.delenv("FATSECRET_CONSUMER_SECRET", raising=False)


class TestBuildPlate:
    DETECTED = [
        {"name": "grilled chicken breast", "grams": 200,
         "calories": 999, "protein_g": 99, "carbs_g": 99, "fat_g": 99},
    ]

    def test_falls_back_to_the_model_estimate_when_lookup_fails(self, monkeypatch):
        """FAIL-OPEN: FatSecret yoksa özellik kırılmıyor, sayıların KAYNAĞI
        değişiyor. Gemini'nin tahmini zaten porsiyona göre verildiği için
        ölçeklenmiyor."""
        monkeypatch.setattr(nutrition, "lookup_macros", lambda name: None)

        plate = nutrition.build_plate(self.DETECTED)

        assert plate["source"] == "estimate"
        assert plate["items"][0]["calories"] == 999
        assert plate["items"][0]["source"] == "estimate"
        assert plate["attribution"] is None   # tahmine FatSecret atfı verilmez

    def test_looked_up_values_replace_the_estimate_and_are_scaled(self, monkeypatch):
        monkeypatch.setattr(nutrition, "lookup_macros", lambda name: {
            "calories": 165.0, "protein_g": 31.0, "carbs_g": 0.0, "fat_g": 3.6,
            "matched_food": "Grilled Chicken Breast",
        })

        plate = nutrition.build_plate(self.DETECTED)
        item = plate["items"][0]

        assert plate["source"] == "fatsecret"
        assert item["source"] == "fatsecret"
        assert item["calories"] == 330.0            # 165 × (200 g / 100 g)
        assert item["matched_food"] == "Grilled Chicken Breast"
        assert plate["attribution"] == nutrition.ATTRIBUTION

    def test_a_large_merged_portion_is_reported_honestly(self, monkeypatch):
        """REGRESYON (tahmin yolu): 10×200 g birleşip 2000 g olurken gram
        varsayılana düşüyordu — arayüz "≈150 g … 2800 kcal" gibi KENDİ İÇİNDE
        ÇELİŞEN bir satır gösteriyordu."""
        monkeypatch.setattr(nutrition, "lookup_macros", lambda name: None)

        plate = nutrition.build_plate(
            [{"name": "pizza slice", "grams": 200, "calories": 280}] * 10
        )

        assert plate["items"][0]["grams"] == 2000
        assert plate["items"][0]["calories"] == 2800.0

    def test_a_large_merged_portion_scales_looked_up_data(self, monkeypatch):
        """REGRESYON (FatSecret yolu) — en ciddisi: gram burada ÇARPAN olduğu
        için hata sessiz ve 13 katlık bir eksik beyandı."""
        monkeypatch.setattr(nutrition, "lookup_macros",
                            lambda name: {"calories": 100.0, "protein_g": 5.0})

        plate = nutrition.build_plate([{"name": "pizza slice", "grams": 200}] * 10)

        assert plate["items"][0]["grams"] == 2000
        assert plate["items"][0]["calories"] == 2000.0

    def test_portion_always_comes_from_the_photo_not_the_database(self, monkeypatch):
        # FatSecret fotoğrafa bakamaz; gram her durumda vision'dan geliyor.
        monkeypatch.setattr(nutrition, "lookup_macros", lambda name: {
            "calories": 100.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0,
        })
        plate = nutrition.build_plate([{"name": "rice", "grams": 250}])
        assert plate["items"][0]["grams"] == 250

    def test_partial_lookup_is_reported_as_mixed(self, monkeypatch):
        monkeypatch.setattr(nutrition, "lookup_macros",
                            lambda name: {"calories": 100.0} if name == "rice" else None)

        plate = nutrition.build_plate([
            {"name": "rice", "grams": 100},
            {"name": "mystery stew", "grams": 100, "calories": 42},
        ])

        assert plate["source"] == "mixed"
        assert plate["attribution"] == nutrition.ATTRIBUTION

    def test_totals_are_the_sum_of_the_items(self, monkeypatch):
        monkeypatch.setattr(nutrition, "lookup_macros", lambda name: None)
        plate = nutrition.build_plate([
            {"name": "a", "grams": 100, "calories": 100, "protein_g": 10},
            {"name": "b", "grams": 100, "calories": 250, "protein_g": 5},
        ])
        assert plate["totals"]["calories"] == 350.0
        assert plate["totals"]["protein_g"] == 15.0

    def test_nameless_items_are_dropped(self, monkeypatch):
        monkeypatch.setattr(nutrition, "lookup_macros", lambda name: None)
        plate = nutrition.build_plate([{"name": "  ", "grams": 100}, {"grams": 50}])
        assert plate["items"] == []

    def test_item_count_is_capped(self, monkeypatch):
        """Her öğe en az bir HTTP turu — sınırsız bırakılırsa tek fotoğraf
        onlarca ağ turuna dönüşür."""
        monkeypatch.setattr(nutrition, "lookup_macros", lambda name: None)
        detected = [{"name": f"food {i}", "grams": 100} for i in range(30)]
        assert len(nutrition.build_plate(detected)["items"]) == nutrition.MAX_ITEMS

    def test_duplicates_are_merged_before_the_cap_is_applied(self, monkeypatch):
        """SIRA ÖNEMLİ: önce kırpsaydık aynı gıdanın tekrarları bütçeyi yiyip
        gerçekten farklı yemekleri dışarıda bırakırdı."""
        monkeypatch.setattr(nutrition, "lookup_macros", lambda name: None)
        detected = ([{"name": "cherry tomato", "grams": 20}] * 10) + [{"name": "steak", "grams": 200}]

        names = [i["name"] for i in nutrition.build_plate(detected)["items"]]

        assert names == ["cherry tomato", "steak"]

    def test_a_repeated_food_is_looked_up_only_once(self, monkeypatch):
        """Tekilleştirme aynı zamanda FatSecret'a giden istek sayısını düşürüyor."""
        calls = []
        monkeypatch.setattr(nutrition, "lookup_macros",
                            lambda name: calls.append(name) or {"calories": 18.0})

        nutrition.build_plate([{"name": "cherry tomato", "grams": 20}] * 5)

        assert calls == ["cherry tomato"]

    def test_a_slow_service_cannot_hold_the_whole_request_hostage(self, monkeypatch):
        """Her öğe diğerinden BAĞIMSIZ yeniden deniyor; devre kesici olmadan
        8 öğe × 2 çağrı × 6 sn timeout = ~96 sn beklerdi. Bütçe dolunca kalan
        öğeler tahmine düşüyor (fail-open'ın aynısı, tetikleyicisi yavaşlık)."""
        calls = []
        clock = {"now": 0.0}

        def slow_lookup(name):
            calls.append(name)
            clock["now"] += 6.0          # her arama zaman aşımına uğruyor
            return None

        monkeypatch.setattr(nutrition, "lookup_macros", slow_lookup)
        monkeypatch.setattr(nutrition.time, "perf_counter", lambda: clock["now"])

        detected = [{"name": f"food {i}", "grams": 100} for i in range(8)]
        plate = nutrition.build_plate(detected)

        # Bütçe 10 sn: 2 arama (12 sn) sonrası kesiliyor, 8 değil.
        assert len(calls) == 2
        assert len(plate["items"]) == 8      # öğelerin hepsi yine dönüyor
        assert plate["source"] == "estimate"

    def test_the_budget_does_not_interfere_when_lookups_are_fast(self, monkeypatch):
        calls = []
        monkeypatch.setattr(nutrition, "lookup_macros",
                            lambda name: calls.append(name) or {"calories": 10.0})

        detected = [{"name": f"food {i}", "grams": 100} for i in range(8)]
        plate = nutrition.build_plate(detected)

        assert len(calls) == 8              # hepsi arandı
        assert plate["source"] == "fatsecret"

    def test_empty_detection_gives_an_empty_plate_not_an_error(self, monkeypatch):
        monkeypatch.setattr(nutrition, "lookup_macros", lambda name: None)
        plate = nutrition.build_plate([])
        assert plate["items"] == []
        assert plate["totals"] == nutrition.empty_macros()


# ═══════════════════════════════════════════════════════════
#  KATMAN 1 — vision çıktısının ayrıştırılması (llm.py)
# ═══════════════════════════════════════════════════════════

class TestParsePlateJson:
    """Model JSON modunda bile çiti/biçimi kaçırabiliyor; bozuk çıktıda
    patlamak yerine boş liste dönmeli (çağıran anlaşılır bir mesaj gösteriyor)."""

    def test_parses_the_expected_shape(self):
        import llm
        items = llm._parse_plate_json('{"items": [{"name": "rice", "grams": 180}]}')
        assert items == [{"name": "rice", "grams": 180}]

    def test_strips_a_markdown_fence(self):
        import llm
        items = llm._parse_plate_json('```json\n{"items": [{"name": "rice"}]}\n```')
        assert items == [{"name": "rice"}]

    def test_accepts_a_bare_list(self):
        import llm
        assert llm._parse_plate_json('[{"name": "apple"}]') == [{"name": "apple"}]

    def test_drops_entries_without_a_name(self):
        import llm
        items = llm._parse_plate_json('{"items": [{"name": "rice"}, {"grams": 10}, {"name": "  "}]}')
        assert items == [{"name": "rice"}]

    @pytest.mark.parametrize("raw", ["", None, "not json", "{broken", '{"items": "nope"}'])
    def test_unusable_output_returns_empty_not_an_exception(self, raw):
        import llm
        assert llm._parse_plate_json(raw) == []


# ═══════════════════════════════════════════════════════════
#  KATMAN 2 — endpoint sözleşmesi
# ═══════════════════════════════════════════════════════════

class TestNutritionEndpointAuth:
    def test_requires_an_authorization_header(self, client):
        response = client.post("/api/nutrition/from-image", json={"image_base64": "x"})
        assert response.status_code == 422


class TestNutritionEndpoint:
    PAYLOAD = {"image_base64": "data:image/jpeg;base64,AAAA"}

    def test_returns_the_plate(self, api, auth_client, monkeypatch):
        main, _ = api
        monkeypatch.setattr(main, "analyze_plate_from_image", lambda img: [
            {"name": "rice", "grams": 180, "calories": 234, "protein_g": 4.9,
             "carbs_g": 50.6, "fat_g": 0.5},
        ])
        monkeypatch.setattr(nutrition, "lookup_macros", lambda name: None)

        data = auth_client.post("/api/nutrition/from-image", json=self.PAYLOAD).json()

        assert data["items"][0]["name"] == "rice"
        assert data["totals"]["calories"] == 234.0
        assert data["source"] == "estimate"

    def test_attribution_is_returned_when_looked_up_data_is_used(self, api, auth_client, monkeypatch):
        """FatSecret ücretsiz katmanı görünür atıf ŞART koşuyor."""
        main, _ = api
        monkeypatch.setattr(main, "analyze_plate_from_image",
                            lambda img: [{"name": "rice", "grams": 100}])
        monkeypatch.setattr(nutrition, "lookup_macros", lambda name: {"calories": 130.0})

        data = auth_client.post("/api/nutrition/from-image", json=self.PAYLOAD).json()

        assert data["source"] == "fatsecret"
        assert data["attribution"] == nutrition.ATTRIBUTION

    def test_no_food_detected_gives_a_helpful_message(self, api, auth_client, monkeypatch):
        main, _ = api
        monkeypatch.setattr(main, "analyze_plate_from_image", lambda img: [])

        response = auth_client.post("/api/nutrition/from-image", json=self.PAYLOAD)

        assert response.status_code == 200
        assert "No food detected" in response.json()["error"]

    def test_quota_error_is_200_with_a_message_not_500(self, api, auth_client, monkeypatch):
        """500 CORS middleware'ine UĞRAMADAN çıkar; tarayıcıda gerçek sebep
        yerine yanıltıcı bir 'blocked by CORS policy' görünür (Faz 11b dersi)."""
        main, _ = api

        def quota_exhausted(img):
            raise Exception("429 RESOURCE_EXHAUSTED")

        monkeypatch.setattr(main, "analyze_plate_from_image", quota_exhausted)

        response = auth_client.post(
            "/api/nutrition/from-image", json=self.PAYLOAD,
            headers={"Origin": "https://recipe-rag-assistant.vercel.app"},
        )

        assert response.status_code == 200
        assert "quota" in response.json()["error"].lower()
        assert response.headers["access-control-allow-origin"] == \
            "https://recipe-rag-assistant.vercel.app"

    def test_other_vision_errors_are_also_200(self, api, auth_client, monkeypatch):
        main, _ = api

        def boom(img):
            raise Exception("connection reset")

        monkeypatch.setattr(main, "analyze_plate_from_image", boom)

        response = auth_client.post("/api/nutrition/from-image", json=self.PAYLOAD)

        assert response.status_code == 200
        assert "Could not read the photo" in response.json()["error"]

    def test_chromadb_is_never_touched(self, api, auth_client, collection, monkeypatch):
        """Kullanıcı burada tarif aramıyor; 9.795 tarifin arasında bir elmanın
        karşılığı zaten yok. Embedding maliyeti hiç ödenmemeli."""
        main, _ = api
        monkeypatch.setattr(main, "analyze_plate_from_image",
                            lambda img: [{"name": "apple", "grams": 150}])
        monkeypatch.setattr(nutrition, "lookup_macros", lambda name: None)

        auth_client.post("/api/nutrition/from-image", json=self.PAYLOAD)

        assert collection.query.called is False
        assert collection.get.called is False

    def test_food_classifier_is_not_called(self, api, auth_client, monkeypatch):
        """is_food_request METİN için yazıldı; girdi burada fotoğraf."""
        main, _ = api
        calls = []
        monkeypatch.setattr(main, "is_food_request", lambda q: calls.append(q) or True)
        monkeypatch.setattr(main, "analyze_plate_from_image",
                            lambda img: [{"name": "apple", "grams": 150}])
        monkeypatch.setattr(nutrition, "lookup_macros", lambda name: None)

        auth_client.post("/api/nutrition/from-image", json=self.PAYLOAD)

        assert calls == []

    def test_missing_image_field_is_422(self, auth_client):
        assert auth_client.post("/api/nutrition/from-image", json={}).status_code == 422
