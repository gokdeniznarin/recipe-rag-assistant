"""Sorgudaki olumsuzlama ("mantarsız makarna") — bkz. api/exclusions.py.

Katman 1: saf çıkarım + eşleştirme (mock yok)
Katman 1.5: sözlüğün BÜTÜNLÜĞÜ — bu özelliğin en sessiz bozulma biçimi
Katman 2: endpoint sözleşmesi (over-fetch, temizlenmiş metin, eleme)
"""
import json

import pytest

from exclusions import (
    DESCRIPTORS,
    VOCAB_PATH,
    MAX_EXCLUSIONS,
    excluded_terms_in_recipe,
    extract_exclusions,
    filter_excluded,
)


# ══════════ Katman 1 — extract_exclusions ══════════

class TestExtractExclusions:
    @pytest.mark.parametrize("query,term,expected_text", [
        ("pasta without mushrooms", "mushrooms", "pasta"),
        ("salad without onions", "onions", "salad"),
        ("chicken without cheese", "cheese", "chicken"),
        ("pasta no mushrooms", "mushrooms", "pasta"),
        ("soup minus butter", "butter", "soup"),
        ("cake except eggs", "eggs", "cake"),
        ("pasta hold the mushrooms", "mushrooms", "pasta"),
        ("cookies allergic to peanuts", "peanuts", "cookies"),
    ])
    def test_recognises_negation_triggers(self, query, term, expected_text):
        terms, text = extract_exclusions(query)
        assert terms == [term]
        assert text == expected_text

    def test_removes_the_term_from_the_search_text(self):
        """ADIM 1 — asıl mesele bu.

        Terim metinde kalırsa embedding tam da istenmeyen yöne çekilir: ölçüldü,
        "pasta without mushrooms" sorgusunun 5/5 sonucunda mantar vardı ve
        1. sonuç "Mushroom Pasta for 2" idi.
        """
        _, text = extract_exclusions("pasta without mushrooms")
        assert "mushroom" not in text.lower()
        assert "without" not in text.lower()
        assert "pasta" in text

    def test_collects_several_terms(self):
        terms, text = extract_exclusions("pasta without mushrooms and onions")
        assert terms == ["mushrooms", "onions"]
        assert "mushroom" not in text.lower() and "onion" not in text.lower()

    def test_comma_also_separates_terms(self):
        assert extract_exclusions("soup without mushrooms, onions")[0] == ["mushrooms", "onions"]

    def test_adjacent_words_are_one_term_not_several(self):
        """🔴 AYIRAÇ ŞART. Şartsız hâlde ardışık her malzeme kelimesi
        yutuluyordu: "without mushrooms and cheese sauce" ifadesinde `sauce` da
        dışlanıp SOSLU HER TARİF eleniyordu, oysa kullanıcının istemediği tek
        şey mantarlı peynir sosuydu."""
        terms, _ = extract_exclusions("pasta without mushrooms and cheese sauce")
        assert terms == ["mushrooms", "cheese"]
        assert "sauce" not in terms

    def test_a_term_dropped_by_the_cap_is_not_removed_from_the_text(self):
        """Sınır TOPLAM üzerinden uygulanmalı. Sonradan `terms[:MAX]` ile
        kırpılsaydı fazla terimler yine de sorgudan silinirdi — metin o malzemeyi
        aramayı bırakır, filtre de elemezdi: iki taraflı kayıp."""
        terms, text = extract_exclusions(
            "soup without mushrooms and onions and garlic and celery"
        )
        assert len(terms) == MAX_EXCLUSIONS
        assert "celery" in text.lower()          # kırpılan terim metinde DURUYOR

    def test_skips_filler_words(self):
        assert extract_exclusions("pasta without any mushrooms")[0] == ["mushrooms"]

    def test_is_case_insensitive(self):
        assert extract_exclusions("Pasta WITHOUT Mushrooms")[0] == ["mushrooms"]

    @pytest.mark.parametrize("query", [
        "pasta with mushrooms",
        "creamy mushroom pasta",
        "quick chicken dinner",
    ])
    def test_leaves_ordinary_queries_untouched(self, query):
        """Dışlama yoksa davranış birebir eski hâli olmalı — over-fetch bile
        yapılmıyor (bkz. Katman 2)."""
        assert extract_exclusions(query) == ([], query)

    # ── 🔴 ASIL KORUMA: "no" her zaman bir malzemeyi olumsuzlamıyor ──

    @pytest.mark.parametrize("query", [
        "no bake cookies",
        "no knead bread",
        "no boil lasagna",
        "no churn ice cream",
        "no fail fudge",
        "no fuss dinner",
        "no cook dessert",
        "no roll pie crust",
        "no stir risotto",
    ])
    def test_dish_names_are_not_read_as_exclusions(self, query):
        """Bunlar YEMEK ADI. Sözlük olmasaydı "no bake cookies" sorgusu
        "cookies, bake'siz" diye okunur, "bake" sorgudan atılır ve kullanıcı
        aradığının tam tersini alırdı — düzeltmeye çalıştığımızdan daha kötü
        bir hata. Elle kara liste yalnızca aklımıza gelenleri kapatırdı;
        sözlük veriden geliyor (bkz. ingestion/build_ingredient_vocab.py)."""
        assert extract_exclusions(query) == ([], query)

    def test_qualifier_words_are_not_excluded_even_though_they_are_in_the_vocab(self):
        """"quick" malzeme metinlerinde geçiyor ("quick-cooking oats") ama
        sorguda bir nitelik kelimesi. _NOT_EXCLUDABLE bunu kapatıyor; yoksa
        "quick" sorgudan silinir ve süre niyeti kaybolurdu."""
        terms, text = extract_exclusions("quick dinner without mushrooms")
        assert terms == ["mushrooms"]
        assert "quick" in text

    # ── Son ek biçimi 1: "sugar-free" ──

    @pytest.mark.parametrize("query,term", [
        ("sugar free cake", "sugar"),
        ("egg-free cake", "egg"),
        ("soy free dinner", "soy"),
    ])
    def test_free_suffix(self, query, term):
        assert extract_exclusions(query)[0] == [term]

    def test_free_suffix_removes_the_whole_phrase(self):
        """İlk sürüm yalnızca malzemeyi siliyordu ve embed metni "free cake"
        gibi anlamsız bir kalıntı taşıyordu."""
        _, text = extract_exclusions("egg free cake")
        assert text == "cake"

    # ── Son ek biçimi 2: "-less" ──

    @pytest.mark.parametrize("query,term,expected_text", [
        ("eggless cake", "egg", "cake"),
        ("sugarless cookies", "sugar", "cookies"),
        ("flourless chocolate cake", "flour", "chocolate cake"),
        ("crustless quiche", "crust", "quiche"),
    ])
    def test_less_suffix(self, query, term, expected_text):
        terms, text = extract_exclusions(query)
        assert terms == [term]
        assert text == expected_text

    def test_meatless_is_left_to_the_vegetarian_tag(self):
        """"meat" bir malzeme adı değil, bir KATEGORİ. Ölçüldü: "meatless
        lasagna" sonuçlarının malzemesinde literal "meat" geçmiyor, `ground
        beef` ve `italian sausage` geçiyor — kelime bazlı dışlama 5 sonucun
        4'ünü elemekte başarısızdı. filters.py bunu vejetaryen etiketine
        çeviriyor."""
        assert extract_exclusions("meatless lasagna") == ([], "meatless lasagna")

    @pytest.mark.parametrize("query", [
        "boneless skinless chicken breast",
        "seedless grape salad",
    ])
    def test_ingredient_descriptors_are_not_exclusions(self, query):
        """🔴 "boneless skinless chicken breast" yazan kullanıcı kemik ve deri
        DIŞLAMAK istemiyor, tavuğun cinsini tarif ediyor. İstisna listesi
        tahminle değil korpustan sayılıyor: bu üç kelime malzeme metinlerinde
        geçiyor (boneless 456, skinless 346, seedless 42), diğer `-less`
        kelimeleri yalnızca tarif adlarında."""
        assert extract_exclusions(query) == ([], query)

    @pytest.mark.parametrize("query", [
        "endless summer punch",
        "useless leftovers",
        "unless you like it hot",
        "bless this mess casserole",
    ])
    def test_ordinary_less_words_are_not_exclusions(self, query):
        """İki koruma birden: "unless"/"bless" {3,} sınırının altında kalıp hiç
        eşleşmiyor, "endless"/"useless" eşleşiyor ama gövdeleri sözlükte yok."""
        assert extract_exclusions(query) == ([], query)

    def test_fat_free_is_not_an_ingredient_exclusion(self):
        """"fat free milk" bir MALZEME adı. Dışlama sayılsaydı "fat" içeren
        her tarif elenirdi — üstelik "fat free" yazan tarifler dahil.
        Yağ kısıtı ayrıca filters.py'de zaten var."""
        assert extract_exclusions("fat free milk smoothie") == ([], "fat free milk smoothie")

    @pytest.mark.parametrize("query", [
        "gluten free pasta",
        "dairy free dessert",
        "pasta without gluten",
        "cookies without nuts",
    ])
    def test_allergen_terms_are_left_to_the_curated_diet_tags(self, query):
        """Alerjenler filters.py'nin küratörlü boolean etiketleriyle ele alınıyor
        (ada + kategoriye + malzemeye birlikte bakıyorlar). Burada İKİNCİ KEZ
        uygulanırsa iki farklı kural aynı sorguyu gereksiz yere daraltır."""
        assert extract_exclusions(query) == ([], query)

    # ── Sınır durumları ──

    def test_falls_back_to_the_original_when_nothing_is_left(self):
        """"without mushrooms" → geriye "" kalıyor. Boş metni embed etmek
        anlamsız; filtre yine uygulanıyor, yalnızca embedding orijinal kalıyor."""
        terms, text = extract_exclusions("without mushrooms")
        assert terms == ["mushrooms"]
        assert text == "without mushrooms"

    def test_caps_the_number_of_exclusions(self):
        terms, _ = extract_exclusions(
            "soup without mushrooms and onions and garlic and celery and carrots"
        )
        assert len(terms) <= MAX_EXCLUSIONS

    @pytest.mark.parametrize("query", ["", "   ", None])
    def test_empty_input(self, query):
        terms, text = extract_exclusions(query)
        assert terms == []
        assert text == (query or "")

    def test_unknown_word_after_trigger_is_ignored(self):
        assert extract_exclusions("pasta without zzzzz")[0] == []


