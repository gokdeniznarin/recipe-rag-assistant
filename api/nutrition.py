"""Besin değeri — fotoğraftaki yemeğin/malzemenin yaklaşık makro değerleri.

NEDEN AYRI BİR VERİ KAYNAĞI GEREKİYOR: elimizdeki besin verisi TARİF BAŞINA
(ChromaDB metadata'sındaki `calories`, `protein_content`, …). Kullanıcı bir elma
ya da restoranda bilmediğimiz bir tabak çekerse 9.795 tarifimizde karşılığı yok.
Faz 17'nin `ingredients` alanı da yalnızca İSİM taşıyor, besin değeri değil.
Yani GIDA BAŞINA bir tabloya ihtiyaç var — bu modül onu FatSecret'tan alıyor.

İKİ KAYNAK, TEK AKIŞ (fail-open — is_food_request'teki desen):
    1. Gemini vision tabağı tanıyor + porsiyonu gram olarak tahmin ediyor ve
       kendi kaba besin tahminini de aynı çağrıda veriyor (llm.analyze_plate).
    2. FatSecret erişilebiliyorsa sayılar ORADAN geliyor (aranmış veri), Gemini'nin
       yalnızca porsiyon tahmini kullanılıyor.
    3. FatSecret yoksa / anahtar tanımlı değilse / hata verirse Gemini'nin kendi
       sayılarına düşülüyor. Özellik KIRILMIYOR, sadece sayıların kaynağı değişiyor.

Fark önemli ve kullanıcıya da söyleniyor (`source` alanı): LLM'in sayısı
*üretilmiş* (aynı fotoğrafa farklı cevap verebilir, doğrulanamaz), FatSecret'ın
sayısı *aranmış* ve kaynağı gösterilebilir.

NEDEN OAuth 1.0 (2-legged), OAuth 2.0 DEĞİL — bu, işi yapılabilir kılan detay:
FatSecret'ın OAuth 2.0 akışı en az bir IP'nin whitelist'e alınmasını ŞART koşuyor.
Render'ın ücretsiz katmanında sabit giden IP YOK (paylaşımlı CIDR; dedicated IP
Pro plan). Yani OAuth 2.0 yolu bizim için kapalı. OAuth 1.0'da IP kısıtı yok —
her istek Consumer Secret ile İMZALANIYOR (HMAC-SHA1) ve imza gerçekliği
kanıtladığı için IP kilidine gerek kalmıyor.

BAĞIMLILIK EKLENMEDİ: imzalama `hmac`/`hashlib`/`base64`, istek `urllib.request`
— hepsi standart kütüphane.

⚠️ ATIF ZORUNLU: FatSecret'ın ücretsiz katmanı, veriyi kullanan uygulamanın
görünür bir yerde atıf vermesini şart koşuyor (Amazon Associates açıklaması
gibi). `ATTRIBUTION` sabiti bu yüzden yanıtta dönüyor ve frontend onu basıyor —
FatSecret verisi kullanıldığı sürece kaldırılmamalı.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from logger import get_logger, log_duration

log = get_logger("nutrition")

FATSECRET_URL = "https://platform.fatsecret.com/rest/server.api"

# Atıf metni — FatSecret ücretsiz katman sözleşmesinin şartı.
ATTRIBUTION = "Nutrition data from FatSecret Platform API."

# Zaman aşımı KISA olmalı: FatSecret takılırsa isteği bekletmek yerine Gemini
# tahminine düşmek istiyoruz (fail-open). Render'da kullanıcı zaten vision
# çağrısını bekliyor, üstüne yavaş bir dış servis binmemeli.
HTTP_TIMEOUT_SEC = 6

# Tabaktaki öğe sayısı sınırı. Her öğe en az bir FatSecret HTTP çağrısı demek;
# sınırsız bırakılırsa tek fotoğraf onlarca ağ turuna dönüşebilir.
MAX_ITEMS = 8

# TÜM arama turlarının toplam zaman bütçesi (istek başına).
#
# NEDEN GEREKLİ: tek başına zaman aşımı yetmiyor. Her öğe diğerinden BAĞIMSIZ
# olarak yeniden deniyor, yani FatSecret takılırsa 8 öğe × 2 çağrı × 6 sn =
# ~96 sn boyunca kullanıcı bekler — üstüne vision'ın ~8 sn'si biner. Devre
# kesici olmadan tek bir yavaş dış servis bütün isteği rehin alıyor.
#
# Bütçe dolunca kalan öğeler Gemini tahminine düşüyor — yani zaten var olan
# fail-open davranışının aynısı, sadece tetikleyicisi "hata" değil "yavaşlık".
# Normal işleyişte hiç devreye girmiyor: gerçek çağrılar ~200-500 ms.
LOOKUP_BUDGET_SEC = 10.0

# Porsiyon sınırları. İKİ AYRI TAVAN VAR ve karıştırılmamalı:
#   MAX_GRAMS       — tek bir PARÇA için makul üst sınır ("2500 g'lık tek domates"
#                     model hatasıdır)
#   MAX_TOTAL_GRAMS — birleştirme SONRASI toplam için sınır. Daha yüksek, çünkü
#                     10 dilim pizza toplamı meşru biçimde 2000 g olabilir.
MIN_GRAMS = 1.0
MAX_GRAMS = 1500.0
MAX_TOTAL_GRAMS = 3000.0
DEFAULT_GRAMS = 150.0

# Yanıtta kullanılan makro anahtarları. Tek yerde duruyor ki toplama, ölçekleme
# ve boş-değer üretimi birbirinden ayrışmasın.
MACRO_KEYS = ("calories", "protein_g", "carbs_g", "fat_g")


# ═══════════════════════════════════════════════════════════
#  SAF FONKSİYONLAR (ağ yok — Katman 1'de mock'suz test ediliyor)
# ═══════════════════════════════════════════════════════════

def empty_macros() -> dict:
    return {key: 0.0 for key in MACRO_KEYS}


def _finite(value) -> float | None:
    """float'a çevirir; sayı değilse ya da NaN/sonsuzsa None."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def piece_grams(value) -> float:
    """TEK BİR PARÇANIN gramı. Kullanılamazsa **0** döner.

    Neden 0 ve neden "tipik porsiyon" DEĞİL: bu fonksiyon yalnızca birleştirme
    sırasında, yani aynı gıdanın birden çok parçası varken çağrılıyor. Bozuk bir
    parçaya varsayılan bir ağırlık uydurmak toplamı ŞİŞİRİR — oysa kardeş
    parçalar ölçeği zaten taşıyor. Uydurmak yerine o parçayı hesaba katmıyoruz.

    Aralık dışı değerler de (99999 g) 0 sayılıyor: model hatası olduğu açık ve
    tek bir uçuk parça bütün öğeyi ele geçirmemeli.
    """
    grams = _finite(value)
    if grams is None or grams < MIN_GRAMS or grams > MAX_GRAMS:
        return 0.0
    return grams


