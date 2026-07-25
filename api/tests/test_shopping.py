"""Shopping list testleri.

Katman 1 — saf fonksiyonlar (missing_ingredients, build_list) + paylaşılan
eşleştirici (pantry.ingredient_in_pantry). Rozet ↔ liste TUTARLILIĞI burada
kilitleniyor: dolapta olan bir malzeme listede istenmemeli.

Katman 1.5 — overlay Firestore yazma mantığı (sahte doküman): check toggle,
custom ekleme/çıkarma.

Katman 2 — endpoint sözleşmesi (auth, boş plan, dolap çıkarması bağlı,
normalize, custom '/' içeren ad).

    python -m pytest api/tests/test_shopping.py -v
"""
from unittest.mock import MagicMock

import pytest

from pantry import ingredient_in_pantry, canonical_ingredient
from shopping import (
    aggregate_ingredients,
    missing_ingredients,
    build_list,
)


# ── Katman 1: çoğul-duyarlı kanonik anahtar ───────────────

class TestCanonicalIngredient:
    def test_singular_plural_collapse(self):
        # Asıl neden: bazı tarifler aynı malzemenin tekil+çoğulunu içeriyor
        assert canonical_ingredient("garlic clove") == canonical_ingredient("garlic cloves")

    def test_common_plurals(self):
        assert canonical_ingredient("eggs") == "egg"
        assert canonical_ingredient("onions") == "onion"
        assert canonical_ingredient("berries") == "berry"          # -ies → -y

    def test_double_s_not_stripped(self):
        # "swiss"/"glass" çoğul değil — ss guard
        assert canonical_ingredient("swiss cheese") == "swiss cheese"

    def test_lowercases_and_trims(self):
        assert canonical_ingredient("  Garlic Cloves ") == "garlic clove"

    def test_empty(self):
        assert canonical_ingredient("") == ""


# ── Katman 1: paylaşılan eşleştirici (rozet ↔ liste tek kaynak) ──

class TestIngredientInPantry:
    def test_exact_word(self):
        assert ingredient_in_pantry("garlic", ["garlic"]) is True

    def test_subphrase_match(self):
        # Dolapta "chicken", tarifte uzun ifade → kapsanıyor
        assert ingredient_in_pantry("boneless skinless chicken breast halves", ["chicken"]) is True

    def test_word_boundary_prevents_partial(self):
        # "egg" ≠ "eggplant" (kelime sınırı) — rozetteki kuralın aynısı
        assert ingredient_in_pantry("eggplant", ["egg"]) is False

    def test_plural_both_directions(self):
        assert ingredient_in_pantry("tomatoes", ["tomato"]) is True
        assert ingredient_in_pantry("tomato", ["tomatoes"]) is True

    def test_not_in_pantry(self):
        assert ingredient_in_pantry("saffron", ["chicken", "garlic"]) is False

    def test_empty_pantry(self):
        assert ingredient_in_pantry("garlic", []) is False

    def test_empty_ingredient(self):
        assert ingredient_in_pantry("", ["garlic"]) is False


# ── Katman 1: malzeme toplama / eksik hesabı ──────────────

def _recipe(name, ingredients):
    return {"recipe_id": name, "name": name, "ingredients": ingredients}