# ══════════ Katman 1 — eşleştirme ══════════

class TestExcludedTermsInRecipe:
    def test_finds_the_term_inside_a_longer_ingredient_phrase(self):
        ings = ["boneless skinless chicken breast halves", "olive oil"]
        assert excluded_terms_in_recipe(ings, ["chicken"]) == ["chicken"]

    def test_word_boundary_stops_egg_matching_eggplant(self):
        """Düz alt-dizi araması "egg"i "eggplant" içinde bulur ve yumurtasız kek
        arayan kullanıcıdan patlıcanlı tarifleri saklardı. Aynı tuzağın veri
        tarafındaki hâli: `ham` ⊂ `graham` (Faz 29)."""
        assert excluded_terms_in_recipe(["eggplant", "tomatoes"], ["egg"]) == []

    @pytest.mark.parametrize("ingredient,term", [
        ("mushrooms", "mushroom"),
        ("mushroom", "mushrooms"),
        ("tomatoes", "tomato"),
        ("tomato", "tomatoes"),
    ])
    def test_plural_matches_in_both_directions(self, ingredient, term):
        assert excluded_terms_in_recipe([ingredient], [term]) == [term]

    def test_reports_only_the_terms_that_actually_matched(self):
        ings = ["mushrooms", "cream", "pasta"]
        assert excluded_terms_in_recipe(ings, ["mushrooms", "onions"]) == ["mushrooms"]

    @pytest.mark.parametrize("ings,terms", [([], ["egg"]), (["egg"], []), ([], [])])
    def test_empty_inputs(self, ings, terms):
        assert excluded_terms_in_recipe(ings, terms) == []