def plate_grams(value) -> float:
    """BİRLEŞTİRME SONRASI gram — ölçeklemede kullanılan nihai değer.

    piece_grams'tan KRİTİK FARKI: fazla büyük bir toplam varsayılana
    DÜŞÜRÜLMEZ, tavana ÇEKİLİR. Düşürmek sessiz ve büyük bir hataydı: 10 dilim
    pizzanın meşru 2000 g'lık toplamı 150 g'a iniyordu ve FatSecret yolunda gram
    doğrudan ÇARPAN olduğu için besin değeri 13 kat eksik çıkıyordu.

    Hiç kullanılabilir parça yoksa (toplam 0) varsayılana düşülüyor — orada
    gerçekten elimizde bilgi yok, tahmin etmekten başka seçenek kalmıyor.
    """
    grams = _finite(value)
    if grams is None or grams < MIN_GRAMS:
        return DEFAULT_GRAMS
    return min(grams, MAX_TOTAL_GRAMS)


def canonical_food_name(name: str) -> str:
    """Tekilleştirme anahtarı: küçük harf + kelime bazında kaba tekilleştirme.

    pantry.canonical_ingredient ile aynı FİKİR ama BİLEREK KOPYA: pantry.py
    import anında `firestore.client()` çağırıyor, yani onu buraya import etmek
    besin değeri modülüne gereksiz bir Firestore bağımlılığı takardı (ve bu
    modülün import anında yan etkisiz kalması gerekiyor — bkz. conftest.py).
    İhtiyaç duyulan kural da orada olduğundan çok daha dar.
    """
    words = (name or "").strip().lower().split()
    singular = []
    for word in words:
        if word.endswith("ies") and len(word) > 4:
            singular.append(word[:-3] + "y")        # berries → berry
        elif word.endswith("ss") or len(word) <= 2:
            singular.append(word)                   # glass, swiss — çoğul değil
        elif word.endswith("es") and len(word) > 3:
            singular.append(word[:-2])              # tomatoes → tomato
        elif word.endswith("s"):
            singular.append(word[:-1])              # eggs → egg
        else:
            singular.append(word)
    return " ".join(singular)