class TestAggregateIngredients:
    def test_dedup_across_recipes(self):
        planned = [
            _recipe("A", ["olive oil", "garlic"]),
            _recipe("B", ["olive oil", "onion"]),
        ]
        agg = aggregate_ingredients(planned)
        assert set(agg.keys()) == {"olive oil", "garlic", "onion"}

    def test_tracks_source_recipes(self):
        planned = [
            _recipe("A", ["olive oil"]),
            _recipe("B", ["olive oil"]),
        ]
        agg = aggregate_ingredients(planned)
        assert agg["olive oil"]["from_recipes"] == ["A", "B"]

    def test_keeps_first_original_spelling(self):
        planned = [_recipe("A", ["Olive Oil"]), _recipe("B", ["olive oil"])]
        agg = aggregate_ingredients(planned)
        assert agg["olive oil"]["name"] == "Olive Oil"   # ilk yazım korunuyor

    def test_merges_singular_and_plural_in_one_recipe(self):
        # Gerçek dataset kusuru: tek tarif hem "garlic clove" hem "garlic cloves"
        # içeriyordu. Çoğul-duyarlı dedup ikisini TEK satıra indiriyor.
        planned = [_recipe("A", ["garlic clove", "garlic cloves", "onion", "onions"])]
        agg = aggregate_ingredients(planned)
        assert len(agg) == 2                              # 4 girdi → 2 satır
        names = [v["name"] for v in agg.values()]
        assert names == ["garlic clove", "onion"]         # ilk görülen yazım

    def test_skips_blank(self):
        agg = aggregate_ingredients([_recipe("A", ["", "  ", "garlic"])])
        assert list(agg.keys()) == ["garlic"]

    def test_empty(self):
        assert aggregate_ingredients([]) == {}


class TestMissingIngredients:
    def test_subtracts_pantry(self):
        planned = [_recipe("A", ["chicken breast", "tomatoes", "saffron"])]
        missing = missing_ingredients(planned, ["chicken", "tomato"])
        names = [m["name"] for m in missing]
        assert names == ["saffron"]          # chicken/tomato dolapta → düşer

    def test_nothing_in_pantry_returns_all(self):
        planned = [_recipe("A", ["garlic", "onion"])]
        missing = missing_ingredients(planned, [])
        assert [m["name"] for m in missing] == ["garlic", "onion"]

    def test_all_covered_returns_empty(self):
        planned = [_recipe("A", ["garlic", "onion"])]
        assert missing_ingredients(planned, ["garlic", "onion"]) == []

    def test_badge_consistency(self):
        # Rozet "2/3 var" diyorsa (garlic+onion), liste tam olarak diğer 1'i
        # (flour) istemeli — ikisi de ingredient_in_pantry kullandığı için.
        from pantry import count_pantry_matches
        ingredients = ["garlic", "onion", "flour"]
        pantry = ["garlic", "onion"]
        matched = count_pantry_matches(pantry, ingredients)   # rozet: 2
        missing = [m["name"] for m in missing_ingredients([_recipe("A", ingredients)], pantry)]
        assert len(matched) == 2
        assert missing == ["flour"]          # 3 − 2 = tam olarak flour


# ── Katman 1: overlay birleştirme ─────────────────────────

class TestBuildList:
    def test_derived_items_pass_through(self):
        derived = [{"name": "garlic", "from_recipes": ["A"]}]
        out = build_list(derived, [], [])
        assert out[0]["name"] == "garlic"
        assert out[0]["source"] == "recipe"
        assert out[0]["checked"] is False

    def test_checked_applied_case_insensitive(self):
        derived = [{"name": "Garlic", "from_recipes": []}]
        out = build_list(derived, ["garlic"], [])
        assert out[0]["checked"] is True

    def test_custom_items_appended(self):
        out = build_list([], [], [{"name": "dish soap"}])
        assert out[0]["name"] == "dish soap"
        assert out[0]["source"] == "custom"

    def test_custom_duplicate_of_derived_is_skipped(self):
        # Kullanıcı hem plandan gelen hem elle "garlic" eklerse tek satır
        derived = [{"name": "garlic", "from_recipes": ["A"]}]
        out = build_list(derived, [], [{"name": "Garlic"}])
        assert len(out) == 1
        assert out[0]["source"] == "recipe"

    def test_stale_checked_name_is_harmless(self):
        # Plan değişip malzeme listeden düştüyse, kalan işaret sadece yok sayılır
        out = build_list([{"name": "garlic", "from_recipes": []}], ["tomatoes"], [])
        assert out[0]["checked"] is False    # bayat "tomatoes" işareti bir şey bozmuyor

    def test_custom_can_be_checked(self):
        out = build_list([], ["dish soap"], [{"name": "dish soap"}])
        assert out[0]["checked"] is True

    def test_custom_as_plain_strings(self):
        out = build_list([], [], ["napkins"])
        assert out[0]["name"] == "napkins"


