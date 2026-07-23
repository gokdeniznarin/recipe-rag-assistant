"""validation.validate_query için birim testleri.

MOCK YOK VE GEREKMİYOR: validate_query saf bir fonksiyon — ağ, veritabanı, LLM
ya da dosya erişimi içermiyor. Girdi bir string, çıktı bir string ya da None.
Sahtelenecek hiçbir bağımlılık olmadığı için testler doğrudan gerçek kodu
çalıştırıyor; yani "mock'ladığım şey gerçeğe benziyor mu?" sorusu hiç doğmuyor.
Fonksiyonun ayrı bir modülde durmasının sebebi de bu (filters.py ile aynı desen).

    python -m pytest api/tests/test_validation.py -v
"""
import pytest

from validation import (
    COMMENTARY_MAX_DISTANCE,
    MAX_LENGTH,
    MIN_LENGTH,
    is_weak_match,
    validate_query,
)


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


# ── Zayıf eşleşme ─────────────────────────────────────────
# Aşağıdaki mesafeler VE tarif metinleri gerçek ölçüm: api/chroma_data'nın bir
# kopyasına atılan gerçek sorgulardan geliyor, uydurma değiller. Kararın iki
# sinyale birden dayandığını (mesafe + sözcüksel örtüşme) doğrulayan tek kayıt
# bu testler.

# Gerçek koleksiyondan gelen doküman metinleri (kısaltılmış).
DOC_EASY_PIZZA = "Easy Pizza Sauce. Category: < 4 Hours. Ingredients: olive oil, carrot, onion."
DOC_QUICK_SAUCE = "Quick Meat Sauce from a Jar. Category: < 15 Mins. Ingredients: ground beef, onion."
DOC_GOOD_MEN = "A Few (Really) Good Men. Category: Dessert. Ingredients: butter, white sugar, egg."
DOC_BORSCH = "Ukrainian Borsch With Pyrizhky (Pyrohy) (Piroshki). Category: Meat. Ingredients: shin beef, salt."
DOC_BUFFALO_PIEROGI = "Buffalo Pierogies. Category: Lunch/Snacks. Ingredients: cayenne pepper, pierogi."
DOC_GLOGG = "Dk's Swedish Glogg. Category: Beverages. Ingredients: aquavit, Burgundy wine, sugar."
DOC_CAROB = "Carob Pinwheels. Category: Australian. Ingredients: vegan margarine, caster sugar."
DOC_MEATBALLS = "Easy Appetizer Meatballs. Category: Weeknight. Ingredients: sour cream, water."
DOC_MINESTRONE = "Quick and Easy Meatball Minestrone. Category: Beans. Ingredients: chicken broth."
DOC_TAIYAKI = "Taiyaki. Category: Dessert. Ingredients: flour, baking powder, egg, milk."


class TestIsWeakMatchGuards:
    def test_no_distances_is_not_weak(self):
        # Karar verilemiyorsa kullanıcının aleyhine davranma
        assert is_weak_match(None, "anything", [DOC_GLOGG]) is False

    def test_empty_distances_is_not_weak(self):
        # Sonuç yoksa zaten gösterilecek bir şey de yok
        assert is_weak_match([], "anything", []) is False

    def test_only_the_nearest_neighbour_matters(self):
        # İlk sonuç yakınsa arkadakiler uzak olsa bile eşleşme iyi sayılır,
        # örtüşmeye hiç bakılmaz
        assert is_weak_match([0.5, 1.9, 2.0], "zzzz", [DOC_GLOGG]) is False

    def test_missing_documents_do_not_crash(self):
        assert is_weak_match([1.9], "chicken", None) is True


class TestNearMatchesKeepCommentary:
    """Mesafe eşiğin ALTINDA — örtüşmeye bakılmadan yorum alıyorlar."""

    @pytest.mark.parametrize("query, distance", [
        ("gluten free quick chicken dinner", 0.637),
        ("chocolate cake", 0.687),
        ("soup", 0.814),
        ("turkish menemen", 1.048),
        ("borscht", 1.141),      # en yakın sonuç DOĞRU tarif (Ukrainian Borsch)
        ("food", 1.157),
        ("pad kee mao", 1.177),
        ("dinner", 1.185),
        ("tasty", 1.235),
        ("fast", 1.277),
    ])
    def test_not_weak(self, query, distance):
        assert is_weak_match([distance], query, [DOC_BORSCH]) is False