def merge_duplicate_items(detected_items: list[dict]) -> list[dict]:
    """Aynı yemeği birden çok kez listeleyen çıktıyı tek satıra indirir.

    GERÇEK BİR MODEL DAVRANIŞI, teorik bir önlem değil: test fotoğrafında vision
    aynı tabaktaki kirazdomatesleri "cherry tomato" adıyla BEŞ AYRI öğe olarak
    döndürdü (25 g + 15 g + 10 g + 20 g + 25 g). Sonucu üç ayrı yerden bozuyordu:
      1. arayüzde beş özdeş satır,
      2. MAX_ITEMS bütçesinin tek bir gıdaya harcanması,
      3. FatSecret'a aynı sorgu için beş ayrı istek.

    Prompt de bunu söylemesin diye sıkılaştırıldı, ama prompt bir GARANTİ DEĞİL
    (model davranışı sürüm sürüm değişiyor — Faz 14'te tam bunu yaşadık), o
    yüzden asıl koruma burada, kodda.

    Gramlar ve makrolar TOPLANIYOR: her ikisi de o porsiyona ait mutlak
    değerler, yani beş domatesin toplamı doğru cevap.
    """
    merged: dict[str, dict] = {}
    order: list[str] = []

    for raw in detected_items or []:
        name = str(raw.get("name", "")).strip()
        if not name:
            continue

        key = canonical_food_name(name)
        if key not in merged:
            # İlk görülen yazım korunuyor (kullanıcıya gösterilen ad).
            merged[key] = {"name": name, "grams": 0.0, **empty_macros()}
            order.append(key)

        target = merged[key]
        # Parça bazında sağlama: bozuk/uçuk bir parça 0 sayılıyor, böylece tek
        # bir hatalı değer sağlıklı kardeşlerini götürmüyor.
        target["grams"] += piece_grams(raw.get("grams"))
        for macro in MACRO_KEYS:
            try:
                target[macro] += float(raw.get(macro) or 0.0)
            except (TypeError, ValueError):
                continue

    # Toplam 0 kalmış olabilir (hepsi bozuk geldiyse); son sözü plate_grams
    # söylüyor ve orada varsayılana düşülüyor.
    return [merged[key] for key in order]


def scale_macros(per_100g: dict, grams: float) -> dict:
    """100 gramlık değerleri verilen porsiyona ölçekler.

    plate_grams kullanıyor (piece_grams DEĞİL): buraya gelen değer birleştirme
    sonrası toplam ve gram burada doğrudan ÇARPAN — büyük bir toplamı varsayılana
    düşürmek besin değerini sessizce eksik gösterirdi.
    """
    factor = plate_grams(grams) / 100.0
    scaled = {}
    for key in MACRO_KEYS:
        try:
            value = float(per_100g.get(key, 0.0) or 0.0)
        except (TypeError, ValueError):
            value = 0.0
        scaled[key] = round(value * factor, 1)
    return scaled


