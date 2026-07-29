"""HTTP sözleşme testleri (Katman 2).

Katman 1 saf fonksiyonları test ediyordu; bu dosya ENDPOINT'in kendisini test
ediyor: auth sözleşmesi, CORS, decorator sırası, is_food_request bağlantısı ve
Faz 11b'nin "hata olsa bile 200 + CORS" kuralı. Kurulum için conftest.py'ye bak.

    python -m pytest api/tests/test_api_contract.py -v

CLAUDE.md'de "doğrulandı" diye geçen bu davranışların çoğu bugüne kadar ELLE
kontrol edilmişti; bu testler onları tekrarlanabilir hale getiriyor.
"""
from unittest.mock import MagicMock

import pytest


# ── Auth sözleşmesi ───────────────────────────────────────
# `client` fixture'ı auth'u BYPASS ETMİYOR — gerçek get_current_user_email
# çalışıyor. En sade korumalı endpoint /api/auth/me üzerinden test ediliyor
# (yalnızca token doğrulamasına bağlı, başka hiçbir şeye değil).

class TestAuthContract:
    def test_missing_header_is_422_not_401(self, client):
        # Header(...) zorunlu → FastAPI doğrulama katmanı, endpoint gövdesi
        # hiç çalışmadan 422. 401 DEĞİL — farklı katman, karışması kolay.
        assert client.get("/api/auth/me").status_code == 422

    def test_non_bearer_scheme_is_401(self, client):
        r = client.get("/api/auth/me", headers={"Authorization": "Basic abc123"})
        assert r.status_code == 401

    def test_invalid_token_is_401(self, client, monkeypatch):
        import auth
        monkeypatch.setattr(
            auth.firebase_auth, "verify_id_token",
            lambda token: (_ for _ in ()).throw(ValueError("bad token")),
        )
        r = client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"})
        assert r.status_code == 401

    def test_valid_token_returns_email(self, client, monkeypatch):
        import auth
        monkeypatch.setattr(
            auth.firebase_auth, "verify_id_token",
            lambda token: {"email": "real@user.com"},
        )
        r = client.get("/api/auth/me", headers={"Authorization": "Bearer good"})
        assert r.status_code == 200
        assert r.json() == {"email": "real@user.com"}

    def test_token_without_email_is_401(self, client, monkeypatch):
        import auth
        monkeypatch.setattr(
            auth.firebase_auth, "verify_id_token", lambda token: {"uid": "x"},
        )
        r = client.get("/api/auth/me", headers={"Authorization": "Bearer noemail"})
        assert r.status_code == 401


# ── is_food_request bağlantısı (Faz 15f) ──────────────────
# Sıra kritik: validate_query (biçim) ÖNCE, is_food_request (LLM) SONRA,
# arama EN SON. Her kapı bir sonrakini gereksiz yere tetiklememeli.

class TestFoodClassifierWiring:
    def test_food_query_reaches_search(self, auth_client, collection, api, monkeypatch):
        main, _ = api
        monkeypatch.setattr(main, "is_food_request", lambda q: True)
        r = auth_client.post("/api/recipes/search", json={"query": "chicken dinner"})
        assert r.status_code == 200
        assert len(r.json()["results"]) == 1
        assert collection.query.called

    def test_non_food_query_rejected_before_search(self, auth_client, collection, api, monkeypatch):
        main, _ = api
        monkeypatch.setattr(main, "is_food_request", lambda q: False)
        r = auth_client.post("/api/recipes/search", json={"query": "capital of france"})
        assert r.status_code == 200
        body = r.json()
        assert body["results"] == []
        assert "error" in body
        # En önemli assert: ChromaDB'ye HİÇ gidilmedi
        assert not collection.query.called

    def test_format_gate_runs_before_classifier(self, auth_client, collection, api, monkeypatch):
        # "1235533443" validate_query'de ölmeli; is_food_request ÇAĞRILMAMALI
        # (boşa Gemini çağrısı yok).
        main, _ = api
        classifier = _Counter(return_value=True)
        monkeypatch.setattr(main, "is_food_request", classifier)
        r = auth_client.post("/api/recipes/search", json={"query": "1235533443"})
        assert r.status_code == 200
        assert r.json()["results"] == []
        assert "error" in r.json()
        assert classifier.calls == 0           # sınıflandırıcıya hiç gidilmedi
        assert not collection.query.called

    def test_response_has_no_weak_match_field(self, auth_client, api, monkeypatch):
        # Faz 15f'de weak_match kaldırıldı — yanıtta artık olmamalı.
        main, _ = api
        monkeypatch.setattr(main, "is_food_request", lambda q: True)
        r = auth_client.post("/api/recipes/search", json={"query": "chicken"})
        assert "weak_match" not in r.json()


