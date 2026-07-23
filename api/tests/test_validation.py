"""validation.validate_query için birim testleri.

MOCK YOK VE GEREKMİYOR: validate_query saf bir fonksiyon — ağ, veritabanı, LLM
ya da dosya erişimi içermiyor. Girdi bir string, çıktı bir string ya da None.
Sahtelenecek hiçbir bağımlılık olmadığı için testler doğrudan gerçek kodu
çalıştırıyor; yani "mock'ladığım şey gerçeğe benziyor mu?" sorusu hiç doğmuyor.
Fonksiyonun ayrı bir modülde durmasının sebebi de bu (filters.py ile aynı desen).

    python -m pytest api/tests/test_validation.py -v
"""
import pytest

from validation import MAX_LENGTH, MIN_LENGTH, validate_query


# ── Sözleşme ──────────────────────────────────────────────

class TestContract:
    def test_valid_query_returns_none(self):
        assert validate_query("quick vegan pasta") is None

    def test_invalid_query_returns_message_string(self):
        result = validate_query("1235533443")
        assert isinstance(result, str)
        assert result  # boş mesaj dönmemeli — kullanıcıya bu gösteriliyor


# ── Reddedilenler ─────────────────────────────────────────

class TestRejected:
    @pytest.mark.parametrize("query", [
        "1235533443",      # kullanıcının bildirdiği asıl örnek
        "999999",
        "00000000",
        "12 34 56 78",
        "!!!???...",
        "-----",
        "....",
        "@#$%^&*",
    ])
    def test_no_letters(self, query):
        # Harf içermeyen meşru bir tarif sorgusu yok.
        assert validate_query(query) is not None

    @pytest.mark.parametrize("query", ["aaaaaaaaaa", "aaa", "AAAA", "aAaAaA"])
    def test_single_distinct_letter(self, query):
        assert validate_query(query) is not None

    @pytest.mark.parametrize("query", ["", " ", "   ", "\t\n", "a", " x "])
    def test_too_short(self, query):
        assert validate_query(query) is not None

    def test_too_long(self):
        assert validate_query("chicken " * 40) is not None

    def test_none_input_does_not_crash(self):
        # Pydantic normalde buraya str dışında bir şey geçirmez, ama fonksiyon
        # tek başına da savunmalı olmalı (doğrudan çağrılabiliyor).
        assert validate_query(None) is not None


# ── Sınır değerleri ───────────────────────────────────────

class TestBoundaries:
    def test_exactly_min_length_passes(self):
        assert len("up") == MIN_LENGTH
        assert validate_query("up") is None

    def test_exactly_max_length_passes(self):
        assert validate_query("a" + "b" * (MAX_LENGTH - 1)) is None

    def test_one_over_max_length_fails(self):
        assert validate_query("a" + "b" * MAX_LENGTH) is not None

    def test_whitespace_is_stripped_before_measuring(self):
        # Kırpma uzunluk kontrolünden ÖNCE olmalı, yoksa "  a  " geçerdi
        assert validate_query("  a  ") is not None
        assert validate_query("  soup  ") is None

    def test_two_distinct_letters_is_enough(self):
        assert validate_query("ab") is None


# ── Kabul edilenler (yanlış red koruması) ─────────────────
# Bu liste, mesafe eşiğini eleyen 55 sorgulu kalibrasyondan geliyor. Oradaki
# BÜTÜN meşru sorgular buradan geçmek zorunda: validation.py'nin biçimsel
# kurallarla çalışmasının tek gerekçesi "yanlış red riski yok" iddiasıydı ve
# bu testler o iddiayı koruyor.

class TestAccepted:
    @pytest.mark.parametrize("query", [
        # normal sorgular
        "gluten free quick chicken dinner", "vegan pasta with mushrooms",
        "chocolate cake", "soup", "easy breakfast", "spicy thai noodles",
        "grilled salmon with lemon", "low calorie salad", "beef stew slow cooker",
        "quick lunch under 15 minutes", "healthy snack for kids", "pancakes",
        # ÇOK GENEL ama meşru — embedding mesafesi bunları reddediyordu (1.15-1.30)
        "food", "dinner", "easy", "healthy", "something good", "what can I make",
        # dataset'in zayıf olduğu mutfaklar — mesafe eşiği bunları da vuruyordu
        "borscht", "turkish menemen", "kimchi jjigae", "pierogi ruskie",
        "pad kee mao", "injera teff bread",
        # yazım hataları (embedding tolere ediyor, biz de etmeliyiz)
        "chiken dinner", "vegitarian pasta",
        # içinde rakam geçen meşru sorgular
        "7 up cake", "dinner in 45 minutes", "top 10 pasta",
        # Unicode harfler — str.isalpha() bunları harf sayıyor
        "börek", "crème brûlée", "jalapeño poppers",
    ])
    def test_legitimate_queries_pass(self, query):
        assert validate_query(query) is None, f"yanlış red: {query!r}"