# ── Katman 1.5: overlay Firestore yazma (sahte doküman) ───

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
        self._data = {**(self._data or {}), **payload}


class TestSetCheckedStorage:
    def _fake_doc(self, monkeypatch, existing=None):
        import shopping as sh
        ref = _FakeRef(existing)
        monkeypatch.setattr(sh._shopping, "document", lambda doc_id: ref)
        return ref

    def test_check_adds_name(self, monkeypatch):
        import shopping as sh
        ref = self._fake_doc(monkeypatch)
        sh.set_checked("u@e.com", "2026-07-27", "garlic", True)
        assert ref.written["checked"] == ["garlic"]

    def test_uncheck_removes_name(self, monkeypatch):
        import shopping as sh
        ref = self._fake_doc(monkeypatch, existing={"checked": ["garlic", "onion"]})
        sh.set_checked("u@e.com", "2026-07-27", "garlic", False)
        assert ref.written["checked"] == ["onion"]

    def test_check_idempotent_no_write(self, monkeypatch):
        import shopping as sh
        ref = self._fake_doc(monkeypatch, existing={"checked": ["garlic"]})
        sh.set_checked("u@e.com", "2026-07-27", "garlic", True)   # zaten işaretli
        assert ref.written is None                                 # boşuna yazma yok

    def test_writes_owner_and_week(self, monkeypatch):
        import shopping as sh
        ref = self._fake_doc(monkeypatch)
        sh.set_checked("u@e.com", "2026-07-27", "garlic", True)
        assert ref.written["owner_email"] == "u@e.com"
        assert ref.written["week_start"] == "2026-07-27"

    def test_empty_name_raises(self, monkeypatch):
        import shopping as sh
        self._fake_doc(monkeypatch)
        with pytest.raises(ValueError):
            sh.set_checked("u@e.com", "2026-07-27", "  ", True)


class TestCustomStorage:
    def _fake_doc(self, monkeypatch, existing=None):
        import shopping as sh
        ref = _FakeRef(existing)
        monkeypatch.setattr(sh._shopping, "document", lambda doc_id: ref)
        return ref

    def test_add_custom(self, monkeypatch):
        import shopping as sh
        ref = self._fake_doc(monkeypatch)
        r = sh.add_custom("u@e.com", "2026-07-27", "dish soap")
        assert r["added"] == "dish soap"
        assert ref.written["custom"][0]["name"] == "dish soap"

    def test_add_custom_duplicate_skipped(self, monkeypatch):
        import shopping as sh
        ref = self._fake_doc(monkeypatch, existing={"custom": [{"name": "Dish Soap", "added_at": "t"}]})
        r = sh.add_custom("u@e.com", "2026-07-27", "dish soap")   # büyük/küçük harf
        assert r["skipped"] == "dish soap" and r["added"] is None
        assert ref.written is None            # duplike → yazma yok

    def test_add_custom_invalid_raises(self, monkeypatch):
        import shopping as sh
        self._fake_doc(monkeypatch)
        with pytest.raises(ValueError):
            sh.add_custom("u@e.com", "2026-07-27", "")

    def test_remove_custom(self, monkeypatch):
        import shopping as sh
        ref = self._fake_doc(monkeypatch, existing={"custom": [
            {"name": "dish soap", "added_at": "t"},
            {"name": "napkins", "added_at": "t"},
        ]})
        sh.remove_custom("u@e.com", "2026-07-27", "dish soap")
        assert [c["name"] for c in ref.written["custom"]] == ["napkins"]

    def test_remove_missing_raises(self, monkeypatch):
        import shopping as sh
        self._fake_doc(monkeypatch, existing={"custom": []})
        with pytest.raises(ValueError):
            sh.remove_custom("u@e.com", "2026-07-27", "dish soap")

    def test_remove_from_missing_doc_raises(self, monkeypatch):
        import shopping as sh
        self._fake_doc(monkeypatch)   # doküman yok
        with pytest.raises(ValueError):
            sh.remove_custom("u@e.com", "2026-07-27", "dish soap")


