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

    def test_vegan_collection_narrows_by_category_not_just_the_diet_tag(self):
        """🔴 Diyet etiketi TEK BAŞINA bir iniş sayfası kuramaz.

        Ölçüldü (2026-08-17): filtresiz hâlde 1.762 vegan tarifin ilk 24'ü ne
        gelirse o basılıyordu ve sayfanın tepesinde İKİ KOKTEYL, bir salsa, bir
        ekşi maya başlatıcısı vardı — Pinterest'ten "vegan yemek" için gelen
        ziyaretçinin indiği sayfa buydu. Kardeşi `vegetarian-dinners`'ta filtre
        baştan vardı, burada unutulmuştu.

        Bunu geri almak HİÇBİR ŞEYİ kırmaz: uç yine 200 döner, kartlar yine
        vegandır, yalnızca sayfa içecek ve sosla dolar. O yüzden teste bağlı."""
        for slug in ("vegan-recipes", "vegetarian-dinners"):
            where = repr(discover.COLLECTIONS[slug]["where"])
            assert "category" in where, f"{slug}: kategori filtresi kayıp"

    def test_the_exclusion_list_holds_string_ids(self):
        """Bugün BOŞ — 2026-08-17 yeniden ingestion'ı kök sebebi kapattı, o
        yüzden yamaya gerek kalmadı. Mekanizma yerinde duruyor; buradaki tek
        şart, ileride yeniden doldurulursa **metin** ID yazılması: ChromaDB
        ID'leri metin döner, `int` yazmak sessizce hiçbir şeyi elemez."""
        assert all(isinstance(i, str) for i in discover.EXCLUDED_IDS)

    def test_unknown_slug_returns_none(self):
        assert discover.get_definition("nope") is None

    def test_the_index_lists_every_collection(self):
        listed = discover.list_definitions()
        assert len(listed) == len(discover.COLLECTIONS)
        assert {c["slug"] for c in listed} == set(discover.COLLECTIONS)

    def test_a_lone_five_star_never_outranks_a_well_reviewed_favourite(self):
        """🔴 HAM PUANLA SIRALAMAK bu testi düşürür — ve tam da yapılacak hata o.

        Veri setinde tek yorumlu bir sürü 5.0 var. `Baja Black Beans, Corn and
        Rice` ise **247 yorumla** 5.0 tutuyor. Ham puan ikisini eşit sayar ve
        sıralama ada kalır; bir iniş sayfasında sosyal kanıt tam da en çok
        gereken şeydir."""
        lonely = {"name": "Untested", "rating": 5.0, "review_count": 1}
        proven = {"name": "Baja Black Beans", "rating": 5.0, "review_count": 247}
        assert discover.quality_score(proven) > discover.quality_score(lonely)

    def test_unrated_recipes_are_not_treated_as_zero_star(self):
        """Puanlanmamış (veri setinin ~%17'si) ile KÖTÜ aynı şey değil —
        ama iyi ve çok yorumlanmışın da önüne geçmemeli."""
        unrated = {"name": "New", "rating": 0.0, "review_count": 0}
        weak = {"name": "Meh", "rating": 2.0, "review_count": 40}
        strong = {"name": "Loved", "rating": 4.9, "review_count": 120}
        assert discover.quality_score(unrated) > discover.quality_score(weak)
        assert discover.quality_score(strong) > discover.quality_score(unrated)

    def test_sort_leads_with_quality_not_with_the_shortest_recipe(self):
        """⚠️ SIRA SÜREDEN PUANA ÇEVRİLDİ. Süreye göre artan sıralamak, en
        kısa tarifi başa koyuyordu — ve en kısa şey her zaman en az 'yemek'
        olan şey (5 dakikalık jicama çubuğu), oysa aynı havuzda 247 yorumlu
        bir fasulyeli pilav vardı."""
        cards = [
            {"name": "Snack", "total_time_min": 5, "rating": 4.0, "review_count": 2},
            {"name": "Beloved Dinner", "total_time_min": 45, "rating": 5.0, "review_count": 247},
        ]
        assert [c["name"] for c in sorted(cards, key=discover.sort_key)][0] == "Beloved Dinner"

    def test_sort_is_still_fully_deterministic(self):
        """Bir pin aylarca dolaşıyor; indiği sayfa her yüklemede aynı olmalı.
        Puana geçmek bu şartı KALDIRMIYOR — eşitlikte süre, sonra ad kırıyor."""
        cards = [
            {"name": "B", "total_time_min": 30, "rating": 4.5, "review_count": 10},
            {"name": "A", "total_time_min": 30, "rating": 4.5, "review_count": 10},
        ]
        assert [c["name"] for c in sorted(cards, key=discover.sort_key)] == ["A", "B"]

    def test_sort_survives_a_database_without_ratings(self):
        """Alanları olmayan (yeniden yüklenmemiş) bir veritabanında sıralama
        çökmemeli, yalnızca ayrım gücünü kaybetmeli."""
        cards = [{"name": "B", "total_time_min": 30}, {"name": "A", "total_time_min": 10}]
        assert [c["name"] for c in sorted(cards, key=discover.sort_key)] == ["A", "B"]

    def test_equal_quality_falls_back_to_the_quicker_recipe(self):
        """Puan ayırt etmediğinde eski ölçüt (süre) hâlâ karar veriyor, ve
        süresi BİLİNMEYEN tarif sona düşüyor — `None`u 0 saymak onu en başa
        koyardı."""
        cards = [
            {"name": "Slow", "total_time_min": 90, "rating": 4.5, "review_count": 10},
            {"name": "Fast", "total_time_min": 10, "rating": 4.5, "review_count": 10},
            {"name": "Unknown", "total_time_min": None, "rating": 4.5, "review_count": 10},
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
        # Kara liste çekildikten SONRA uygulandığı için limitte pay olmak
        # zorunda; `PAGE_SIZE`'a düşürülürse elenen her tarif sayfada bir
        # eksik kart bırakır ve ızgara delik görünür.
        assert kwargs["limit"] == discover.PAGE_SIZE + len(discover.EXCLUDED_IDS)

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

    def _many(self, collection, ids):
        """Sahte koleksiyonu birden çok tarif döndürecek hâle getirir."""
        meta = collection.get.return_value["metadatas"][0]
        collection.get.return_value = {
            "documents": ["doc"] * len(ids),
            "metadatas": [dict(meta) for _ in ids],
            "ids": list(ids),
        }

    def test_an_excluded_id_never_reaches_a_public_collection(
        self, client, collection, monkeypatch
    ):
        """Eleme MEKANİZMASI çalışıyor mu — listenin bugünkü içeriğinden
        bağımsız olarak. Liste bugün boş ama `main.py`'deki `if rid not in ...`
        koşulu düşerse bu bir daha fark edilmez; kural yeniden gerektiğinde
        sessizce hiçbir şey yapmayan bir yamayla karşılaşılır."""
        monkeypatch.setattr(discover, "EXCLUDED_IDS", frozenset({"30810", "441404"}))
        self._many(collection, ["17450", "30810", "441404", "999"])
        ids = [c["id"] for c in client.get("/api/discover/vegan-recipes").json()["recipes"]]
        assert ids == ["17450", "999"]

    def test_the_page_is_not_left_short_by_exclusions(
        self, client, collection, monkeypatch
    ):
        """Eleme sonrası sayfa yine PAGE_SIZE kart göstermeli.

        ChromaDB'den fazladan çekilmesinin tek sebebi bu; fazlalık trim
        edilmezse sayfa bu kez PAGE_SIZE'ı AŞAR."""
        monkeypatch.setattr(discover, "EXCLUDED_IDS", frozenset({"30810"}))
        extra = discover.PAGE_SIZE + 1
        self._many(collection, ["30810"] + [str(9000 + i) for i in range(extra)])
        cards = client.get("/api/discover/vegan-recipes").json()["recipes"]
        assert len(cards) == discover.PAGE_SIZE

    def test_cards_carry_what_the_page_renders(self, client, collection):
        card = client.get("/api/discover/cookies").json()["recipes"][0]
        for field in ("id", "name", "category", "total_time_min", "image_url"):
            assert field in card