def total_macros(items: list[dict]) -> dict:
    """Tabaktaki öğelerin makro toplamı."""
    totals = empty_macros()
    for item in items:
        for key in MACRO_KEYS:
            try:
                totals[key] += float(item.get(key, 0.0) or 0.0)
            except (TypeError, ValueError):
                continue
    return {key: round(value, 1) for key, value in totals.items()}


def overall_source(items: list[dict]) -> str:
    """Tabağın bütünü için tek bir kaynak etiketi.

    Öğelerin bir kısmı FatSecret'ta bulunup bir kısmı bulunamayabilir; kullanıcıya
    "kaynak" derken bunu gizlememek gerekiyor, o yüzden karışık durumun ayrı bir
    adı var ("mixed") ve arayüz o zaman iki kaynağı da söylüyor.
    """
    if not items:
        return "estimate"
    sources = {item.get("source", "estimate") for item in items}
    if sources == {"fatsecret"}:
        return "fatsecret"
    if "fatsecret" in sources:
        return "mixed"
    return "estimate"


# ── FatSecret yanıt ayrıştırma ────────────────────────────

def as_list(value) -> list:
    """FatSecret tek sonuçta DİZİ DEĞİL doğrudan nesne döndürüyor.

    Klasik bir tuzak: `foods.food` iki sonuçta liste, tek sonuçta sözlük geliyor
    (aynısı `servings.serving` için de geçerli). Bunu tek yerde normalize
    etmezsek çağıran her yerde `isinstance` kontrolü gerekirdi ve biri
    unutulduğunda hata ancak "tam olarak bir sonuç dönen" sorgularda ortaya
    çıkardı — yani en zor yakalanan türden.
    """
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


# "Per 100g - Calories: 165kcal | Fat: 3.57g | Carbs: 0.00g | Protein: 31.02g"
_DESCRIPTION_RE = re.compile(
    r"per\s+(?P<amount>[\d.]+)\s*(?P<unit>g|ml)\b.*?"
    r"calories:\s*(?P<calories>[\d.]+)\s*kcal.*?"
    r"fat:\s*(?P<fat>[\d.]+)\s*g.*?"
    r"carbs:\s*(?P<carbs>[\d.]+)\s*g.*?"
    r"protein:\s*(?P<protein>[\d.]+)\s*g",
    re.IGNORECASE | re.DOTALL,
)


def parse_food_description(description: str) -> dict | None:
    """`food_description` metninden 100 g'lık makroları çıkarır.

    NEDEN BU YOL VAR (bir HTTP turu tasarrufu): `foods.search` yanıtı zaten bu
    özet metni içeriyor. Metrik bir porsiyona ("Per 100g") dayanıyorsa ikinci bir
    `food.get` çağrısına gerek kalmıyor — öğe başına 2 istek yerine 1. Sekiz
    öğelik bir tabakta bu 16 değil 8 ağ turu demek.

    Metrik olmayan açıklamalarda ("Per 1 medium") None dönüyor; o zaman çağıran
    `food.get`'e düşüp gerçek gram karşılığını okuyor.
    """
    match = _DESCRIPTION_RE.search(description or "")
    if not match:
        return None

    try:
        amount = float(match.group("amount"))
    except (TypeError, ValueError):
        return None
    if amount <= 0:
        return None

    factor = 100.0 / amount
    return {
        "calories": round(float(match.group("calories")) * factor, 1),
        "protein_g": round(float(match.group("protein")) * factor, 1),
        "carbs_g": round(float(match.group("carbs")) * factor, 1),
        "fat_g": round(float(match.group("fat")) * factor, 1),
    }


def macros_from_serving(serving: dict) -> dict | None:
    """Bir `serving` kaydından 100 g'lık makrolar.

    Yalnızca METRİK porsiyonlar kullanılıyor (`metric_serving_amount` + birim
    g/ml): "1 medium" gibi bir porsiyonun kaç gram olduğunu bilmeden 100 g'a
    normalize etmek mümkün değil.
    """
    if not isinstance(serving, dict):
        return None

    unit = str(serving.get("metric_serving_unit", "")).strip().lower()
    if unit not in ("g", "ml"):
        return None

    try:
        amount = float(serving.get("metric_serving_amount"))
    except (TypeError, ValueError):
        return None
    if amount <= 0:
        return None

    factor = 100.0 / amount

    def value(key: str) -> float:
        try:
            return round(float(serving.get(key, 0.0) or 0.0) * factor, 1)
        except (TypeError, ValueError):
            return 0.0

    return {
        "calories": value("calories"),
        "protein_g": value("protein"),
        "carbs_g": value("carbohydrate"),
        "fat_g": value("fat"),
    }


