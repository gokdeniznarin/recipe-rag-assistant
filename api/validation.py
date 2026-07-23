"""Kullanıcıdan gelen serbest metin sorgularının ön kontrolü.

NEDEN AYRI MODÜL: kural bazlı ve saf — ağ, veritabanı, LLM yok. filters.py ile
aynı desende, dolayısıyla mock'suz test edilebiliyor (bkz. api/tests/test_validation.py).

NEDEN HİÇBİR İŞ YAPILMADAN ÖNCE ÇAĞRILIYOR: anlamsız bir sorgu (örn. "1235533443")
bugün şunları harcıyordu:
  1. ONNX embedding + ChromaDB araması — yerelde ~300 ms, Render'ın 0.1 vCPU'sunda
     ÖLÇÜLEN değer ~5.4 sn (bkz. Faz 13c)
  2. ardından frontend'in otomatik tetiklediği /api/recipes/commentary isteği:
     ikinci bir token doğrulaması + bir Gemini çağrısı + günlük kotadan 1 hak
     (kota model başına 20, 5 model = 100 istek/gün)
Kullanıcı bunun karşılığında 5 alakasız tarif görüyordu, çünkü vektör araması
"eşleşme yok" DİYEMEZ — eşleşme kalitesine bakmadan her zaman en yakın n komşuyu
döndürür. Sistemde "sonuç yok" diye bir durum yok.

KURALLAR BİLEREK DİZGİNİN BİÇİMİNE BAKIYOR, ANLAMINA DEĞİL.
Anlamsal bir eşik (embedding mesafesi) denendi ve ÖLÇÜMLE ELENDİ. 55 sorgulu
kalibrasyonda (L2 mesafesi, en yakın komşu):
    meşru sorgular            : 0.336 - 1.566
    reddedilmesi gerekenler   : 1.230 - 1.792
Sınıflar iç içe geçiyor. "dinner" (1.185) ve "borscht" (1.141) gibi gerçek
kullanıcı sorguları, "zxcvbnm" (1.240) gibi klavye ezmelerinden DAHA UZAK
olabiliyor — çünkü ölçülen şey en yakın komşuya uzaklık ve bu, genel sorguları
("dinner") ve dataset'in zayıf olduğu mutfakları ("borscht") cezalandırıyor.
Yani hiçbir eşik iki sınıfı temiz ayıramıyor.

Buradaki biçimsel kuralların böyle bir yanlış red riski YOK: harf içermeyen ya
da tek harfin tekrarından oluşan meşru bir tarif sorgusu yoktur.

NOT (Faz 15f): "sorgu yemek mi?" gibi ANLAMSAL kararlar burada DEĞİL — o iş
llm.is_food_request'e taşındı (aramadan önce çağrılıyor). Bu modül yalnızca
biçimsel, deterministik, LLM'siz kontrolleri yapıyor. Eskiden burada bir mesafe
eşiği (is_weak_match) vardı; tutarsız çıktığı için kaldırıldı, bkz. Faz 15f.
"""

MIN_LENGTH = 2
MAX_LENGTH = 200
MIN_DISTINCT_LETTERS = 2

# Kullanıcıya ne yapması gerektiğini söyleyen tek mesaj: "harf kullan" ile
# "tek harfi tekrar etme" ayrımı kullanıcı için bir şey ifade etmiyor, ikisinde
# de yapılacak şey aynı.
_USE_WORDS = "Please describe what you'd like to cook, for example 'quick vegan pasta'."


def validate_query(text: str) -> str | None:
    """Sorgu kullanılabilir mi?

    Sorun varsa kullanıcıya gösterilecek mesajı, sorun yoksa None döner.
    (Bool yerine mesaj dönüyor ki çağıran taraf metni kendi uydurmasın.)
    """
    query = (text or "").strip()

    if len(query) < MIN_LENGTH:
        return f"Please enter at least {MIN_LENGTH} characters."

    if len(query) > MAX_LENGTH:
        # Uzunluk sınırı sadece embedding maliyeti için değil: bu metin daha
        # sonra /api/recipes/commentary üzerinden Gemini prompt'una giriyor.
        return f"Search query is too long (maximum {MAX_LENGTH} characters)."

    # str.isalpha() Unicode farkında — "börek", "menemen" gibi sorgular geçer.
    letters = [ch for ch in query if ch.isalpha()]

    if not letters:
        # "1235533443", "!!!???...", "-----", "12 34 56 78"
        return _USE_WORDS

    if len({ch.lower() for ch in letters}) < MIN_DISTINCT_LETTERS:
        # "aaaaaaaaaa"
        return _USE_WORDS

    return None