# ── Katman 2: auth sözleşmesi ─────────────────────────────

class TestShoppingAuthContract:
    def test_get_requires_auth(self, client):
        assert client.get("/api/shopping-list?week=2026-07-27").status_code == 422

    def test_check_requires_auth(self, client):
        r = client.post("/api/shopping-list/check", json={
            "week": "2026-07-27", "name": "garlic", "checked": True,
        })
        assert r.status_code == 422

    def test_custom_add_requires_auth(self, client):
        r = client.post("/api/shopping-list/custom", json={"week": "2026-07-27", "name": "soap"})
        assert r.status_code == 422

    def test_custom_delete_requires_auth(self, client):
        r = client.delete("/api/shopping-list/custom?week=2026-07-27&name=soap")
        assert r.status_code == 422


# ── Katman 2: liste hesabı endpoint'i ─────────────────────

class TestGetShoppingListEndpoint:
    def test_empty_plan_no_chromadb(self, auth_client, api, collection, monkeypatch):
        main, _ = api
        monkeypatch.setattr(main, "get_week", MagicMock(return_value=[]))
        monkeypatch.setattr(main, "get_pantry", MagicMock(return_value=[]))
        monkeypatch.setattr(main, "get_overlay", MagicMock(return_value={"checked": [], "custom": []}))
        r = auth_client.get("/api/shopping-list?week=2026-07-27")
        assert r.status_code == 200
        assert r.json()["items"] == []
        assert r.json()["recipe_count"] == 0
        assert not collection.get.called          # boş plan → ChromaDB'ye gidilmiyor

    def test_computes_missing_minus_pantry(self, auth_client, api, collection, monkeypatch):
        # conftest meta ingredients: chicken breast|tomatoes|olive oil|garlic
        main, _ = api
        monkeypatch.setattr(main, "get_week", MagicMock(return_value=[
            {"date": "2026-07-27", "slot": "dinner", "recipe_id": "17450"},
        ]))
        monkeypatch.setattr(main, "get_pantry", MagicMock(return_value=[{"name": "chicken"}]))
        monkeypatch.setattr(main, "get_overlay", MagicMock(return_value={"checked": [], "custom": []}))
        r = auth_client.get("/api/shopping-list?week=2026-07-27")
        names = [i["name"] for i in r.json()["items"]]
        # "chicken breast" dolapta (chicken) → düşer; kalanlar kalır
        assert "chicken breast" not in names
        assert "tomatoes" in names and "olive oil" in names and "garlic" in names

    def test_overlay_checked_applied(self, auth_client, api, collection, monkeypatch):
        main, _ = api
        monkeypatch.setattr(main, "get_week", MagicMock(return_value=[
            {"date": "2026-07-27", "slot": "dinner", "recipe_id": "17450"},
        ]))
        monkeypatch.setattr(main, "get_pantry", MagicMock(return_value=[]))
        monkeypatch.setattr(main, "get_overlay",
                            MagicMock(return_value={"checked": ["garlic"], "custom": [{"name": "soap"}]}))
        r = auth_client.get("/api/shopping-list?week=2026-07-27")
        by_name = {i["name"]: i for i in r.json()["items"]}
        assert by_name["garlic"]["checked"] is True
        assert by_name["soap"]["source"] == "custom"

    def test_deleted_recipe_skipped(self, auth_client, api, collection, monkeypatch):
        main, _ = api
        monkeypatch.setattr(main, "get_week", MagicMock(return_value=[
            {"date": "2026-07-27", "slot": "dinner", "recipe_id": "99999"},
        ]))
        monkeypatch.setattr(main, "get_pantry", MagicMock(return_value=[]))
        monkeypatch.setattr(main, "get_overlay", MagicMock(return_value={"checked": [], "custom": []}))
        collection.get.return_value = {"documents": [], "metadatas": [], "ids": []}
        r = auth_client.get("/api/shopping-list?week=2026-07-27")
        assert r.status_code == 200
        assert r.json()["items"] == []       # silinmiş tarif → patlamıyor

    def test_week_normalized(self, auth_client, api, monkeypatch):
        main, _ = api
        get_week = MagicMock(return_value=[])
        monkeypatch.setattr(main, "get_week", get_week)
        monkeypatch.setattr(main, "get_pantry", MagicMock(return_value=[]))
        monkeypatch.setattr(main, "get_overlay", MagicMock(return_value={"checked": [], "custom": []}))
        r = auth_client.get("/api/shopping-list?week=2026-07-30")   # perşembe
        assert get_week.call_args.args[1] == "2026-07-27"
        assert r.json()["week_start"] == "2026-07-27"

    def test_invalid_week_returns_error(self, auth_client, api, monkeypatch):
        main, _ = api
        get_week = MagicMock()
        monkeypatch.setattr(main, "get_week", get_week)
        r = auth_client.get("/api/shopping-list?week=nope")
        assert "error" in r.json()
        assert not get_week.called            # doğrulama başarısız → hiç iş yok


