"""Faz 29 — herkese açık tarif detayı + anonim uçlar için hız sınırı.

İKİ AYRI ŞEY test ediliyor ve ikisi de sessizce bozulabilir türden:

1. **Ucun AÇIK kalması.** Bir gün biri "korumalı endpoint'lerde eksik auth var mı"
   diye tarayıp buraya `Depends(get_current_user_email)` geri koyarsa hiçbir test
   kırılmaz, uygulama çalışmaya devam eder — sadece Pinterest'ten gelen HERKES
   giriş formuna düşer ve büyüme kanalı sessizce ölür. Bu dosyadaki auth
   testlerinin tek işi o geri dönüşü kırmak.

2. **Hız sınırının DOĞRU ŞEYİ sayması.** Yanlış anahtar seçmek iki yönde de
   felakete gidiyor ve ikisi de yerelde fark edilmez (aşağıdaki
   `TestRateLimitKey`).
"""
import pytest

import ratelimit


@pytest.fixture(autouse=True)
def _reset_limiter():
    """Her test kendi sayacıyla başlasın; yoksa testler birbirini 429'a düşürür."""
    ratelimit.reset()
    yield
    ratelimit.reset()


# ── 1. Uç girişsiz erişilebilir ───────────────────────────

class TestPublicAccess:
    def test_recipe_detail_needs_no_auth(self, client, collection):
        """Faz 29'un TAMAMI bu satıra bağlı: Authorization header'ı YOK."""
        r = client.get("/api/recipes/17450")

        assert r.status_code == 200
        assert r.json()["name"] == "Test Recipe"

    def test_authenticated_request_still_works(self, client, collection, monkeypatch):
        """Uygulama içinden gelen (token'lı) istek de aynı yanıtı almalı —
        girişsiz erişimi açarken giriş yapmış kullanıcıyı kırmadığımızın kontrolü."""
        import auth
        monkeypatch.setattr(
            auth.firebase_auth, "verify_id_token",
            lambda token: {"email": "a@b.com"},
        )
        r = client.get("/api/recipes/17450", headers={"Authorization": "Bearer good"})

        assert r.status_code == 200
        assert r.json()["name"] == "Test Recipe"

    def test_response_carries_no_user_data(self, client, collection):
        """Ucu açmak bir gizlilik yüzeyi yaratmıyor: yanıt salt-okunur tarif
        verisi. Kullanıcıya ait bir alan eklenirse (favori durumu, e-posta…)
        anonim ziyaretçiye sızardı."""
        body = r"%s" % client.get("/api/recipes/17450").json()

        for leaked in ("email", "owner", "favorite", "user"):
            assert leaked not in body.lower()

    def test_other_endpoints_are_still_protected(self, client):
        """Regresyon: tarif detayını açarken kullanıcı verisi uçlarını
        yanlışlıkla açmadık. Header zorunlu olduğu için 422."""
        for path in ("/api/favorites", "/api/pantry", "/api/collections"):
            assert client.get(path).status_code == 422


# ── 2. Hız sınırı: hangi anahtara göre sayıyor ────────────

class TestRateLimitKey:
    """⚠️ Bu sınıftaki iki test, modülün var olma sebebini koruyor.

    Anahtar seçimi iki yönde de bozulabilir ve İKİSİ DE YERELDE GÖRÜNMEZ,
    çünkü yerelde proxy yok ve tek istemci var:

      `request.client.host`'a göre saymak → Render'da her isteğin kaynağı
      proxy görünür, yani tek bir yoğun ziyaretçi HERKESİ sınırlar.

      SSR muafiyetini unutmak → Vercel fonksiyonundan gelen tüm trafik birkaç
      IP'de toplanır, yani Pinterest'ten trafik geldiği anda SSR yolu kendi
      kendini 429'a düşürür.
    """

    def test_different_visitors_behind_one_proxy_are_counted_apart(
        self, client, collection, monkeypatch
    ):
        monkeypatch.setattr(ratelimit, "MAX_REQUESTS", 2)

        # Aynı TestClient (yani aynı request.client.host), FARKLI ziyaretçiler.
        for _ in range(2):
            assert client.get(
                "/api/recipes/17450", headers={"X-Forwarded-For": "1.1.1.1"}
            ).status_code == 200

        # Birinci ziyaretçi sınırı doldurdu…
        assert client.get(
            "/api/recipes/17450", headers={"X-Forwarded-For": "1.1.1.1"}
        ).status_code == 429

        # …ama ikincisi bundan HİÇ etkilenmiyor.
        assert client.get(
            "/api/recipes/17450", headers={"X-Forwarded-For": "2.2.2.2"}
        ).status_code == 200

    def test_only_the_first_forwarded_entry_counts(self, client, collection, monkeypatch):
        """Proxy zincirleri X-Forwarded-For'a EKLEME yapıyor: "istemci, proxy1,
        proxy2". Tüm dizgiyi anahtar saysaydık, aynı ziyaretçi farklı bir proxy
        üzerinden geldiğinde yeni bir kimlik kazanıp sınırı sıfırlardı."""
        monkeypatch.setattr(ratelimit, "MAX_REQUESTS", 1)

        assert client.get(
            "/api/recipes/17450", headers={"X-Forwarded-For": "9.9.9.9, 10.0.0.1"}
        ).status_code == 200
        assert client.get(
            "/api/recipes/17450", headers={"X-Forwarded-For": "9.9.9.9, 10.0.0.99"}
        ).status_code == 429