def pick_serving(servings: list) -> dict | None:
    """Metrik bilgisi olan ilk porsiyonu seçer (100 g'a normalize edilebilen)."""
    for serving in as_list(servings):
        if macros_from_serving(serving) is not None:
            return serving
    return None


# "Green Chili Peppers (Canned)" → parantez içi bir İŞLENME DURUMU bildiriyor.
_QUALIFIER_RE = re.compile(r"\s*\([^)]*\)")


def _strip_qualifier(name: str) -> str:
    return _QUALIFIER_RE.sub("", name or "").strip()


_NON_WORD_RE = re.compile(r"[^a-z0-9]+")


def food_tokens(name: str) -> set[str]:
    """Bir gıda adının kelime kümesi (tekilleştirilmiş).

    Noktalama AYRAÇ sayılıyor: "Chinese Cabbage (Bok-Choy, Pak-Choi)" içindeki
    "Bok-Choy" tireli tek kelime olarak kalsaydı `choy` hiç görünmezdi ve doğru
    eşleşme reddedilirdi.
    """
    cleaned = _NON_WORD_RE.sub(" ", (name or "").lower())
    return set(canonical_food_name(cleaned).split())


def head_noun(name: str) -> str:
    """Adın ANA İSMİ — İngilizce'de son kelime.

    "hot chili PEPPER" bir biber, "chili pepper FRITTER" bir kızartma. İkisi de
    sorgunun bütün kelimelerini içeriyor, yani kelime örtüşmesi bunları ayırt
    edemiyor; ayıran şey hangi yemek oldukları, o da son kelimede.
    Parantez içi atılıyor: nitelik değil, asıl adın son kelimesi aranıyor.
    """
    words = canonical_food_name(_strip_qualifier(name)).split()
    return words[-1] if words else ""


def score_food(food: dict, query: str = "") -> int:
    """Bir arama sonucunun uygunluk puanı (yüksek olan seçilir).

    FatSecret'ın kendi alaka sırası TEK BAŞINA YETMİYOR — canlı sorgularda
    ölçüldü:
      "grilled chicken breast" → 1. "Skinless Chicken Breast",
                                 2. "Grilled Chicken Breast"  ← sorgunun AYNISI
      "green chili pepper"     → 1. "Green Chili Peppers (Canned)",
                                 2. "Green Hot Chili Peppers"  ← taze olan
    Yani ilk sonucu almak hem tam eşleşmeyi kaçırıyor hem de fotoğrafta
    görünmeyen bir işlenme durumunu (konserve) seçebiliyor.
    """
    name = str(food.get("food_name", ""))
    score = 0

    # Markalı kayıt: fotoğraftan tanınan şey bir ürün değil bir yemek. Bir
    # zincir restoranın kendi tavuğu tabaktakini temsil etmiyor.
    if str(food.get("brand_name", "")).strip():
        score -= 100

    # Parantezli nitelik ("(Canned)", "(Cooked, Fat Added)") fotoğrafın
    # söylemediği bir hazırlanış biçimi varsayar. Sade kayıt daha güvenli.
    if "(" in name:
        score -= 10

    # Sorgunun birebir karşılığı varsa en güçlü sinyal o. Karşılaştırma
    # canonical_food_name üzerinden: "Green Chili Peppers" ↔ "green chili pepper"
    # (çoğul farkı eşleşmeyi bozmasın).
    if query and canonical_food_name(_strip_qualifier(name)) == canonical_food_name(query):
        score += 5

    # Aynı ANA İSİM: "chili pepper" için hem "Hot Chili Pepper" hem "Chili Pepper
    # Fritter" sorgunun tüm kelimelerini içeriyor ve ikisi de tam eşleşme DEĞİL,
    # yani puanları eşitti ve karar FatSecret'ın sırasına kalıyordu — kızartma
    # kazanıyordu. Ana isim ikisini ayırıyor (pepper vs fritter).
    if query and head_noun(name) and head_noun(name) == head_noun(query):
        score += 3

    return score