# ── Katman 2: check / custom endpoint'leri ────────────────

class TestShoppingMutationEndpoints:
    def test_check_toggle(self, auth_client, api, monkeypatch):
        main, _ = api
        set_checked = MagicMock()
        monkeypatch.setattr(main, "shopping_set_checked", set_checked)
        r = auth_client.post("/api/shopping-list/check", json={
            "week": "2026-07-30", "name": "garlic", "checked": True,
        })
        assert r.status_code == 200
        # week normalize edilmiş halde geçiyor
        assert set_checked.call_args.args[1:] == ("2026-07-27", "garlic", True)

    def test_custom_add(self, auth_client, api, monkeypatch):
        main, _ = api
        monkeypatch.setattr(main, "shopping_add_custom",
                            MagicMock(return_value={"added": "soap", "skipped": None}))
        r = auth_client.post("/api/shopping-list/custom", json={"week": "2026-07-27", "name": "soap"})
        assert r.status_code == 200
        assert r.json()["added"] == "soap"

    def test_custom_add_invalid_returns_error(self, auth_client, api, monkeypatch):
        main, _ = api
        monkeypatch.setattr(main, "shopping_add_custom",
                            MagicMock(side_effect=ValueError("Ingredient name can't be empty.")))
        r = auth_client.post("/api/shopping-list/custom", json={"week": "2026-07-27", "name": " "})
        assert r.status_code == 200
        assert "error" in r.json()

    def test_custom_remove_handles_slash(self, auth_client, api, monkeypatch):
        # REGRESYON güvencesi: ad SORGU parametresi, "salt/pepper" çözülüyor
        main, _ = api
        captured = {}
        monkeypatch.setattr(main, "shopping_remove_custom",
                            lambda email, week, name: captured.update(name=name))
        r = auth_client.delete("/api/shopping-list/custom", params={
            "week": "2026-07-27", "name": "salt/pepper",
        })
        assert r.status_code == 200
        assert captured["name"] == "salt/pepper"

    def test_custom_remove_missing_returns_error(self, auth_client, api, monkeypatch):
        main, _ = api
        monkeypatch.setattr(main, "shopping_remove_custom",
                            MagicMock(side_effect=ValueError("That item is not on your list.")))
        r = auth_client.delete("/api/shopping-list/custom?week=2026-07-27&name=soap")
        assert r.status_code == 200
        assert "not on your list" in r.json()["error"]

    def test_check_name_too_long_is_422(self, auth_client):
        r = auth_client.post("/api/shopping-list/check", json={
            "week": "2026-07-27", "name": "x" * 121, "checked": True,
        })
        assert r.status_code == 422