# ── Faz 11b: hata olsa bile 200 + CORS header ─────────────
# Vision çağrısı patlarsa endpoint 500 DEĞİL 200 dönmeli; 500 CORS
# middleware'ine uğramadan çıkar ve tarayıcıda yanıltıcı "CORS hatası" görünür.

class TestImageErrorStaysCORSSafe:
    def test_vision_error_returns_200_with_message(self, auth_client, api, monkeypatch):
        main, _ = api
        monkeypatch.setattr(
            main, "detect_ingredients_from_image",
            lambda img: (_ for _ in ()).throw(Exception("boom")),
        )
        r = auth_client.post(
            "/api/recipes/from-image",
            json={"image_base64": "data:image/jpeg;base64,xxx"},
            headers={"Origin": "https://recipe-rag-assistant.vercel.app"},
        )
        assert r.status_code == 200                       # 500 DEĞİL
        assert "error" in r.json()
        # Kritik: CORS header yerinde (200 olduğu için middleware'e uğradı)
        assert r.headers.get("access-control-allow-origin") == "https://recipe-rag-assistant.vercel.app"

    def test_quota_error_gives_specific_message(self, auth_client, api, monkeypatch):
        main, _ = api
        monkeypatch.setattr(
            main, "detect_ingredients_from_image",
            lambda img: (_ for _ in ()).throw(Exception("429 RESOURCE_EXHAUSTED")),
        )
        r = auth_client.post("/api/recipes/from-image", json={"image_base64": "x"})
        assert r.status_code == 200
        assert "quota" in r.json()["error"].lower()

    def test_no_ingredients_detected(self, auth_client, api, monkeypatch):
        main, _ = api
        monkeypatch.setattr(main, "detect_ingredients_from_image", lambda img: [])
        r = auth_client.post("/api/recipes/from-image", json={"image_base64": "x"})
        assert r.status_code == 200
        assert "error" in r.json()


# ── CORS ──────────────────────────────────────────────────

class TestCORS:
    def test_allowed_origin_reflected(self, client):
        origin = "https://recipe-rag-assistant.vercel.app"
        r = client.get("/", headers={"Origin": origin})
        assert r.headers.get("access-control-allow-origin") == origin

    def test_vercel_preview_reflected(self, client):
        origin = "https://recipe-rag-assistant-git-abc123.vercel.app"
        r = client.get("/", headers={"Origin": origin})
        assert r.headers.get("access-control-allow-origin") == origin

    def test_evil_origin_not_reflected(self, client):
        r = client.get("/", headers={"Origin": "https://evil.com"})
        assert r.headers.get("access-control-allow-origin") != "https://evil.com"

    def test_suffix_spoof_not_reflected(self, client):
        # "...vercel.app.evil.com" regex'i geçmemeli (fullmatch'e dayanıyor)
        origin = "https://recipe-rag-assistant.vercel.app.evil.com"
        r = client.get("/", headers={"Origin": origin})
        assert r.headers.get("access-control-allow-origin") != origin


# ── Decorator sırası (OpenAPI üzerinden) ──────────────────
# @timed, @app.post'un ALTINDA olmalı. Ters çevrilirse FastAPI sarmalanmamış
# fonksiyonu kaydeder ve ölçüm sessizce ölür. functools.wraps imzayı koruduğu
# için OpenAPI şeması hâlâ gövde + header parametrelerini göstermeli.

class TestDecoratorOrderPreservesSchema:
    def test_search_body_schema_present(self, client):
        schema = client.get("/openapi.json").json()
        post = schema["paths"]["/api/recipes/search"]["post"]
        assert "requestBody" in post          # SearchRequest gövdesi görünüyor

    def test_authorization_header_required(self, client):
        schema = client.get("/openapi.json").json()
        params = schema["paths"]["/api/recipes/search"]["post"].get("parameters", [])
        auth_params = [p for p in params if p["name"].lower() == "authorization"]
        assert auth_params and auth_params[0]["required"] is True


