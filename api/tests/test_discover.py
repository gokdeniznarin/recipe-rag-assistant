"""Faz 29 — küratörlü, herkese açık koleksiyonlar.

İki şey sabitleniyor ve ikisi de sessizce bozulabilir:

1. **`get` kullanılması, `query` DEĞİL.** Fark ölçüldü: aynı konteynerde
   `get` 2.6 ms, `query` 6.4 sn (Render'da 0.1 vCPU'da ONNX embedding —
   Faz 17). Biri iyi niyetle "arama daha alakalı sonuç verir" diye `query`'ye
   çevirirse her iniş sayfası 6 saniye sürer ve HİÇBİR TEST kırılmaz —
   sayfa yine doğru tarifleri gösterir, sadece kimse beklemez.

2. **Diyet etiketli koleksiyon OLMAMASI.** `vegetarian` 228 tarifte yanlış
   (içinde ham/sausage var). "Vegetarian Dinners" diye pinlenen bir listeye
   jambonlu tarif koymak, kazanılacak trafikten pahalıya mal olur.
"""
import pytest

import discover
import ratelimit


@pytest.fixture(autouse=True)
def _reset_limiter():
    ratelimit.reset()
    yield
    ratelimit.reset()


# ── Katman 1: tanımlar (saf) ──────────────────────────────

class TestDefinitions:
    def test_every_collection_has_the_fields_the_page_renders(self):
        for slug, entry in discover.COLLECTIONS.items():
            assert entry["title"], slug
            assert entry["description"], slug
            assert entry["where"], slug

    def test_slugs_are_url_safe(self):
        """Slug doğrudan URL'e giriyor; boşluk ya da büyük harf kanonik
        adresi bozar ve pin'in indiği yer 404 olur."""
        import re
        for slug in discover.COLLECTIONS:
            assert re.fullmatch(r"[a-z0-9-]+", slug), slug

    def test_no_collection_is_built_on_an_allergen_tag(self):
        """⚖️ ALERJEN etiketleri üzerine herkese açık koleksiyon KURULMAZ.

        Adım A ölçümü iyileştirdi (etli "vejetaryen" 228 → 0) ama etiketler
        hâlâ kural bazlı TAHMİN. Buradaki hatanın sonucu tercih etiketlerinden
        kategorik olarak farklı: çölyak hastası ya da fıstık alerjisi olan biri
        için yanlış bir "Nut-Free Desserts" listesi sağlık riski. Uygulamanın
        içinde bu etiketlerin yanında "otomatik tahmin" uyarısı var; pinlenen
        bir koleksiyon başlığında o uyarıyı basacak yer YOK.

        Aynı ayrım `_seo.js`'te de uygulanıyor (`suitableForDiet` hiç yazılmıyor)."""
        allergen_fields = {"gluten_free", "dairy_free", "nut_free"}
        for slug, entry in discover.COLLECTIONS.items():
            assert not (allergen_fields & set(repr(entry["where"]).split("'"))), slug

    def test_preference_collections_exist(self):
        """Tercih bazlı koleksiyonlar (vegetarian/vegan) Pinterest'te en çok
        aranan başlıklar ve adım A'dan ÖNCE kurulamıyorlardı. Bu test onların
        sessizce düşmesini engelliyor."""
        assert "vegetarian-dinners" in discover.COLLECTIONS
        assert "vegan-recipes" in discover.COLLECTIONS

    def test_unknown_slug_returns_none(self):
        assert discover.get_definition("nope") is None

    def test_the_index_lists_every_collection(self):
        listed = discover.list_definitions()
        assert len(listed) == len(discover.COLLECTIONS)
        assert {c["slug"] for c in listed} == set(discover.COLLECTIONS)

    def test_sort_puts_quick_recipes_first(self):
        """Sıra keyfi bırakılamaz: ChromaDB `get` ekleme sırasında döndürüyor,
        yani liste her yeniden ingestion'da değişirdi. Bir pin aylarca
        dolaşıyor, indiği sayfanın kararlı olması gerekiyor."""
        cards = [
            {"name": "Slow", "total_time_min": 90},
            {"name": "Fast", "total_time_min": 10},
            {"name": "Unknown", "total_time_min": None},
        ]
        assert [c["name"] for c in sorted(cards, key=discover.sort_key)] == \
               ["Fast", "Slow", "Unknown"]


# ── Katman 2: uç sözleşmesi ───────────────────────────────

class TestEndpoints:
    def test_the_index_needs_no_auth(self, client):
        r = client.get("/api/discover")
        assert r.status_code == 200
        assert len(r.json()["collections"]) == len(discover.COLLECTIONS)

    def test_a_collection_needs_no_auth(self, client, collection):
        r = client.get("/api/discover/30-minute-dinners")
        assert r.status_code == 200
        assert r.json()["title"] == "30-Minute Dinners"
        assert r.json()["recipes"][0]["name"] == "Test Recipe"

    def test_it_uses_get_and_never_query(self, client, collection):
        """⚡ Asıl performans iddiası. `query` 2000 kat pahalı ve bu iddia
        başka hiçbir testte görünmüyor."""
        client.get("/api/discover/cookies")
        assert collection.get.called
        assert not collection.query.called

    def test_the_metadata_filter_reaches_chromadb(self, client, collection):
        client.get("/api/discover/15-minute-recipes")
        kwargs = collection.get.call_args.kwargs
        assert kwargs["where"] == discover.COLLECTIONS["15-minute-recipes"]["where"]
        assert kwargs["limit"] == discover.PAGE_SIZE

    def test_an_unknown_slug_never_touches_chromadb(self, client, collection):
        """Uydurma slug'larla gelen trafik veritabanına hiç ulaşmamalı —
        adres herkese açık ve tahmin edilebilir."""
        r = client.get("/api/discover/made-up")
        assert r.status_code == 200
        assert "error" in r.json()
        assert not collection.get.called

    def test_it_is_rate_limited(self, client, collection, monkeypatch):
        monkeypatch.setattr(ratelimit, "MAX_REQUESTS", 2)
        headers = {"X-Forwarded-For": "9.1.1.1"}
        for _ in range(2):
            assert client.get("/api/discover/cookies", headers=headers).status_code == 200
        assert client.get("/api/discover/cookies", headers=headers).status_code == 429

    def test_the_index_is_rate_limited_too(self, client, monkeypatch):
        monkeypatch.setattr(ratelimit, "MAX_REQUESTS", 1)
        headers = {"X-Forwarded-For": "9.2.2.2"}
        client.get("/api/discover", headers=headers)
        assert client.get("/api/discover", headers=headers).status_code == 429

    def test_cards_carry_what_the_page_renders(self, client, collection):
        card = client.get("/api/discover/cookies").json()["recipes"][0]
        for field in ("id", "name", "category", "total_time_min", "image_url"):
            assert field in card
