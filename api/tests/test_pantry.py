"""Pantry testleri.

Katman 1 — saf fonksiyonlar (validate_ingredient_name, count_pantry_matches,
build_pantry_query): mock yok, veritabanına dokunmuyor. Eşleştirme mantığı
BURADA test ediliyor çünkü rozetin doğruluğu tamamen buna bağlı ve kullanıcıya
görünür bir sayı üretiyor.

Katman 2 — endpoint sözleşmesi (auth, toplu ekleme, boş dolap, rozet bağlantısı).
Firestore CRUD'u birim test EDİLMİYOR (favoriler/koleksiyonlar gibi); main'de
monkeypatch'lenip yalnızca bağlantılar doğrulanıyor.

    python -m pytest api/tests/test_pantry.py -v
"""
from unittest.mock import MagicMock

import pytest

from pantry import (
    validate_ingredient_name,
    count_pantry_matches,
    build_pantry_query,
    MAX_NAME_LENGTH,
    MAX_QUERY_CHARS,
)


# ── Katman 1: isim doğrulama ──────────────────────────────

class TestValidateIngredientName:
    def test_valid_name(self):
        assert validate_ingredient_name("olive oil") == "olive oil"

    def test_trims_whitespace(self):
        assert validate_ingredient_name("  tomato  ") == "tomato"

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            validate_ingredient_name("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError):
            validate_ingredient_name("   ")

    def test_none_raises(self):
        with pytest.raises(ValueError):
            validate_ingredient_name(None)

    def test_at_max_length_ok(self):
        name = "a" * MAX_NAME_LENGTH
        assert validate_ingredient_name(name) == name

    def test_over_max_length_raises(self):
        with pytest.raises(ValueError):
            validate_ingredient_name("a" * (MAX_NAME_LENGTH + 1))


# ── Katman 1: dolap ↔ tarif eşleştirmesi ──────────────────
# Rozetin ("4/6 from pantry") doğruluğu tamamen bu fonksiyona bağlı.
# Gerçek veriden alınmış malzeme ifadeleri kullanılıyor.

class TestCountPantryMatches:
    def test_exact_match(self):
        assert count_pantry_matches(["garlic"], ["garlic", "salt"]) == ["garlic"]

    def test_substring_inside_long_phrase(self):
        # Gerçek veri: "boneless skinless chicken breast halves"
        matched = count_pantry_matches(
            ["chicken"], ["boneless skinless chicken breast halves", "butter"]
        )
        assert matched == ["chicken"]

    def test_multiword_pantry_item(self):
        matched = count_pantry_matches(["olive oil"], ["extra virgin olive oil"])
        assert matched == ["olive oil"]

    def test_singular_pantry_matches_plural_recipe(self):
        assert count_pantry_matches(["tomato"], ["roma tomatoes"]) == ["tomato"]

    def test_plural_pantry_matches_singular_recipe(self):
        # Ters yön de tutmalı — kullanıcı "tomatoes" yazmış olabilir
        assert count_pantry_matches(["tomatoes"], ["tomato sauce"]) == ["tomatoes"]

    def test_ies_plural(self):
        assert count_pantry_matches(["berries"], ["fresh berry"]) == ["berries"]

    def test_word_boundary_prevents_false_positive(self):
        # EN ÖNEMLİ TEST: düz `in` kontrolü "egg"i "eggplant" içinde bulurdu.
        assert count_pantry_matches(["egg"], ["eggplant"]) == []

    def test_no_match(self):
        assert count_pantry_matches(["saffron"], ["flour", "sugar"]) == []

    def test_counts_only_matching_items(self):
        pantry = ["chicken", "tomato", "saffron", "garlic"]
        recipe = ["chicken breast", "roma tomatoes", "olive oil"]
        matched = count_pantry_matches(pantry, recipe)
        assert matched == ["chicken", "tomato"]
        assert len(matched) == 2

    def test_case_insensitive(self):
        assert count_pantry_matches(["Chicken"], ["CHICKEN BREAST"]) == ["Chicken"]

    def test_returns_original_spelling(self):
        # Rozet tooltip'inde kullanıcının yazdığı hâli görmeli
        assert count_pantry_matches(["Olive Oil"], ["extra virgin olive oil"]) == ["Olive Oil"]

    def test_empty_pantry(self):
        assert count_pantry_matches([], ["chicken"]) == []

    def test_empty_recipe_ingredients(self):
        assert count_pantry_matches(["chicken"], []) == []

    def test_blank_entries_ignored(self):
        assert count_pantry_matches(["", "  "], ["chicken"]) == []


# ── Katman 1: sorgu metni kurma ───────────────────────────

class TestBuildPantryQuery:
    def test_joins_names(self):
        assert build_pantry_query(["tomato", "onion"]) == "tomato, onion"

    def test_appends_additional_text(self):
        q = build_pantry_query(["tomato"], "quick dinner")
        assert q == "tomato. quick dinner"

    def test_ignores_blank_additional_text(self):
        assert build_pantry_query(["tomato"], "   ") == "tomato"

    def test_truncates_long_pantry(self):
        # Commentary endpoint'i query'yi 500 karakterle sınırlıyor (Faz 15c);
        # büyük bir dolap o sınırı aşıp 422 aldırırdı.
        names = [f"ingredient number {i}" for i in range(100)]
        q = build_pantry_query(names)
        assert len(q) <= MAX_QUERY_CHARS

    def test_truncation_does_not_cut_mid_item(self):
        names = [f"ingredient number {i}" for i in range(100)]
        q = build_pantry_query(names)
        # Yarım kalmış bir malzeme adıyla bitmemeli
        assert not q.endswith(",")
        assert "ingredient number 0" in q

    def test_limit_includes_additional_text(self):
        # REGRESYON: sınır önce yalnızca malzeme kısmına uygulanıyordu, üstüne
        # 200 karakterlik additional_text ekleniyordu → 586 karakter, commentary
        # 500 sınırını aşıyor ve AI yorumu sessizce 422 alıyordu.
        names = [f"ingredient number {i}" for i in range(100)]
        q = build_pantry_query(names, "a" * 200)   # additional_text üst sınırı
        assert len(q) <= MAX_QUERY_CHARS

    def test_additional_text_survives_truncation(self):
        # Kırpma malzemelerden yapılmalı, kullanıcının notundan değil
        names = [f"ingredient number {i}" for i in range(100)]
        q = build_pantry_query(names, "quick and gluten free")
        assert q.endswith("quick and gluten free")


# ── Katman 2: auth sözleşmesi ─────────────────────────────

class TestPantryAuthContract:
    def test_list_requires_auth(self, client):
        assert client.get("/api/pantry").status_code == 422

    def test_add_requires_auth(self, client):
        assert client.post("/api/pantry", json={"names": ["x"]}).status_code == 422

    def test_from_pantry_requires_auth(self, client):
        assert client.post("/api/recipes/from-pantry", json={}).status_code == 422


# ── Katman 2: ekleme / çıkarma ────────────────────────────

class TestPantryEndpoints:
    def test_add_returns_added_and_items(self, auth_client, api, monkeypatch):
        main, _ = api
        monkeypatch.setattr(
            main, "add_pantry_items",
            MagicMock(return_value={"added": ["tomato"], "skipped": []}),
        )
        monkeypatch.setattr(
            main, "get_pantry",
            MagicMock(return_value=[{"name": "tomato", "added_at": "t"}]),
        )
        r = auth_client.post("/api/pantry", json={"names": ["tomato"]})
        assert r.status_code == 200
        body = r.json()
        assert body["added"] == ["tomato"]
        assert body["items"][0]["name"] == "tomato"

    def test_duplicate_is_skipped_not_error(self, auth_client, api, monkeypatch):
        main, _ = api
        monkeypatch.setattr(
            main, "add_pantry_items",
            MagicMock(return_value={"added": [], "skipped": ["tomato"]}),
        )
        monkeypatch.setattr(main, "get_pantry", MagicMock(return_value=[]))
        r = auth_client.post("/api/pantry", json={"names": ["tomato"]})
        assert r.status_code == 200
        assert "error" not in r.json()          # zaten varsa hata DEĞİL
        assert r.json()["skipped"] == ["tomato"]

    def test_invalid_name_returns_error_not_500(self, auth_client, api, monkeypatch):
        main, _ = api
        monkeypatch.setattr(
            main, "add_pantry_items",
            MagicMock(side_effect=ValueError("Ingredient name can't be empty.")),
        )
        r = auth_client.post("/api/pantry", json={"names": [""]})
        assert r.status_code == 200
        assert "error" in r.json()

    def test_too_many_names_is_422(self, auth_client):
        r = auth_client.post("/api/pantry", json={"names": ["x"] * 51})
        assert r.status_code == 422

    def test_remove_missing_returns_error(self, auth_client, api, monkeypatch):
        main, _ = api
        monkeypatch.setattr(
            main, "remove_pantry_item",
            MagicMock(side_effect=ValueError("This ingredient is not in your pantry.")),
        )
        r = auth_client.delete("/api/pantry?name=saffron")
        assert r.status_code == 200
        assert "not in your pantry" in r.json()["error"]

    def test_clear_all_requires_auth(self, client):
        assert client.delete("/api/pantry/all").status_code == 422

    def test_clear_all_returns_removed_count(self, auth_client, api, monkeypatch):
        main, _ = api
        monkeypatch.setattr(main, "clear_pantry", MagicMock(return_value=11))
        r = auth_client.delete("/api/pantry/all")
        assert r.status_code == 200
        assert r.json()["removed"] == 11

    def test_clear_all_on_empty_pantry(self, auth_client, api, monkeypatch):
        main, _ = api
        monkeypatch.setattr(main, "clear_pantry", MagicMock(return_value=0))
        r = auth_client.delete("/api/pantry/all")
        assert r.status_code == 200
        assert r.json()["removed"] == 0

    def test_clear_all_route_not_treated_as_ingredient_name(self, auth_client, api, monkeypatch):
        # "/api/pantry/all" LİTERAL yol; yanlışlıkla "all" adlı bir malzemeyi
        # silmeye çalışan tekil silme yoluna düşmemeli.
        main, _ = api
        remove = MagicMock()
        monkeypatch.setattr(main, "remove_pantry_item", remove)
        monkeypatch.setattr(main, "clear_pantry", MagicMock(return_value=3))
        auth_client.delete("/api/pantry/all")
        assert not remove.called

    def test_remove_handles_name_with_slash(self, auth_client, api, monkeypatch):
        # REGRESYON: ad YOL parametresiyken "salt/pepper" → ASGI path'i
        # yüzde-çözdüğü için route eşleşmiyor ve 404 dönüyordu.
        main, _ = api
        captured = {}
        monkeypatch.setattr(
            main, "remove_pantry_item",
            lambda email, name: captured.update(name=name),
        )
        r = auth_client.delete("/api/pantry", params={"name": "salt/pepper"})
        assert r.status_code == 200
        assert captured["name"] == "salt/pepper"


# ── Katman 1.5: toplu ekleme mantığı (sahte Firestore) ────
# Kamera akışının kritik yolu. Gerçek Firestore yerine küçük bir sahte doküman
# kullanılıyor — MagicMock anlamlı davranış üretmediği için bu mantık aksi
# hâlde hiç test edilemezdi.

class _FakeSnap:
    def __init__(self, data):
        self._data = data

    @property
    def exists(self):
        return self._data is not None

    def to_dict(self):
        return self._data


class _FakeRef:
    def __init__(self, data=None):
        self._data = data
        self.written = None

    def get(self):
        return _FakeSnap(self._data)

    def set(self, payload, merge=False):
        self.written = payload


class TestAddPantryItemsBulk:
    def _fake_doc(self, monkeypatch, existing=None):
        import pantry as pantry_mod
        ref = _FakeRef({"items": existing} if existing is not None else None)
        monkeypatch.setattr(pantry_mod._pantry, "document", lambda email: ref)
        return ref

    def test_adds_all_new(self, monkeypatch):
        import pantry as pantry_mod
        ref = self._fake_doc(monkeypatch)
        r = pantry_mod.add_pantry_items("u@e.com", ["chicken", "tomato"])
        assert r["added"] == ["chicken", "tomato"]
        assert r["skipped"] == [] and r["invalid"] == []
        assert [i["name"] for i in ref.written["items"]] == ["chicken", "tomato"]

    def test_skips_existing(self, monkeypatch):
        import pantry as pantry_mod
        self._fake_doc(monkeypatch, existing=[{"name": "Chicken", "added_at": "t"}])
        r = pantry_mod.add_pantry_items("u@e.com", ["chicken", "tomato"])
        # Büyük/küçük harf duyarsız dedup
        assert r["added"] == ["tomato"]
        assert r["skipped"] == ["chicken"]

    def test_invalid_names_are_skipped_others_saved(self, monkeypatch):
        # REGRESYON: önce ValueError fırlatılıyordu; kamera 8 malzeme
        # gönderdiğinde Gemini'nin tek tuhaf öğesi yüzünden HİÇBİRİ kaydedilmiyordu.
        import pantry as pantry_mod
        ref = self._fake_doc(monkeypatch)
        r = pantry_mod.add_pantry_items(
            "u@e.com", ["chicken", "", "tomato", "x" * 61]
        )
        assert r["added"] == ["chicken", "tomato"]      # diğerleri KAYDEDİLDİ
        assert len(r["invalid"]) == 2
        assert ref.written is not None

    def test_nothing_written_when_all_invalid(self, monkeypatch):
        import pantry as pantry_mod
        ref = self._fake_doc(monkeypatch)
        r = pantry_mod.add_pantry_items("u@e.com", ["", "   "])
        assert r["added"] == []
        assert len(r["invalid"]) == 2
        assert ref.written is None                      # boşuna yazma yok

    def test_duplicate_within_same_batch(self, monkeypatch):
        import pantry as pantry_mod
        self._fake_doc(monkeypatch)
        r = pantry_mod.add_pantry_items("u@e.com", ["tomato", "Tomato"])
        assert r["added"] == ["tomato"]
        assert r["skipped"] == ["Tomato"]

    def test_clear_pantry_empties_and_counts(self, monkeypatch):
        import pantry as pantry_mod
        ref = self._fake_doc(monkeypatch, existing=[
            {"name": "a", "added_at": "t"}, {"name": "b", "added_at": "t"},
        ])
        assert pantry_mod.clear_pantry("u@e.com") == 2
        assert ref.written == {"items": []}

    def test_clear_pantry_when_no_document(self, monkeypatch):
        import pantry as pantry_mod
        ref = self._fake_doc(monkeypatch)          # doküman hiç yok
        assert pantry_mod.clear_pantry("u@e.com") == 0
        assert ref.written is None                 # boşuna yazma yok


# ── Katman 2: dolaptan arama + rozet bağlantısı ───────────

class TestSearchFromPantry:
    def test_empty_pantry_skips_search(self, auth_client, collection, api, monkeypatch):
        main, _ = api
        monkeypatch.setattr(main, "get_pantry", MagicMock(return_value=[]))
        r = auth_client.post("/api/recipes/from-pantry", json={})
        assert r.status_code == 200
        assert r.json()["results"] == []
        assert "error" in r.json()
        # Boş dolapla ChromaDB'ye HİÇ gidilmemeli
        assert not collection.query.called

    def test_search_uses_server_side_pantry(self, auth_client, collection, api, monkeypatch):
        main, _ = api
        monkeypatch.setattr(
            main, "get_pantry",
            MagicMock(return_value=[{"name": "chicken", "added_at": "t"}]),
        )
        r = auth_client.post("/api/recipes/from-pantry", json={})
        assert r.status_code == 200
        body = r.json()
        assert body["pantry_items"] == ["chicken"]
        assert "chicken" in body["combined_query"]
        assert collection.query.called

    def test_results_carry_pantry_match_badge(self, auth_client, collection, api, monkeypatch):
        main, _ = api
        # conftest'teki sahte tarifin malzemeleri:
        #   "chicken breast|tomatoes|olive oil|garlic"
        monkeypatch.setattr(
            main, "get_pantry",
            MagicMock(return_value=[
                {"name": "chicken", "added_at": "t"},
                {"name": "tomato", "added_at": "t"},
                {"name": "saffron", "added_at": "t"},
            ]),
        )
        r = auth_client.post("/api/recipes/from-pantry", json={})
        card = r.json()["results"][0]
        assert card["pantry_match"]["count"] == 2          # chicken + tomato
        assert card["pantry_match"]["pantry_total"] == 3
        assert "saffron" not in card["pantry_match"]["matched"]

    def test_classifier_not_called(self, auth_client, api, monkeypatch):
        # Dolaptakiler zaten yemek — is_food_request çalıştırılmamalı
        # (from-image'daki gerekçe; boşa Gemini çağrısı yok).
        main, _ = api
        classifier = MagicMock(return_value=True)
        monkeypatch.setattr(main, "is_food_request", classifier)
        monkeypatch.setattr(
            main, "get_pantry",
            MagicMock(return_value=[{"name": "chicken", "added_at": "t"}]),
        )
        auth_client.post("/api/recipes/from-pantry", json={})
        assert not classifier.called

    def test_additional_text_too_long_is_422(self, auth_client):
        r = auth_client.post(
            "/api/recipes/from-pantry", json={"additional_text": "a" * 201}
        )
        assert r.status_code == 422


# ── Katman 2: eşleşmeye göre sıralama ─────────────────────
# Kullanıcı bildirimi: 8/11 eşleşen tarif, 4/11 eşleşenin ALTINDA görünüyordu.
# Bu modda alaka ölçüsü eşleşme sayısı olmalı.

def _multi_recipe_query(specs):
    """specs: [(id, name, ingredients_str)] → sahte collection.query yanıtı."""
    base = {
        "category": "Test", "total_time_min": 20, "calories": 300.0,
        "protein_content": 1.0, "carbohydrate_content": 1.0, "fat_content": 1.0,
        "instructions": "1. Cook.", "gluten_free": True, "dairy_free": True,
        "nut_free": True, "vegetarian": False, "pescatarian": False, "vegan": False,
    }
    return {
        "documents": [[f"{n} description" for _, n, _ in specs]],
        "metadatas": [[{**base, "name": n, "ingredients": ing} for _, n, ing in specs]],
        "ids": [[i for i, _, _ in specs]],
    }


class TestPantryResultOrdering:
    def _pantry(self, monkeypatch, api, names):
        main, _ = api
        monkeypatch.setattr(
            main, "get_pantry",
            MagicMock(return_value=[{"name": n, "added_at": "t"} for n in names]),
        )

    def test_most_matches_first(self, auth_client, collection, api, monkeypatch):
        self._pantry(monkeypatch, api, ["beef", "carrots", "onions", "potatoes"])
        # Semantik sıra bilerek TERS: az eşleşen başta geliyor
        collection.query.return_value = _multi_recipe_query([
            ("1", "Few matches", "flour|sugar|carrots"),                  # 1
            ("2", "Many matches", "beef|carrots|onions|potatoes"),        # 4
            ("3", "Some matches", "beef|onions"),                         # 2
        ])
        r = auth_client.post("/api/recipes/from-pantry", json={})
        results = r.json()["results"]
        counts = [c["pantry_match"]["count"] for c in results]
        assert counts == [4, 2, 1]
        assert results[0]["name"] == "Many matches"

    def test_ties_keep_semantic_order(self, auth_client, collection, api, monkeypatch):
        # Eşleşme ayırt etmiyorsa vektör benzerliği karar vermeli (stable sort)
        self._pantry(monkeypatch, api, ["beef"])
        collection.query.return_value = _multi_recipe_query([
            ("1", "Closer", "beef|flour"),
            ("2", "Further", "beef|sugar"),
        ])
        r = auth_client.post("/api/recipes/from-pantry", json={})
        names = [c["name"] for c in r.json()["results"]]
        assert names == ["Closer", "Further"]

    def test_overfetches_candidates(self, auth_client, collection, api, monkeypatch):
        # Yalnızca n_results kadar çekilseydi sıralama elimizdeki 5'i
        # karıştırmaktan ibaret kalırdı; yüksek eşleşmeli ama semantik olarak
        # geride kalan tarifler hiç görünmezdi.
        self._pantry(monkeypatch, api, ["beef"])
        auth_client.post("/api/recipes/from-pantry", json={"n_results": 5})
        assert collection.query.call_args.kwargs["n_results"] > 5

    def test_trims_to_requested_count(self, auth_client, collection, api, monkeypatch):
        self._pantry(monkeypatch, api, ["beef"])
        collection.query.return_value = _multi_recipe_query([
            (str(i), f"Recipe {i}", "beef") for i in range(10)
        ])
        r = auth_client.post("/api/recipes/from-pantry", json={"n_results": 3})
        assert len(r.json()["results"]) == 3


# ── Katman 2: kartlarda/detayda ingredients ───────────────

class TestIngredientsExposed:
    def test_card_has_ingredients(self, auth_client, collection, api, monkeypatch):
        # `collection` fixture'ı ŞART: sahte koleksiyonun dönüş değerini
        # sıfırlıyor. İstenmezse önceki testin bıraktığı veri okunur.
        main, _ = api
        monkeypatch.setattr(main, "is_food_request", lambda q: True)
        r = auth_client.post("/api/recipes/search", json={"query": "chicken"})
        card = r.json()["results"][0]
        assert card["ingredients"] == ["chicken breast", "tomatoes", "olive oil", "garlic"]

    def test_detail_has_ingredients(self, auth_client, collection):
        r = auth_client.get("/api/recipes/17450")
        assert r.json()["ingredients"] == ["chicken breast", "tomatoes", "olive oil", "garlic"]

    def test_missing_ingredients_field_is_empty_list(self, auth_client, collection):
        # Eski veriyle (ingredients alanı olmayan) patlamamalı
        meta = dict(collection.get.return_value["metadatas"][0])
        meta.pop("ingredients")
        collection.get.return_value = {
            "documents": ["d"], "metadatas": [meta], "ids": ["17450"],
        }
        r = auth_client.get("/api/recipes/17450")
        assert r.json()["ingredients"] == []