class TestVagueQueriesRescuedByOverlap:
    """Mesafe UZAK diyor ama sorgunun kelimesi tariflerde geçiyor → meşru.

    Sadece mesafeye bakılsaydı bu sorguların hepsi yorumunu kaybederdi ve
    "tam eşleşme olmayabilir" notu YANLIŞ olurdu — dönen tarifin adında
    sorgunun kendisi yazıyor.
    """

    @pytest.mark.parametrize("query, distance, docs", [
        ("easy", 1.566, [DOC_EASY_PIZZA]),
        ("quick", 1.419, [DOC_QUICK_SAUCE]),
        ("something good", 1.503, [DOC_GOOD_MEN]),
        # pierogi: eşleşme 1. dokümanda değil 2.'de — bu yüzden tek dokümana
        # değil en yakın birkaçına birden bakılıyor
        ("pierogi ruskie", 1.315, [DOC_BORSCH, DOC_BUFFALO_PIEROGI]),
    ])
    def test_overlap_keeps_commentary(self, query, distance, docs):
        assert is_weak_match([distance], query, docs) is False, \
            f"{query!r} yorumunu kaybetmemeli — kelimesi sonuçlarda geçiyor"


class TestGibberishAndOffTopicAreWeak:
    """Hem uzak hem hiçbir kelimesi tutmuyor → yorum istenmez."""

    @pytest.mark.parametrize("query, distance, docs", [
        ("qweqweqwe", 1.304, [DOC_GLOGG]),
        ("sdgsdgsdg", 1.378, [DOC_GLOGG]),
        ("lkjhgfdsa", 1.421, [DOC_GLOGG]),      # ekran görüntüsündeki sorgu
        ("qazwsxedc", 1.488, [DOC_GLOGG]),
        ("asdkjfhaskjdfh", 1.566, [DOC_GLOGG]),
        ("asdf asdf", 1.612, [DOC_GLOGG]),
        ("what is the capital of Japan", 1.520, [DOC_TAIYAKI]),
        ("mortgage interest rates", 1.599, [DOC_GLOGG]),
        ("how to tie a tie", 1.353, [DOC_GLOGG]),
    ])
    def test_weak(self, query, distance, docs):
        assert is_weak_match([distance], query, docs) is True, f"{query!r} yakalanmalıydı"

    def test_short_words_only_falls_back_to_distance(self):
        # "can you fix my car" — hiçbir kelime 4 harften uzun değil, yani
        # örtüşme İDDİA EDİLEMEZ. Mesafe tek karar verici kalıyor.
        assert is_weak_match([1.698], "can you fix my car", [DOC_CAROB]) is True

    def test_exact_word_boundary_required(self):
        # Önek eşleşmesi kullanılsaydı "japan" -> "Japanese" tutar ve konu dışı
        # sorgu kaçardı. \b...\b bunu engelliyor.
        japanese = "Low Carb Japanese Curry. Category: Curries. Ingredients: chicken."
        assert is_weak_match([1.520], "what is the capital of Japan", [japanese]) is True


class TestThresholdBoundary:
    def test_just_below_threshold_is_never_weak(self):
        assert is_weak_match([COMMENTARY_MAX_DISTANCE - 0.001], "zzzz", [DOC_GLOGG]) is False

    def test_at_threshold_without_overlap_is_weak(self):
        assert is_weak_match([COMMENTARY_MAX_DISTANCE], "zzzz", [DOC_GLOGG]) is True


class TestKnownFalsePositives:
    """Bilinen maliyet — kayda geçirilsin diye test edildi.

    `simple` ve `cheap` meşru sorgular ama hem uzaklar hem de kelimeleri dönen
    tariflerde geçmiyor (sonuçlar "Easy Appetizer Meatballs" gibi eşanlamlılar).
    Sonuçlarını YİNE görüyorlar, sadece AI yorumu gelmiyor.

    Ölçüm: bu kural yanlış redleri 6/16'dan 2/16'ya indirdi; kalan ikisi bunlar.
    """

    @pytest.mark.parametrize("query, distance, docs", [
        ("simple", 1.766, [DOC_MEATBALLS]),
        ("cheap", 1.702, [DOC_MINESTRONE]),
    ])
    def test_still_weak(self, query, distance, docs):
        assert is_weak_match([distance], query, docs) is True
