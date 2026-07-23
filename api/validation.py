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
"""

import re

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


# ── Zayıf eşleşme tespiti ─────────────────────────────────
# Yukarıdaki biçimsel kuralların yakalayamadığı sınıf: harf çeşitliliği olan
# klavye ezmeleri ("lkjhgfdsa") ve konu dışı ama düzgün cümleler ("how to tie a
# tie"). Bunları biçimden ayırt etmek MÜMKÜN DEĞİL — "borscht" ile
# "asdkjfhaskjdfh" istatistiksel olarak birbirine benziyor (ikisinde de sesli
# harf oranı %14, sessiz dizisi 5-6 harf).
#
# Elde kullanılmayan bir sinyal var: ChromaDB `distances`'ı zaten hesaplayıp
# döndürüyor. Ölçüm (yerel): embedding üretimi 155 ms, HNSW araması 1 ms —
# yani mesafe, arama sırasında zaten ödenmiş bir bilgi, okumanın maliyeti yok.
#
# EŞİK NEDEN 1.3 (55 sorgulu kalibrasyon, L2, en yakın komşu):
#   meşru sorgular          : 0.336 - 1.566
#   reddedilmesi gerekenler : 1.230 - 1.792
# Sınıflar İÇ İÇE. Bu yüzden eşik SONUÇLARI GİZLEMEK İÇİN KULLANILMIYOR —
# öyle olsaydı "dinner" (1.185), "borscht" (1.141), "pad kee mao" (1.177) gibi
# gerçek sorgular sonuçsuz kalırdı. Yalnızca (a) AI yorumu istenip istenmeyeceğine
# ve (b) sonuçların üstüne "tam eşleşme olmayabilir" notu düşülüp düşülmeyeceğine
# karar veriyor.
#
# Maliyet asimetrik: sonuç gizlemek gerçek zarar, yorumu atlamak zaten tasarlanmış
# bir durum (kota dolduğunda search.js:96 kutuyu aynen gizliyor).
#
# 1.3'te ölçülen davranış: 12 klavye ezmesinin HEPSİ (1.304 - 1.612) yakalanıyor;
# meşrulardan yalnızca "pierogi ruskie" (1.315) ve içerik taşımayan "easy" /
# "something good" yorumsuz kalıyor.
#
# UYARI: bu sayı embedding modeline özel (all-MiniLM-L6-v2 + ChromaDB varsayılan
# L2). Model ya da mesafe metriği değişirse yeniden kalibre edilmeli.
COMMENTARY_MAX_DISTANCE = 1.3

# ── İkinci sinyal: sözcüksel örtüşme ──────────────────────
# Mesafe TEK BAŞINA yetmiyor, çünkü aslında isabeti değil ÖZGÜLLÜĞÜ ölçüyor.
# "easy" yüzlerce tarifin adında geçtiği için hepsine orta uzaklıkta duruyor,
# hiçbirine çok yakın değil — nearest-neighbour mesafesi bunu "alakasız" diye
# okuyor. Ölçüm (sadece mesafe kullanılsaydı):
#     "easy"   1.566 -> yorum kesilir, ama dönen tarif "Easy Pizza Sauce"
#     "quick"  1.419 -> yorum kesilir, ama dönen tarif "Quick Meat Sauce"
# Yani not ("tam eşleşme olmayabilir") düpedüz YANLIŞ olurdu. Üstelik eşanlamlı
# "fast" (1.277) eşiğin altında kalıp yorum alıyordu — tutarsız.
#
# Ayırt edici ikinci soru: SORGUDAKİ KELİME DÖNEN TARİFLERDE GEÇİYOR MU?
#     "easy"      -> "Easy Pizza Sauce"          geçiyor  -> meşru
#     "lkjhgfdsa" -> "Dk's Swedish Glogg"        geçmiyor -> saçma
# Bu bilgi de bedava: dokümanlar zaten arama yanıtında elimizde.
#
# ÖLÇÜM (16 meşru + 13 saçma/konu dışı sorgu):
#     sadece mesafe          : yanlış red 6/16, kaçan 1/13
#     mesafe + örtüşme (VE)  : yanlış red 2/16, kaçan 1/13
# Ödünleşim yok, katıksız kazanç. Geri kazanılanlar: easy, quick,
# "something good" ve pierogi ruskie (bu sonuncusu eskiden bilinen maliyetti).
#
# TAM KELIME sınırı (\b...\b) şart: önek eşleşmesi kullanılınca "japan" sorgusu
# "Japanese Curry"ye takılıp "what is the capital of Japan"ı kaçırıyordu.
#
# Kaç dokümana bakılacağı ölçüldü: 1 doküman pierogi'yi kaçırıyor (eşleşme
# 2. sırada), 5 doküman "best gaming laptop"u içeri alıyor ("best" tarif
# adlarında çok geçiyor). 2 ve 3 aynı sonucu veriyor; 3 seçildi.
OVERLAP_DOCS = 3
MIN_TOKEN_LENGTH = 4

# Yalnızca dilbilgisel dolgu kelimeleri. Yemek sıfatları (easy, quick, good)
# BİLEREK listede değil — "easy" sorgusunun eşleşmesi gereken tek kelimesi o.
_STOPWORDS = frozenset({
    "what", "this", "that", "with", "from", "your", "have", "some", "make",
    "need", "want", "please", "would", "could", "there", "about", "which",
    "when", "them", "into", "will", "just",
})


def _has_lexical_overlap(query: str, documents: list[str]) -> bool:
    """Sorgudaki anlamlı bir kelime, en yakın tariflerin metninde geçiyor mu?"""
    tokens = {
        word
        for word in re.findall(rf"[a-z]{{{MIN_TOKEN_LENGTH},}}", query.lower())
        if word not in _STOPWORDS
    }
    if not tokens:
        # Sorguda kontrol edilecek kelime yok ("can you fix my car" — hepsi
        # 4 harften kısa). Örtüşme İDDİA EDİLEMEZ, mesafe tek karar verici olur.
        return False

    blob = " ".join(documents[:OVERLAP_DOCS]).lower()
    return any(re.search(rf"\b{re.escape(t)}\b", blob) for t in tokens)


def is_weak_match(
    distances: list[float] | None,
    query: str,
    documents: list[str] | None,
) -> bool:
    """Sonuçlar sorguyla gerçekten alakasız mı?

    İKİ sinyal birden gerekiyor: en yakın sonuç uzak OLACAK **ve** sorgudaki
    hiçbir kelime bulunan tariflerde geçmeyecek. Tek sinyal yetmiyor, çünkü
    ikisi de tek başına yanılıyor (yukarıdaki ölçüme bakınız).

    Karar VERİLEMEYEN durumlarda (mesafe yok, sonuç yok) False döner — şüphede
    kalınca kullanıcının aleyhine davranmıyoruz.
    """
    if not distances:
        return False
    if distances[0] < COMMENTARY_MAX_DISTANCE:
        return False
    return not _has_lexical_overlap(query, documents or [])
