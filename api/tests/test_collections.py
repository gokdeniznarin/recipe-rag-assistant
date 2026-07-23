"""Koleksiyonlar için testler.

Katman 1 — validate_collection_name saf fonksiyonu (mock yok, veritabanına
dokunmuyor). Katman 2 — collection endpoint'lerinin HTTP sözleşmesi (auth,
biçim doğrulama, ilişki kuralı bağlantısı). Kurulum conftest.py'de.

    python -m pytest api/tests/test_collections.py -v

Not: is_food_request / generate_answer gibi collections_store'un Firestore'a
dokunan fonksiyonlarının kendi doğruluğu burada test EDİLMİYOR (MagicMock
Firestore anlamlı davranış üretmez); onlar main'de monkeypatch'lenip yalnızca
BAĞLANTILARI doğrulanıyor — favorilerin de contract testi olmamasıyla tutarlı.
"""
from unittest.mock import MagicMock

import pytest

# conftest import-anı mock'larını kurduğu için collections_store güvenle import
# edilebilir (firestore.client() burada MagicMock döner; validate saf zaten).
from collections_store import validate_collection_name, MAX_NAME_LENGTH


# ── Katman 1: validate_collection_name (saf) ──────────────

class TestValidateCollectionName:
    def test_valid_name_returned(self):
        assert validate_collection_name("Breakfast") == "Breakfast"

    def test_trims_surrounding_whitespace(self):
        assert validate_collection_name("  Guests  ") == "Guests"

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            validate_collection_name("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError):
            validate_collection_name("   ")

    def test_none_raises(self):
        # Pydantic normalde str garantiliyor ama fonksiyon kendi başına da sağlam
        with pytest.raises(ValueError):
            validate_collection_name(None)

    def test_at_max_length_ok(self):
        name = "a" * MAX_NAME_LENGTH
        assert validate_collection_name(name) == name

    def test_over_max_length_raises(self):
        with pytest.raises(ValueError):
            validate_collection_name("a" * (MAX_NAME_LENGTH + 1))

    def test_length_measured_after_trim(self):
        # 60 harf + baştan/sondan boşluk → trim sonrası tam sınırda, geçmeli
        name = "  " + "a" * MAX_NAME_LENGTH + "  "
        assert validate_collection_name(name) == "a" * MAX_NAME_LENGTH

    def test_unicode_name_ok(self):
        # Türkçe/aksanlı adlar geçmeli (isalpha Unicode farkında değil ama burada
        # sadece uzunluk/boşluk kuralı var — özel karakter yasağı yok)
        assert validate_collection_name("Kahvaltılıklar") == "Kahvaltılıklar"


# ── Katman 2: auth sözleşmesi ─────────────────────────────
# collection endpoint'lerinin hepsi korumalı. `client` auth'u BYPASS ETMİYOR;
# header yoksa endpoint gövdesi hiç çalışmadan 422 (favori/arama ile aynı).

class TestCollectionsAuthContract:
    def test_create_requires_auth(self, client):
        assert client.post("/api/collections", json={"name": "x"}).status_code == 422

    def test_list_requires_auth(self, client):
        assert client.get("/api/collections").status_code == 422

    def test_detail_requires_auth(self, client):
        assert client.get("/api/collections/abc").status_code == 422

    def test_add_recipe_requires_auth(self, client):
        r = client.post("/api/collections/abc/recipes", json={"recipe_id": "1"})
        assert r.status_code == 422


# ── Katman 2: create + biçim doğrulama ────────────────────

class TestCreateCollection:
    def test_create_success_returns_collection(self, auth_client, api, monkeypatch):
        main, _ = api
        made = {"id": "c1", "name": "Breakfast", "recipe_ids": [], "created_at": "t"}
        monkeypatch.setattr(main, "create_collection", MagicMock(return_value=made))
        r = auth_client.post("/api/collections", json={"name": "Breakfast"})
        assert r.status_code == 200
        assert r.json() == made

    def test_duplicate_name_returns_error_not_500(self, auth_client, api, monkeypatch):
        main, _ = api
        monkeypatch.setattr(
            main, "create_collection",
            MagicMock(side_effect=ValueError("You already have a collection with this name.")),
        )
        r = auth_client.post("/api/collections", json={"name": "Breakfast"})
        assert r.status_code == 200                      # 500 DEĞİL
        assert "already have" in r.json()["error"]

    def test_empty_name_rejected_before_firestore(self, auth_client):
        # create_collection MONKEYPATCH'LENMEDİ: gerçek fonksiyon çalışıyor ama
        # validate_collection_name boş adı Firestore'a HİÇ gitmeden eliyor.
        r = auth_client.post("/api/collections", json={"name": "   "})
        assert r.status_code == 200
        assert "empty" in r.json()["error"].lower()

    def test_too_long_name_rejected_before_firestore(self, auth_client):
        # 61 harf: Pydantic'i (max 200) geçer, validate 60 sınırında reddeder.
        r = auth_client.post("/api/collections", json={"name": "a" * 61})
        assert r.status_code == 200
        assert "too long" in r.json()["error"].lower()

    def test_absurd_length_is_422(self, auth_client):
        # Pydantic max_length=200: devasa gövde daha JSON mantığına girmeden 422.
        r = auth_client.post("/api/collections", json={"name": "a" * 201})
        assert r.status_code == 422


# ── Katman 2: detay + include_details ─────────────────────

class TestCollectionDetail:
    def test_detail_maps_recipe_cards_in_order(self, auth_client, collection, api, monkeypatch):
        main, _ = api
        monkeypatch.setattr(
            main, "get_collection_detail",
            MagicMock(return_value={
                "id": "c1", "name": "Breakfast",
                "recipe_ids": ["17450"], "created_at": "t",
            }),
        )
        r = auth_client.get("/api/collections/c1?include_details=true")
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "Breakfast"
        assert len(body["recipes"]) == 1
        assert body["recipes"][0]["id"] == "17450"
        assert collection.get.called

    def test_detail_not_found_returns_error(self, auth_client, api, monkeypatch):
        main, _ = api
        monkeypatch.setattr(
            main, "get_collection_detail",
            MagicMock(side_effect=ValueError("Collection not found.")),
        )
        r = auth_client.get("/api/collections/missing")
        assert r.status_code == 200
        assert "not found" in r.json()["error"].lower()

    def test_empty_collection_skips_chromadb(self, auth_client, collection, api, monkeypatch):
        main, _ = api
        monkeypatch.setattr(
            main, "get_collection_detail",
            MagicMock(return_value={
                "id": "c1", "name": "Empty", "recipe_ids": [], "created_at": "t",
            }),
        )
        r = auth_client.get("/api/collections/c1?include_details=true")
        assert r.status_code == 200
        assert r.json()["recipes"] == []
        assert not collection.get.called            # boş → ChromaDB'ye gidilmez


# ── Katman 2: ilişki kuralı (auto-favorite + zincir temizliği) ──

class TestRelationshipRules:
    def test_add_to_collection_also_favorites(self, auth_client, api, monkeypatch):
        main, _ = api
        monkeypatch.setattr(main, "add_recipe_to_collection", MagicMock())
        fav = MagicMock()
        monkeypatch.setattr(main, "add_favorite", fav)
        r = auth_client.post("/api/collections/c1/recipes", json={"recipe_id": "17450"})
        assert r.status_code == 200
        # Kritik: koleksiyona ekleme favoriye de eklemeli
        fav.assert_called_once_with("test@example.com", "17450")

    def test_add_when_already_favorite_is_swallowed(self, auth_client, api, monkeypatch):
        main, _ = api
        monkeypatch.setattr(main, "add_recipe_to_collection", MagicMock())
        # add_favorite "zaten favoride" diye ValueError atıyor — yutulmalı, 500 olmamalı
        monkeypatch.setattr(
            main, "add_favorite",
            MagicMock(side_effect=ValueError("This recipe is already in favorites.")),
        )
        r = auth_client.post("/api/collections/c1/recipes", json={"recipe_id": "17450"})
        assert r.status_code == 200
        assert "error" not in r.json()

    def test_remove_favorite_clears_collections(self, auth_client, api, monkeypatch):
        main, _ = api
        monkeypatch.setattr(main, "remove_favorite", MagicMock())
        clear = MagicMock()
        monkeypatch.setattr(main, "remove_recipe_from_all_collections", clear)
        r = auth_client.delete("/api/favorites/17450")
        assert r.status_code == 200
        # İlişki kuralı: favoriden çıkan tarif tüm koleksiyonlardan da düşer
        clear.assert_called_once_with("test@example.com", "17450")

    def test_remove_from_collection_leaves_favorite(self, auth_client, api, monkeypatch):
        main, _ = api
        remove_coll = MagicMock()
        monkeypatch.setattr(main, "remove_recipe_from_collection", remove_coll)
        fav = MagicMock()
        monkeypatch.setattr(main, "remove_favorite", fav)
        r = auth_client.delete("/api/collections/c1/recipes/17450")
        assert r.status_code == 200
        remove_coll.assert_called_once()
        # Koleksiyondan çıkarmak favoriye DOKUNMAMALI
        assert not fav.called


# ── Katman 2: delete ──────────────────────────────────────

class TestDeleteCollection:
    def test_delete_success(self, auth_client, api, monkeypatch):
        main, _ = api
        monkeypatch.setattr(main, "delete_collection", MagicMock())
        r = auth_client.delete("/api/collections/c1")
        assert r.status_code == 200
        assert r.json()["message"] == "Collection deleted"

    def test_delete_missing_returns_error(self, auth_client, api, monkeypatch):
        main, _ = api
        monkeypatch.setattr(
            main, "delete_collection",
            MagicMock(side_effect=ValueError("Collection not found.")),
        )
        r = auth_client.delete("/api/collections/missing")
        assert r.status_code == 200
        assert "not found" in r.json()["error"].lower()