# ── 3. Hız sınırı: davranış ───────────────────────────────

class TestRateLimitBehaviour:
    def test_requests_over_the_limit_get_429(self, client, collection, monkeypatch):
        monkeypatch.setattr(ratelimit, "MAX_REQUESTS", 3)
        headers = {"X-Forwarded-For": "5.5.5.5"}

        for _ in range(3):
            assert client.get("/api/recipes/17450", headers=headers).status_code == 200

        r = client.get("/api/recipes/17450", headers=headers)
        assert r.status_code == 429
        assert "error" in r.json()

    def test_429_still_carries_the_cors_header(self, client, collection, monkeypatch):
        """Faz 11b dersi: CORS başlığı olmayan bir hata yanıtı tarayıcıda
        gerçek sebebi GİZLER ve yanıltıcı bir CORS hatası olarak görünür.
        429'un middleware yığınından geçtiği VARSAYILMIYOR, ölçülüyor."""
        monkeypatch.setattr(ratelimit, "MAX_REQUESTS", 1)
        origin = "https://recipe-rag-assistant.vercel.app"
        headers = {"X-Forwarded-For": "6.6.6.6", "Origin": origin}

        client.get("/api/recipes/17450", headers=headers)
        r = client.get("/api/recipes/17450", headers=headers)

        assert r.status_code == 429
        assert r.headers.get("access-control-allow-origin") == origin

    def test_blocked_request_never_touches_chromadb(self, client, collection, monkeypatch):
        """Sınır 0.1 vCPU'yu korumak için var; engellenen istek veritabanına
        gidiyorsa korumanın hiçbir anlamı kalmaz."""
        monkeypatch.setattr(ratelimit, "MAX_REQUESTS", 1)
        headers = {"X-Forwarded-For": "7.7.7.7"}

        client.get("/api/recipes/17450", headers=headers)
        collection.reset_mock()
        client.get("/api/recipes/17450", headers=headers)

        assert collection.get.call_count == 0

    def test_counters_clear_when_the_window_rolls_over(self, client, collection, monkeypatch):
        """Pencere dolunca sözlük tamamen siliniyor. İki işi birden yapıyor:
        sınırı yeniliyor VE belleği sınırlıyor (süpürme unutulursa 512 MB'lık
        konteynerde sessiz bir sızıntı olurdu)."""
        monkeypatch.setattr(ratelimit, "MAX_REQUESTS", 1)
        headers = {"X-Forwarded-For": "8.8.8.8"}

        client.get("/api/recipes/17450", headers=headers)
        assert client.get("/api/recipes/17450", headers=headers).status_code == 429

        clock = [ratelimit.time.monotonic() + ratelimit.WINDOW_SEC + 1]
        monkeypatch.setattr(ratelimit.time, "monotonic", lambda: clock[0])

        assert client.get("/api/recipes/17450", headers=headers).status_code == 200
        assert len(ratelimit._hits) == 1        # eskiler silindi, sadece yeni kayıt

    def test_the_shipped_limit_is_generous_enough_for_humans(self):
        """Sabitlerin kendisi teste bağlı: bir yazım hatasıyla 6'ya düşseydi
        normal gezinme 429 yerdi ve bunu ancak canlıda fark ederdik."""
        assert ratelimit.MAX_REQUESTS >= 30
        assert ratelimit.WINDOW_SEC == 60


# ── 4. SSR muafiyeti ──────────────────────────────────────

class TestInternalExemption:
    def test_ssr_function_is_not_rate_limited(self, client, collection, monkeypatch):
        monkeypatch.setenv("INTERNAL_API_KEY", "s3cret")
        monkeypatch.setattr(ratelimit, "MAX_REQUESTS", 1)
        headers = {"X-Forwarded-For": "3.3.3.3", "X-Internal-Key": "s3cret"}

        for _ in range(5):
            assert client.get("/api/recipes/17450", headers=headers).status_code == 200

    def test_wrong_key_gets_no_exemption(self, client, collection, monkeypatch):
        monkeypatch.setenv("INTERNAL_API_KEY", "s3cret")
        monkeypatch.setattr(ratelimit, "MAX_REQUESTS", 1)
        headers = {"X-Forwarded-For": "4.4.4.4", "X-Internal-Key": "guess"}

        client.get("/api/recipes/17450", headers=headers)
        assert client.get("/api/recipes/17450", headers=headers).status_code == 429

    def test_no_exemption_when_the_env_var_is_unset(self, client, collection, monkeypatch):
        """⚠️ Muafiyetin sırsız bir varsayılanı YOK. Olsaydı, ortam değişkenini
        kurmayı unuttuğumuz an sınır herkes tarafından atlanabilir olurdu —
        korumanın var olduğunu sanıp hiç sahip olmamak."""
        monkeypatch.delenv("INTERNAL_API_KEY", raising=False)
        monkeypatch.setattr(ratelimit, "MAX_REQUESTS", 1)
        headers = {"X-Forwarded-For": "4.4.4.5", "X-Internal-Key": "anything"}

        client.get("/api/recipes/17450", headers=headers)
        assert client.get("/api/recipes/17450", headers=headers).status_code == 429