def pick_best_food(foods: list, query: str = "") -> dict | None:
    """Arama sonuçlarından en uygun gıdayı seçer (bkz. score_food).

    `max` ilk en büyüğü döndürdüğü için EŞİT PUANDA FatSecret'ın kendi alaka
    sırası korunuyor — puanlama ayırt etmediğinde onun sıralamasına güveniyoruz.
    """
    candidates = [f for f in as_list(foods) if isinstance(f, dict)]
    if not candidates:
        return None
    return max(candidates, key=lambda food: score_food(food, query))


# ── OAuth 1.0 imzalama (saf — sabit nonce/timestamp ile test edilebilir) ──

def percent_encode(value) -> str:
    """RFC 3986 yüzde-kodlaması.

    `urllib.parse.quote`'un varsayılan `safe='/'` değeri OAuth için YANLIŞ:
    bölü işareti kaçırılmazsa imza tabanı yanlış kurulur ve sunucu isteği
    reddeder. Kaçırılmayacak tek küme `-._~`.
    """
    return urllib.parse.quote(str(value), safe="-._~")


def signature_base_string(method: str, url: str, params: dict) -> str:
    """OAuth 1.0 imza tabanı: METHOD & url & sıralı-parametreler.

    Parametreler önce ANAHTARA, eşitlik durumunda DEĞERE göre sıralanıyor
    (spec böyle diyor). Sunucu aynı tabanı kendi kurup imzayı doğruladığı için
    sıralamadaki en küçük sapma "invalid signature" demek.
    """
    normalized = "&".join(
        f"{percent_encode(k)}={percent_encode(v)}"
        for k, v in sorted(params.items(), key=lambda kv: (str(kv[0]), str(kv[1])))
    )
    return "&".join([method.upper(), percent_encode(url), percent_encode(normalized)])


def sign(base_string: str, consumer_secret: str, token_secret: str = "") -> str:
    """HMAC-SHA1 imzası (base64).

    2-legged akışta kullanıcı token'ı yok, dolayısıyla imzalama anahtarı
    "consumer_secret&" — sondaki & ŞART, spec anahtarı iki parçanın birleşimi
    olarak tanımlıyor ve boş ikinci parça da yazılıyor.
    """
    key = f"{percent_encode(consumer_secret)}&{percent_encode(token_secret)}".encode()
    digest = hmac.new(key, base_string.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def build_signed_params(
    method_params: dict,
    consumer_key: str,
    consumer_secret: str,
    nonce: str | None = None,
    timestamp: str | None = None,
) -> dict:
    """İmzalanmış tam parametre kümesi.

    nonce/timestamp dışarıdan verilebiliyor — testlerin imzayı sabitleyebilmesi
    için (aksi halde her çağrı farklı imza üretir ve doğrulanamaz).
    """
    params = {
        **method_params,
        "oauth_consumer_key": consumer_key,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": timestamp or str(int(time.time())),
        "oauth_nonce": nonce or uuid.uuid4().hex,
        "oauth_version": "1.0",
        "format": "json",
    }
    base = signature_base_string("GET", FATSECRET_URL, params)
    return {**params, "oauth_signature": sign(base, consumer_secret)}


# ═══════════════════════════════════════════════════════════
#  FATSECRET İSTEMCİSİ (ağ)
# ═══════════════════════════════════════════════════════════

def credentials() -> tuple[str, str] | None:
    """(consumer_key, consumer_secret) ya da anahtar tanımlı değilse None.

    HER ÇAĞRIDA OKUNUYOR, import anında değil: modül import edilirken ortam
    değişkenine bakmak, testlerin anahtarı sonradan ayarlamasını imkânsız
    kılardı. Ayrıca bu modülün import anında HİÇBİR yan etkisi olmaması gerekiyor
    (bkz. conftest.py'deki import-anı yan etkileri notu).

    ⚠️ Secret ASLA frontend'e girmiyor: yerelde `.env`, canlıda Render env var'ı;
    imzalama yalnızca burada, sunucuda yapılıyor.
    """
    key = (os.getenv("FATSECRET_CONSUMER_KEY") or "").strip()
    secret = (os.getenv("FATSECRET_CONSUMER_SECRET") or "").strip()
    if not key or not secret:
        return None
    return key, secret


def _call(method_params: dict) -> dict | None:
    """İmzalı bir FatSecret çağrısı. Başarısızlıkta None (fail-open).

    HİÇBİR HATA YUKARI FIRLATILMIYOR: bu servis özelliğin ZORUNLU parçası değil,
    iyileştiricisi. Anahtar yoksa, kota dolmuşsa, ağ takılmışsa ya da yanıt
    bozuksa çağıran Gemini tahminine düşüyor. Bir dış servisin kötü günü
    yüzünden kullanıcı hiçbir şey görememeli.
    """
    creds = credentials()
    if not creds:
        return None

    params = build_signed_params(method_params, *creds)
    url = f"{FATSECRET_URL}?{urllib.parse.urlencode(params)}"

    start = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT_SEC) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
        log.warning("FatSecret call failed (%s), falling back to estimate: %s",
                    method_params.get("method"), e)
        return None

    log_duration(log, f"fatsecret {method_params.get('method')}",
                 (time.perf_counter() - start) * 1000, slow_ms=2000)

    # FatSecret hataları HTTP 200 gövdesinde `error` olarak dönüyor (geçersiz
    # imza, kota vb.) — yani durum kodu kontrolü yetmiyor.
    if isinstance(payload, dict) and "error" in payload:
        log.warning("FatSecret error response: %s", str(payload["error"])[:200])
        return None
    return payload