class TestFilterExcluded:
    def _card(self, name, ingredients):
        return {"id": name, "name": name, "ingredients": ingredients}

    def test_drops_matching_cards_and_keeps_order(self):
        cards = [
            self._card("a", ["mushrooms", "pasta"]),
            self._card("b", ["pasta", "garlic"]),
            self._card("c", ["cream", "mushroom"]),
            self._card("d", ["tomatoes"]),
        ]
        kept = filter_excluded(cards, ["mushrooms"])
        assert [c["id"] for c in kept] == ["b", "d"]

    def test_no_terms_is_the_identity(self):
        cards = [self._card("a", ["mushrooms"])]
        assert filter_excluded(cards, []) == cards

    def test_a_recipe_without_ingredient_data_survives(self):
        """`ingredients` Faz 17'de eklendi; boşu "kirli" saymak sonucu sebepsiz
        yok etmek olurdu."""
        cards = [self._card("a", [])]
        assert filter_excluded(cards, ["mushrooms"]) == cards


# ══════════ Katman 1.5 — sözlüğün bütünlüğü ══════════

@pytest.fixture(scope="module")
def payload():
    return json.loads(VOCAB_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def vocab(payload):
    return set(payload["words"])


class TestVocabulary:
    """Bu özelliğin EN SESSİZ bozulma biçimi sözlüğün bozulması: eşik değişirse
    ya da dosya yeniden üretilirken bir şey kayarsa arama çalışmaya devam eder,
    yalnızca "no bake cookies" sessizce yanlış yorumlanır."""

    def test_file_is_a_non_trivial_list_of_lowercase_words(self, vocab):
        assert len(vocab) > 300
        assert all(w == w.lower() and w.isalpha() for w in vocab)

    @pytest.mark.parametrize("word", [
        "mushroom", "onion", "egg", "cheese", "butter", "walnut", "peanut",
        "almond", "meat", "pork", "beef", "shrimp", "milk", "cream", "sugar",
        "tomato", "garlic", "coconut", "chicken", "fish", "bacon", "soy",
    ])
    def test_real_ingredients_are_present(self, vocab, word):
        assert word in vocab

    @pytest.mark.parametrize("word", [
        "bake", "knead", "churn", "fuss", "boil", "cook", "fail", "roll", "stir",
    ])
    def test_cooking_verbs_are_absent(self, vocab, word):
        """Bunlar sözlüğe girerse "no bake cookies" bozulur — test_exclusions'ın
        yukarıdaki yemek-adı testleriyle aynı korumanın veri tarafı."""
        assert word not in vocab

    def test_descriptors_are_present_and_loaded(self, payload):
        """Malzeme tarifi olan `-less` kelimeleri. Boş kalırsa "boneless
        skinless chicken breast" sorgusu kemik ve deri dışlamaya başlar."""
        assert set(payload["descriptors"]) == {"boneless", "skinless", "seedless"}
        assert DESCRIPTORS == set(payload["descriptors"])

    def test_no_exclusion_word_leaked_into_descriptors(self, payload):
        """Ters yön: gerçek dışlama iddiaları istisna listesine düşmemeli,
        yoksa "eggless cake" sessizce çalışmaz hâle gelir."""
        for w in ("eggless", "flourless", "meatless", "sugarless", "crustless"):
            assert w not in payload["descriptors"]


class TestNoDriftFromPantryMatcher:
    """exclusions._variants, pantry._variants'ın BİLİNÇLİ kopyası (pantry import
    anında Firestore'a bağlanıyor, saf bir modül ona bağımlı olmamalı —
    nutrition.py'deki aynı gerekçe). Kopya ayrışırsa sessizce farklı eşleşir;
    bu test ayrışmayı kırılmaya çevirir.

    ⚠️ İlk sürüm pantry'nin YANLIŞ kardeşini (`_singularize_word`, dedup anahtarı
    için, `-es` kuralı yok) kopyalamıştı ve "without tomatoes" hiçbir domatesli
    tarifi elemiyordu. O yüzden bu test iki fonksiyonu da kilitliyor."""

    WORDS = ["mushrooms", "tomatoes", "berries", "eggs", "glass", "swiss",
             "onion", "cheese", "cloves", "potatoes", "s", "is"]

    @pytest.mark.parametrize("word", WORDS)
    def test_variants_agree_with_pantry(self, word):
        import exclusions
        import pantry

        assert exclusions._variants(word) == pantry._variants(word)

    @pytest.mark.parametrize("word", WORDS)
    def test_the_matcher_agrees_with_the_pantry_matcher(self, word):
        """Asıl iddia: aynı malzeme metnine karşı ikisi aynı kararı vermeli."""
        import exclusions
        import pantry

        ours = {p.pattern for p in exclusions._term_patterns(word)}
        theirs = {p.pattern for p in pantry._pantry_patterns(word)}
        assert ours == theirs


# ══════════ Katman 2 — endpoint sözleşmesi ══════════

HEADERS = {"authorization": "Bearer token"}


def _query_result(recipes):
    """(name, ingredients) listesinden sahte bir collection.query() yanıtı."""
    meta_base = {
        "category": "Pasta", "total_time_min": 20, "calories": 300.0,
        "protein_content": 10.0, "carbohydrate_content": 30.0, "fat_content": 5.0,
        "image_url": "", "gluten_free": False, "dairy_free": False,
        "nut_free": True, "vegetarian": True, "pescatarian": False, "vegan": False,
    }
    return {
        "documents": [[f"{n} description" for n, _ in recipes]],
        "metadatas": [[{**meta_base, "name": n, "ingredients": "|".join(i)}
                       for n, i in recipes]],
        "ids": [[str(idx) for idx, _ in enumerate(recipes)]],
        "distances": [[0.5] * len(recipes)],
    }


class TestSearchEndpointExclusions:
    def test_the_excluded_term_never_reaches_the_embedding(self, auth_client, collection, monkeypatch, api):
        main, _ = api
        monkeypatch.setattr(main, "is_food_request", lambda q: True)

        auth_client.post("/api/recipes/search",
                         json={"query": "pasta without mushrooms"}, headers=HEADERS)

        assert collection.query.call_args.kwargs["query_texts"] == ["pasta"]

    def test_over_fetches_candidates_when_something_is_excluded(self, auth_client, collection, monkeypatch, api):
        """Eleme yapılacaksa fazladan aday şart: yalnızca 5 çekilseydi elemenin
        ardından 5'ten az sonuç kalırdı ve kullanıcı "arama bozuk" görürdü."""
        main, _ = api
        monkeypatch.setattr(main, "is_food_request", lambda q: True)

        auth_client.post("/api/recipes/search",
                         json={"query": "pasta without mushrooms", "n_results": 5},
                         headers=HEADERS)

        assert collection.query.call_args.kwargs["n_results"] == 20

    def test_no_over_fetch_for_an_ordinary_query(self, auth_client, collection, monkeypatch, api):
        main, _ = api
        monkeypatch.setattr(main, "is_food_request", lambda q: True)

        auth_client.post("/api/recipes/search",
                         json={"query": "creamy mushroom pasta", "n_results": 5},
                         headers=HEADERS)

        assert collection.query.call_args.kwargs["n_results"] == 5
        assert collection.query.call_args.kwargs["query_texts"] == ["creamy mushroom pasta"]

    def test_recipes_containing_the_excluded_ingredient_are_dropped(self, auth_client, collection, monkeypatch, api):
        main, _ = api
        monkeypatch.setattr(main, "is_food_request", lambda q: True)
        collection.query.return_value = _query_result([
            ("Mushroom Pasta for 2", ["portabella mushroom", "penne"]),
            ("Garlic Butter Pasta", ["garlic", "butter", "penne"]),
            ("Creamy Pasta With Mushrooms", ["mushroom", "cream"]),
            ("Tomato Basil Pasta", ["tomatoes", "basil"]),
        ])

        r = auth_client.post("/api/recipes/search",
                             json={"query": "pasta without mushrooms"}, headers=HEADERS)

        names = [c["name"] for c in r.json()["results"]]
        assert names == ["Garlic Butter Pasta", "Tomato Basil Pasta"]

    def test_response_says_what_was_excluded(self, auth_client, collection, monkeypatch, api):
        """Sonuç sayısı sessizce azalabildiği için ne çıkarıldığı söylenmeli."""
        main, _ = api
        monkeypatch.setattr(main, "is_food_request", lambda q: True)

        r = auth_client.post("/api/recipes/search",
                             json={"query": "pasta without mushrooms"}, headers=HEADERS)

        assert r.json()["excluded_ingredients"] == ["mushrooms"]

    def test_ordinary_query_reports_no_exclusions(self, auth_client, collection, monkeypatch, api):
        main, _ = api
        monkeypatch.setattr(main, "is_food_request", lambda q: True)

        r = auth_client.post("/api/recipes/search",
                             json={"query": "creamy mushroom pasta"}, headers=HEADERS)

        assert r.json()["excluded_ingredients"] == []

    def test_metadata_filters_still_come_from_the_original_query(self, auth_client, collection, monkeypatch, api):
        """extract_filters TEMİZLENMİŞ metni değil orijinali görmeli; yoksa
        "quick pasta without mushrooms"ta süre kısıtı kaybolabilirdi."""
        main, _ = api
        monkeypatch.setattr(main, "is_food_request", lambda q: True)

        r = auth_client.post("/api/recipes/search",
                             json={"query": "quick pasta without mushrooms"}, headers=HEADERS)

        assert r.json()["applied_filters"] == {"total_time_min": {"$lte": 30}}

    def test_no_bake_cookies_searches_for_no_bake_cookies(self, auth_client, collection, monkeypatch, api):
        """Uçtan uca regresyon: yemek adı sorgusu hiç dokunulmadan geçmeli."""
        main, _ = api
        monkeypatch.setattr(main, "is_food_request", lambda q: True)

        r = auth_client.post("/api/recipes/search",
                             json={"query": "no bake cookies"}, headers=HEADERS)

        assert collection.query.call_args.kwargs["query_texts"] == ["no bake cookies"]
        assert r.json()["excluded_ingredients"] == []