# ── Uptime izleme ucu ─────────────────────────────────────
# Render ücretsiz katmanda 15 dk sessizlikten sonra uyuyor ve uyanması ÖLÇÜLDÜ:
# 42.6 sn (uyanıkken 0.42 sn). Bunu engellemek için `/` düzenli aralıklarla
# çağrılıyor. Bu sınıf o çağrının çalışmaya devam ettiğini sabitliyor.

class TestUptimeProbe:
    def test_root_answers_get(self, client):
        assert client.get("/").status_code == 200

    def test_root_answers_head(self, client):
        # FastAPI, düz Starlette'in AKSİNE bir GET rotasına HEAD'i otomatik
        # eklemiyor; bu uç bir süre HEAD'e 405 döndü ve izleme aracı monitörü
        # kurulur kurulmaz "Down | 405" gösterdi. İzleme araçlarının çoğu
        # varsayılan olarak HEAD attığı için bu davranış geri gelirse uptime
        # takibi sessizce yanlış alarma döner.
        assert client.head("/").status_code == 200

    def test_root_needs_no_auth(self, client):
        # `client` (auth_client DEĞİL) kullanılıyor: izleme aracının token'ı yok.
        assert "error" not in client.get("/").json()


# ── Sınır yolları ─────────────────────────────────────────

class TestBoundaryPaths:
    def test_recipe_not_found_is_200_with_error(self, auth_client, collection):
        collection.get.return_value = {"documents": [], "metadatas": [], "ids": []}
        r = auth_client.get("/api/recipes/99999")
        assert r.status_code == 200          # 404 DEĞİL — mevcut davranış
        assert r.json() == {"error": "Recipe not found"}

    def test_commentary_empty_ids_skips_llm(self, auth_client, api, monkeypatch):
        main, _ = api
        gen = _Counter(return_value="some answer")
        monkeypatch.setattr(main, "generate_answer", gen)
        r = auth_client.post("/api/recipes/commentary", json={"query": "x", "recipe_ids": []})
        assert r.status_code == 200
        assert r.json() == {"answer": None}
        assert gen.calls == 0                # Gemini hiç çağrılmadı

    def test_n_results_over_limit_is_422(self, auth_client):
        r = auth_client.post("/api/recipes/search", json={"query": "chicken", "n_results": 21})
        assert r.status_code == 422

    def test_commentary_query_too_long_is_422(self, auth_client):
        r = auth_client.post(
            "/api/recipes/commentary",
            json={"query": "a" * 501, "recipe_ids": ["1"]},
        )
        assert r.status_code == 422


# ── Yardımcı ──────────────────────────────────────────────

class _Counter:
    """Kaç kez çağrıldığını sayan basit sahte (monkeypatch için)."""
    def __init__(self, return_value=None):
        self.return_value = return_value
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        return self.return_value