def lookup_macros(food_name: str) -> dict | None:
    """Bir gıda adının 100 g'lık makroları — bulunamazsa None.

    İKİ ADIM, AMA ÇOĞUNLUKLA TEK İSTEK:
      1. `foods.search` → en uygun kayıt. Yanıttaki `food_description` metrik bir
         porsiyona dayanıyorsa iş burada bitiyor.
      2. Değilse (`Per 1 medium` gibi) `food.get` ile gerçek porsiyon tablosu
         okunup metrik bir porsiyon aranıyor.
    """
    name = (food_name or "").strip()
    if not name:
        return None

    payload = _call({"method": "foods.search", "search_expression": name, "max_results": "5"})
    if not payload:
        return None

    foods = (payload.get("foods") or {}).get("food")
    best = pick_best_food(foods, name)
    if not best:
        log.info("FatSecret has no match for %r", name[:60])
        return None

    # ALAKA TABANI — en iyi aday bile sorgunun ANA İSMİNİ hiç içermiyorsa bu bir
    # eşleşme değil, sadece "en az kötü" sonuç. FatSecret anahtar kelime araması
    # yapıyor ve elindeki hiçbir şey uymadığında yine de bir şeyler döndürüyor:
    # "bean sprouts" sorgusuna beş farklı FASULYE dönüyor, hiçbirinde "sprout"
    # geçmiyor. Onu kabul etmek, yanlış bir sayıyı "aranmış veri" etiketiyle
    # göstermek olurdu — dürüst bir tahminden DAHA KÖTÜ, çünkü kullanıcı
    # doğrulanmış sanıyor. None dönünce çağıran Gemini tahminine düşüyor ve
    # arayüz 'estimated' rozetini gösteriyor.
    #
    # Kontrol TAM ad üzerinden (parantez DAHİL): eşanlamlılar orada duruyor —
    # "Chinese Cabbage (Bok-Choy, Pak-Choi)" bok choy'un DOĞRU karşılığı ve ana
    # adında 'choy' hiç geçmiyor. Yalnızca ana ada baksaydık onu reddederdik.
    head = head_noun(name)
    if head and head not in food_tokens(best.get("food_name", "")):
        log.info("FatSecret match %r rejected for %r (no %r in it)",
                 best.get("food_name", "")[:60], name[:60], head)
        return None

    from_description = parse_food_description(best.get("food_description", ""))
    if from_description:
        return {**from_description, "matched_food": best.get("food_name", name)}

    food_id = best.get("food_id")
    if not food_id:
        return None

    detail = _call({"method": "food.get", "food_id": str(food_id)})
    if not detail:
        return None

    servings = ((detail.get("food") or {}).get("servings") or {}).get("serving")
    serving = pick_serving(servings)
    if not serving:
        # Kayıt var ama metrik porsiyonu yok — gram bazlı ölçekleme yapılamaz.
        log.info("FatSecret match for %r has no metric serving", name[:60])
        return None

    macros = macros_from_serving(serving)
    return {**macros, "matched_food": best.get("food_name", name)}


# ═══════════════════════════════════════════════════════════
#  TABAK BİRLEŞTİRME
# ═══════════════════════════════════════════════════════════

def build_plate(detected_items: list[dict]) -> dict:
    """Vision'ın tanıdığı öğeleri besin değeri tablosuna çevirir.

    `detected_items` her öğe için şunları taşıyor (llm.analyze_plate_from_image):
        {name, grams, calories, protein_g, carbs_g, fat_g}
    Son dördü Gemini'nin KENDİ tahmini — FatSecret'tan veri gelirse onun yerine
    aranmış değerler kullanılıyor, gelmezse bu tahmin korunuyor. Porsiyon (gram)
    her durumda Gemini'den geliyor; FatSecret fotoğrafa bakamaz.
    """
    # TEKİLLEŞTİRME ÖNCE, kırpma SONRA: sırası tersine olsaydı aynı gıdanın
    # tekrarları MAX_ITEMS bütçesini yiyip gerçekten farklı yemekleri dışarıda
    # bırakırdı (beş kirazdomatesi sekiz öğelik bütçenin beşini harcıyordu).
    items = []
    deadline = time.perf_counter() + LOOKUP_BUDGET_SEC
    budget_spent = False

    for raw in merge_duplicate_items(detected_items)[:MAX_ITEMS]:
        name = str(raw.get("name", "")).strip()
        if not name:
            continue

        grams = plate_grams(raw.get("grams"))

        # Bütçe dolduysa aramayı BIRAKIYORUZ ve kalan öğeler tahmine düşüyor.
        # Yavaş bir dış servis, kullanıcıyı dakikalarca bekletmek yerine
        # yalnızca sayıların kaynağını değiştiriyor.
        if time.perf_counter() < deadline:
            looked_up = lookup_macros(name)
        else:
            if not budget_spent:
                log.warning(
                    "FatSecret lookup budget (%.0fs) spent; remaining items fall back to estimates",
                    LOOKUP_BUDGET_SEC,
                )
                budget_spent = True
            looked_up = None

        if looked_up:
            macros = scale_macros(looked_up, grams)
            source = "fatsecret"
            matched = looked_up.get("matched_food", name)
        else:
            # Gemini'nin tahmini ZATEN porsiyona göre verilmiş (100 g'lık değil),
            # o yüzden ölçeklenmiyor — yalnızca sayısallaştırılıyor.
            macros = {}
            for key in MACRO_KEYS:
                try:
                    macros[key] = round(float(raw.get(key, 0.0) or 0.0), 1)
                except (TypeError, ValueError):
                    macros[key] = 0.0
            source = "estimate"
            matched = None

        items.append({
            "name": name,
            "grams": round(grams),
            "source": source,
            "matched_food": matched,
            **macros,
        })

    source = overall_source(items)
    return {
        "items": items,
        "totals": total_macros(items),
        "source": source,
        # Atıf YALNIZCA FatSecret verisi gerçekten kullanıldığında dönüyor —
        # her yanıta koymak, tahminle üretilmiş sayılara da o kaynağı atfetmek
        # olurdu (sözleşmenin istediğinin tersi: yanıltıcı atıf).
        "attribution": ATTRIBUTION if source in ("fatsecret", "mixed") else None,
    }