class TestGenerateFallbackChain:
    """`_generate`'in "bu modeli atla" kararı — hangi hatanın zinciri sürdürüp
    hangisinin yukarı fırlatıldığı."""

    def _llm(self, api):
        import llm
        return llm

    def test_a_503_falls_back_instead_of_killing_the_request(self, api, monkeypatch):
        """REGRESYON: 503 listede YOKTU, dolayısıyla aşırı yüklü TEK bir model
        sıradaki modeller hazır beklerken bütün isteği çöktürüyordu. Faz 6'da
        ücretsiz katmanda sürekli 503 veren bir model yaşanmıştı."""
        llm = self._llm(api)
        calls = []

        def flaky(model, contents, config=None):
            calls.append(model)
            if len(calls) == 1:
                raise Exception("503 UNAVAILABLE. The model is overloaded.")
            return type("R", (), {"text": "ok"})()

        monkeypatch.setattr(llm.client.models, "generate_content", flaky)

        assert llm._generate(("model-a", "model-b"), "prompt").text == "ok"
        assert calls == ["model-a", "model-b"]      # ilkini atlayıp ikinciye geçti

    @pytest.mark.parametrize("message", [
        "429 RESOURCE_EXHAUSTED", "404 NOT_FOUND", "503 UNAVAILABLE",
    ])
    def test_model_level_errors_continue_the_chain(self, api, monkeypatch, message):
        llm = self._llm(api)
        calls = []

        def flaky(model, contents, config=None):
            calls.append(model)
            if len(calls) == 1:
                raise Exception(message)
            return type("R", (), {"text": "ok"})()

        monkeypatch.setattr(llm.client.models, "generate_content", flaky)
        llm._generate(("a", "b"), "p")
        assert len(calls) == 2

    def test_a_real_error_is_still_raised(self, api, monkeypatch):
        """Bozuk istek ya da ağ hatasında denemeye devam etmek yanıltıcı olurdu —
        sıradaki model de aynı hatayı verir."""
        llm = self._llm(api)
        calls = []

        def broken(model, contents, config=None):
            calls.append(model)
            raise Exception("400 INVALID_ARGUMENT: malformed request")

        monkeypatch.setattr(llm.client.models, "generate_content", broken)

        with pytest.raises(Exception, match="INVALID_ARGUMENT"):
            llm._generate(("a", "b"), "p")
        assert calls == ["a"]        # ikinciye HİÇ geçmedi

    def test_a_timeout_falls_back_instead_of_blocking(self, api, monkeypatch):
        """REGRESYON: zincir yalnızca "kullanılamıyor" durumunda geçiyordu.
        Yavaş ama sonunda cevap veren bir model hiçbir korumaya takılmıyordu —
        canlıda AI yorumu 37.8 sn sürdü, oysa zincirde 0.5 sn'lik modeller
        bekliyordu."""
        llm = self._llm(api)
        calls = []

        class ReadTimeout(Exception):
            """httpx'in gerçek sınıfı gibi: mesajında "timeout" GEÇMİYOR."""

        def slow(model, contents, config=None):
            calls.append(model)
            if len(calls) == 1:
                raise ReadTimeout("The handshake operation timed out")
            return type("R", (), {"text": "ok"})()

        monkeypatch.setattr(llm.client.models, "generate_content", slow)

        assert llm._generate(("a", "b"), "p").text == "ok"
        assert calls == ["a", "b"]

    def test_the_caller_config_is_copied_not_mutated(self, api, monkeypatch):
        """Çağıranlar kendi ayarlarını veriyor (sınıflandırıcı temperature=0,
        tabak analizi JSON modu). Zaman aşımı YERİNDE eklenirse çağıranın
        modül seviyesindeki nesnesi kalıcı olarak kirlenirdi, o yüzden kopya.

        NOT: conftest `google.genai`'yi mock'ladığı için burada gerçek pydantic
        davranışı doğrulanamıyor — yalnızca kopyalamanın çağrıldığı. Gerçek
        alan korunumu konteynerde canlı doğrulandı.
        """
        llm = self._llm(api)
        monkeypatch.setattr(llm.client.models, "generate_content",
                            lambda model, contents, config=None: type("R", (), {"text": "ok"})())

        caller_config = MagicMock()
        llm._generate(("a",), "p", config=caller_config)

        caller_config.model_copy.assert_called_once()
        update = caller_config.model_copy.call_args.kwargs["update"]
        assert "http_options" in update

    def test_a_config_is_always_sent_even_without_a_caller_one(self, api, monkeypatch):
        llm = self._llm(api)
        seen = {}
        monkeypatch.setattr(llm.client.models, "generate_content",
                            lambda model, contents, config=None: seen.update(config=config)
                            or type("R", (), {"text": "ok"})())
        llm._generate(("a",), "p")
        assert seen["config"] is not None      # zaman aşımı taşıyan config

    def test_the_unstable_preview_model_was_removed(self, api):
        """Sabah 3219 ms, öğleden sonra 43793 ms ölçüldü — kapasite kazancı
        44 saniyelik bir beklemeyi göze almaya değmiyor."""
        llm = self._llm(api)
        assert "gemini-3-flash-preview" not in llm.COMMENTARY_MODELS
        assert "gemini-3-flash-preview" not in llm.VISION_MODELS

    def test_both_chains_have_the_same_models_in_different_order(self, api):
        llm = self._llm(api)
        assert len(llm.COMMENTARY_MODELS) == 6
        assert set(llm.COMMENTARY_MODELS) == set(llm.VISION_MODELS)
        # Çapraz başlangıç korunuyor: iki akış taze havuzla giriyor
        assert llm.COMMENTARY_MODELS[0] != llm.VISION_MODELS[0]


class TestSimilarRecipes:
    """Tarif sayfasındaki öneri listesi.

    ÖNERİ SİSTEMİ, RAG DEĞİL: yalnızca retrieval, LLM'e hiç gidilmiyor.
    """

    def _stub_embeddings(self, collection, vector=None):
        """collection.get'i embedding döndürecek şekilde ayarlar.

        Gerçek ChromaDB numpy dizisi döndürüyor; sahtesi de öyle döndürmeli,
        çünkü kod `len(...) == 0` ile kontrol ediyor — `if not embeddings`
        numpy'da ValueError fırlatırdı ve bu ayrım kolayca kaçırılır.
        """
        import numpy as np
        base = collection.get.return_value

        def fake_get(ids=None, include=None, **kwargs):
            if include and "embeddings" in include:
                return {"ids": list(ids or []),
                        "embeddings": np.array([vector if vector is not None else [0.1] * 384])}
            return base

        collection.get.side_effect = fake_get

    def test_similar_recipes_are_returned(self, api, auth_client, collection):
        main, _ = api
        self._stub_embeddings(collection)
        meta = collection.query.return_value["metadatas"][0][0]
        collection.query.return_value = {
            "documents": [["a", "b"]],
            "metadatas": [[meta, meta]],
            "ids": [["17450", "999"]],
        }

        data = auth_client.get("/api/recipes/17450").json()

        assert [r["id"] for r in data["similar"]] == ["999"]

    def test_the_recipe_itself_is_excluded(self, api, auth_client, collection):
        """En yakın sonuç HER ZAMAN tarifin kendisi (mesafe 0) — düşürülmeli."""
        main, _ = api
        self._stub_embeddings(collection)
        meta = collection.query.return_value["metadatas"][0][0]
        collection.query.return_value = {
            "documents": [["a"]], "metadatas": [[meta]], "ids": [["17450"]],
        }

        data = auth_client.get("/api/recipes/17450").json()

        assert data["similar"] == []

    def test_it_queries_by_stored_vector_not_by_text(self, api, auth_client, collection):
        """KRİTİK: metinle sorgu ONNX encode tetikler (Render'da ~6 sn).
        Saklanmış vektörle sorgu o adımı tamamen atlıyor (ölçüldü: 5.3 ms)."""
        main, _ = api
        self._stub_embeddings(collection)

        auth_client.get("/api/recipes/17450")

        kwargs = collection.query.call_args.kwargs
        assert "query_embeddings" in kwargs
        assert "query_texts" not in kwargs

    def test_a_missing_embedding_yields_no_suggestions(self, api, auth_client, collection):
        import numpy as np
        main, _ = api
        base = collection.get.return_value
        collection.get.side_effect = lambda ids=None, include=None, **k: (
            {"ids": [], "embeddings": np.array([])} if include and "embeddings" in include else base
        )

        data = auth_client.get("/api/recipes/17450").json()

        assert data["similar"] == []
        assert data["name"] == "Test Recipe"      # detay yine geldi

    def test_a_failure_does_not_break_the_page(self, api, auth_client, collection):
        """Öneriler sayfanın İKİNCİL parçası — gelmemesi tarifi göstermemek
        için sebep değil."""
        main, _ = api
        base = collection.get.return_value

        def exploding_get(ids=None, include=None, **kwargs):
            if include and "embeddings" in include:
                raise RuntimeError("index unavailable")
            return base

        collection.get.side_effect = exploding_get

        response = auth_client.get("/api/recipes/17450")

        assert response.status_code == 200
        assert response.json()["similar"] == []
        assert response.json()["name"] == "Test Recipe"

    def test_no_llm_is_involved(self, api, auth_client, collection, monkeypatch):
        """Bu bir öneri sistemi, RAG değil — hiçbir Gemini çağrısı olmamalı."""
        main, _ = api
        self._stub_embeddings(collection)
        calls = []
        monkeypatch.setattr(main, "generate_answer", lambda *a, **k: calls.append(1))
        monkeypatch.setattr(main, "is_food_request", lambda *a, **k: calls.append(1) or True)

        auth_client.get("/api/recipes/17450")

        assert calls == []
