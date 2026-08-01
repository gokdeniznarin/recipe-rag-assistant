import os
import base64
import json
import time
from dotenv import load_dotenv
from google import genai
from google.genai import types

from logger import get_logger, log_duration, timed

log = get_logger("llm")

# .env dosyasındaki GEMINI_API_KEY'i yükle
load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# Free tier kotası MODEL BAŞINA veriliyor — 429 hatasının kendisi söylüyor:
#   quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier, quotaValue: 20
# "PerProjectPerModel": sayaç proje × model kırılımında tutuluyor, yani aynı API
# anahtarıyla her modelin ayrı 20 hakkı var. Tek bir modele bağlı kalmak, o
# modelin 20 isteği bitince tüm LLM özelliklerinin ölmesi demekti (kamera
# araması dahil). Sırayla denenen liste bunu çözüyor: 5 model = 5 ayrı havuz.
#
# İki akışın ilk iki sırası bilerek ÇAPRAZ. Kapasiteyi artırmıyor (zincir aşağı
# indikçe iki akış da aynı modellere ulaşıyor, toplam yine aynı); kazandırdığı
# şey boşa giden deneme: aynı modelle başlasalardı, 20 yorumdan sonra kamera
# aramasının İLK denemesi 429 yiyip bir ağ turu kaybederdi. Çapraz başlayınca
# her akış kendi taze havuzuyla başlıyor.
#
# ÖLÇÜM (2026-07-22, aynı prompt / projenin kendi test_photo.jpg'si):
#   model                  yorum      görsel
#   gemini-3.5-flash-lite   742 ms     867 ms
#   gemini-3.1-flash-lite   762 ms    1027 ms
#   gemini-2.5-flash       2771 ms    2483 ms
#   gemini-3.6-flash       5454 ms    3057 ms
#   gemini-3.5-flash      12374 ms    9483 ms
#
# Vision sırası bu ölçümle DÜZELTİLDİ. Önceki gerekçe "malzeme tanıma asıl
# görsel iş, daha güçlü model başta" idi ve gemini-3.5-flash ilk sıradaydı —
# ölçüm bu varsayımı çürüttü: beş model de aynı üç malzemeyi buluyor, ama o
# model 11 kat yavaş. Kamera araması 9.5sn → 0.87sn.
#
# Not: ücretsiz katmanda gecikmeler günden güne çok oynuyor (gemini-3.5-flash
# Faz 11b'de 5.17sn ölçülmüştü, bugün 12.4sn). Sıralama bugünün ölçümüne göre;
# mutlak değerlere değil, zaten var olan fallback zincirine güveniyoruz.
# Elenenler: gemini-2.5-flash-lite ve 2.0-flash-lite (Faz 11b).
# ÖLÇÜM (2026-07-28) — zincire eklenen iki model. Adaylar `client.models.list()`
# ile bulundu, tahmin edilmedi; sonra hem metin hem görselde çalıştırıldı:
#   gemini-3.1-flash-lite-preview   614 ms metin / 889 ms görsel  ✅ eklendi
#   gemini-3-flash-preview         3219 ms metin / 2251 ms görsel ✅ eklendi
#   gemini-2.0-flash / -lite       429 — ayrı kota havuzu DEĞİL
#   gemini-2.5-pro                 429 — ücretsiz katmanda hak yok
#   gemini-2.5-flash-lite          404 — hâlâ "yeni kullanıcılara kapalı"
# Sınıflandırıcı prompt'u yeni modellerde de doğrulandı (Faz 15f'nin 6 zor
# sorgusu): 3.1-flash-lite-preview 6/6.
#
# PREVIEW MODELLER BİLEREK ÖNDE DEĞİL: 3.1-flash-lite-preview aslında listenin
# EN HIZLISI (614 ms), ama preview modeller habersiz geri çekilebiliyor
# (gemini-2.5-flash-lite'ın başına tam bu geldi). Kararlı modeller önde, preview
# olanlar taşma kapasitesi olarak arkada. Geri çekilirlerse 404 dönerler ve
# zincir onları zaten sessizce atlar — yani en kötü ihtimalde bir ağ turu.
#
# 5 model → 7: akış başına günlük kapasite 100 → 140 istek.
#
# ⚠️ `gemini-3-flash-preview` EKLENDİ VE AYNI GÜN ÇIKARILDI: sabah 3219 ms
# ölçüldü, öğleden sonra **43793 ms**. 13 kat oynama. Kapasite kazancı, tek
# başına 44 saniyelik bir bekleme yaratabilecek bir modeli taşımaya değmiyor.
# Ölçümün TEK SEFERLİK yapılmasının yetmediğinin kanıtı olarak kayıtta duruyor.
COMMENTARY_MODELS = (
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.1-flash-lite-preview",
    "gemini-2.5-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
)
VISION_MODELS = (
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite-preview",
    "gemini-2.5-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
)

# Model başına zaman aşımı (SDK'nın `http_options.timeout`'u, MİLİSANİYE).
#
# ⚠️ BU BİR İSTEMCİ ZAMAN AŞIMI DEĞİL — SUNUCUYA GÖNDERİLEN BİR DEADLINE.
# Faz 22'de "50 → 93 ms'de koptu" ölçümü bunu istemci tarafı sanmıştı; yanlış
# okunmuş. Kısa değer aslında ANINDA 400 dönüyor. Süre dolduğunda ise istek
# istemcide kesilmiyor, Google **504 DEADLINE_EXCEEDED** döndürüyor — o yüzden
# 504 aşağıdaki atlama listesinde olmak ZORUNDA.
#
# 🔒 10 SANİYE BİR TERCİH DEĞİL, TABAN: Google'ın izin verdiği en küçük değer.
# Ölçüldü (2026-07-30): "Manually set deadline 6s is too short. Minimum allowed
# deadline is 10s." — 7/8/9 sn de reddediliyor, 10 sn kabul.
# DAHA KÜÇÜK BİR DEĞER YAZILIRSA her çağrı 400 INVALID_ARGUMENT alır; 400 bilerek
# atlanmayan bir hata olduğu için zincir ilk modelde ölür ve LLM'e bağlı HER
# ŞEY (yorum, sınıflandırıcı, malzeme tanıma, tabak analizi) anında çalışmaz
# hâle gelir. "Biraz kısalım" fikrini teste bağladık.
#
# Tabanda olduğumuz için yavaş bir günde modelin 10 sn'yi aşması olağan; bu bir
# arıza değil, zincirin devreye girme sebebi (2026-07-30 canlı: ilk model 504,
# ikinci model cevapladı).
#
# NEDEN GEREKLİ: zincir bugüne kadar yalnızca "bu model KULLANILAMIYOR"
# (429/404/503) durumunda sonrakine geçiyordu. Yavaş ama sonunda cevap veren
# bir model hiçbir korumaya takılmıyordu ve her şeyi bloke ediyordu — canlıda
# ölçüldü: **AI yorumu 37.8 saniye**. Oysa zincirde 0.5 saniyede cevap veren
# modeller bekliyordu.
#
# 10 sn bilinçli: sağlıklı modeller 0.5–1.5 sn'de dönüyor, yani normal işleyişte
# hiç devreye girmiyor; ama patolojik bir modelde beklemeyi 44 sn yerine 10 sn
# ile sınırlıyor. FatSecret'taki LOOKUP_BUDGET_SEC ile aynı fikir.
MODEL_TIMEOUT_MS = 10_000


def _generate(models: tuple[str, ...], contents, config=None):
    """
    Modelleri sırayla dener. Yalnızca "bu model şu an kullanılamıyor" anlamına
    gelen hatalarda (kota dolu / model yok) sonrakine geçer — bozuk istek ya da
    ağ hatası gibi durumlarda denemeye devam etmek yanıltıcı olurdu, o yüzden
    onlar olduğu gibi yukarı fırlatılır.

    config: opsiyonel GenerateContentConfig. Sınıflandırıcı temperature=0
    veriyor (deterministik olsun); yorum/vision varsayılanı kullanıyor (None).
    """
    # Zaman aşımını çağıranın config'ine ENJEKTE ediyoruz — çağıranlar kendi
    # ayarlarını veriyor (sınıflandırıcı temperature=0, tabak analizi JSON modu)
    # ve onları ezmek istemiyoruz. model_copy: pydantic nesnesi, yerinde
    # değiştirmek çağıranın sabitini kirletirdi.
    http = types.HttpOptions(timeout=MODEL_TIMEOUT_MS)
    config = (
        types.GenerateContentConfig(http_options=http) if config is None
        else config.model_copy(update={"http_options": http})
    )

    last_error = None
    for model in models:
        # Her model denemesi ayrı ölçülüyor: hangi modelin ne kadar sürdüğü
        # (0.65sn vs 8.5sn) doğrudan log'dan okunabilsin. Ölçüm burada elle
        # yapılıyor çünkü timed_block başarısızlığı ERROR sayardı — oysa 429
        # alıp bir sonraki modele geçmek hata değil, planlanmış davranış.
        start = time.perf_counter()
        try:
            response = client.models.generate_content(
                model=model, contents=contents, config=config
            )
            log_duration(log, f"gemini {model}", (time.perf_counter() - start) * 1000, slow_ms=5000)
            return response
        except Exception as e:
            text = str(e)
            # 503/UNAVAILABLE de "bu modeli atla" demek: model kotası dolmamış,
            # o an aşırı yüklü. Eskiden bu listede YOKTU, dolayısıyla tek bir
            # 503 sıradaki 4 model hazır beklerken bütün isteği çöktürüyordu.
            # Faz 6'da ölçülmüştü: ücretsiz katmanda bir modelin sürekli 503
            # vermesi gerçek bir durum (o zaman SDK retry'ları aramayı 20 sn'ye
            # çıkarmıştı). Aday model testinde de 6 çağrının birinde görüldü.
            # Zaman aşımı da "bu modeli atla": sınıf ADINDAN bakılıyor, mesajdan
            # değil — httpx "The handshake operation timed out" diyor, yani
            # "timeout" kelimesi mesajda hiç geçmiyor ve dizgi araması kaçırırdı.
            #
            # ⚠️ AMA BU KONTROL BURADA NEREDEYSE HİÇ TETİKLENMİYOR — ölçüldü:
            # SDK `http_options.timeout`'u SUNUCUYA deadline olarak GÖNDERİYOR
            # (kanıt: 2000 ms verince Google "Manually set deadline 2s is too
            # short" diye 400 dönüyor). Yani süre dolduğunda istemci istemciyi
            # kesmiyor, sunucu **504 DEADLINE_EXCEEDED** döndürüyor. Bu yüzden
            # 504/DEADLINE_EXCEEDED de listede olmalı — 503'ün aynısı.
            timed_out = "timeout" in type(e).__name__.lower()
            unavailable = timed_out or any(
                s in text
                for s in ("429", "RESOURCE_EXHAUSTED", "404", "NOT_FOUND",
                          "503", "UNAVAILABLE", "504", "DEADLINE_EXCEEDED")
            )
            if not unavailable:
                raise
            # Hata değil: planlanmış geri çekilme. Ama sessiz de geçilmemeli —
            # kotanın dolduğu buradan görülüyor.
            log.warning("Model %s unavailable, falling back: %s", model, text[:120])
            last_error = e
    log.error("All models exhausted (%s)", ", ".join(models))
    raise last_error


@timed(slow_ms=5000)
def is_food_request(query: str) -> bool:
    """Sorgu bir yemek/tarif arayışı mı? Değilse arama hiç yapılmadan reddedilir.

    FAIL-OPEN: kota dolması, ağ hatası ya da model belirsiz bir cevap verirse
    True döner (yemek say) — yani sınıflandırıcı çökse bile arama çalışmaya
    devam eder, sadece eleme devre dışı kalır. Yanlışlıkla meşru bir sorguyu
    reddetmektense, nadiren saçma bir sorguyu geçirmeyi tercih ediyoruz.
    """
    # Prompt 4 modelde 6 zor sorguyla doğrulandı (2026-07-23). İki anahtar:
    #   1. "genel NİYETE bak, tek kelimeye değil" — yoksa lite model "turkey"i
    #      hindi, "swiss"i peynir sanıp coğrafya sorusunu yemek sayıyordu.
    #   2. açık örnek ("capital of Turkey" → NO) — bu tek satır Switzerland/
    #      Turkey/France sınıfının hepsini çözdü. "roast turkey for thanksgiving"
    #      YES kalıyor, yani kelimeye değil niyete bakıyor.
    prompt = f"""You are a filter for a recipe search app. Decide whether the user is trying to find food or recipes, based on the OVERALL INTENT of the message — not just individual words.

Answer YES if the user wants something to cook or eat: a dish, ingredient, cuisine, meal, or dietary preference. Vague ("easy", "dinner") and misspelled ("chiken") inputs still count as YES.

Answer NO if the message is a question or request about something OTHER than cooking — geography, general knowledge, technology, or random letters — EVEN IF it contains a word that can also be a food. For example "what is the capital of Turkey" is NO (turkey is the country here), "can you fix my car" is NO.

Reply with only the single word YES or NO.

Input: "{query}"
"""
    try:
        # temperature=0: sınıflandırma deterministik olmalı. Varsayılan sıcaklık
        # sınırdaki sorgularda ("does spain have good food?") aynı girdiye çağrı-
        # başı farklı YES/NO verdiriyordu. 0 bu rastgeleliği kaldırıyor. (Model
        # fallback zinciri hâlâ modeller arası fikir ayrılığına açık — bkz. yorum.)
        response = _generate(
            COMMENTARY_MODELS, prompt,
            config=types.GenerateContentConfig(temperature=0.0),
        )
        answer = (response.text or "").strip().upper()
        # Kesin "NO" değilse yemek say — belirsizlikte de kullanıcının lehine.
        is_food = not answer.startswith("NO")
        if not is_food:
            log.info("Classifier rejected non-food query: %r", query[:100])
        return is_food
    except Exception as e:
        log.warning("Food classifier unavailable, allowing query through: %s", e)
        return True


@timed(slow_ms=5000)
def generate_answer(user_query: str, recipes: list) -> str:
    """Bulunan tarifleri LLM'e verip doğal bir öneri cevabı üretir.

    Not: "bu sorgu yemek mi?" kontrolü artık burada değil — is_food_request
    aramadan önce yapıyor ve non-food sorgular buraya hiç ulaşmıyor.
    """

    recipes_text = "\n".join([
        f"- {r['name']}: {r['total_time_min']} min, {r['calories']} calories, "
        f"category: {r['category']}"
        for r in recipes
    ])

    prompt = f"""
You are a helpful recipe assistant. The user asked: "{user_query}"

Here are some matching recipes found in the database:
{recipes_text}

Pick the best matching recipe(s) and explain briefly why they fit the user's request.
Keep your answer concise (2-4 sentences). Respond in English.
"""

    response = _generate(COMMENTARY_MODELS, prompt)
    return response.text


@timed(slow_ms=5000)
def detect_ingredients_from_image(image_base64: str) -> list[str]:
    """Base64 formatındaki bir fotoğraftan malzeme listesi çıkarır."""

    # base64 string'i, gerekiyorsa "data:image/jpeg;base64," gibi bir önekten temizle
    if "," in image_base64:
        image_base64 = image_base64.split(",")[1]

    image_bytes = base64.b64decode(image_base64)

    prompt = """
Look at this photo and identify the food ingredients visible in it.
Respond with ONLY a comma-separated list of ingredient names in English, 
nothing else. Example: "chicken, bell pepper, onion, garlic"
If no food ingredients are visible, respond with "no ingredients detected".
"""

    response = _generate(VISION_MODELS, [
        {
            "inline_data": {
                "mime_type": "image/jpeg",
                "data": image_bytes
            }
        },
        prompt
    ])

    raw_text = (response.text or "").strip()

    if "no ingredients" in raw_text.lower():
        return []

    ingredients = [item.strip() for item in raw_text.split(",")]
    return ingredients


def _decode_image(image_base64: str) -> bytes:
    """base64 metnini bayta çevirir; "data:image/jpeg;base64," önekini temizler."""
    if "," in image_base64:
        image_base64 = image_base64.split(",")[1]
    return base64.b64decode(image_base64)


def _parse_plate_json(raw_text: str) -> list[dict]:
    """Vision'ın JSON çıktısını öğe listesine çevirir — SAVUNMACI.

    `response_mime_type="application/json"` istenmiş olsa bile modelin çıktıyı
    ```json çitiyle sarması ya da tek bir nesne (liste değil) döndürmesi mümkün.
    Bozuk çıktıda patlamak yerine boş liste dönüyoruz: çağıran bunu "yemek
    tanınamadı" olarak ele alıp anlaşılır bir mesaj gösteriyor.
    """
    text = (raw_text or "").strip()
    if not text:
        return []

    # ```json … ``` çitini soy
    if text.startswith("```"):
        text = text.split("```")[1] if "```" in text[3:] else text[3:]
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]

    try:
        data = json.loads(text.strip())
    except (ValueError, TypeError):
        log.warning("Could not parse plate JSON: %r", (raw_text or "")[:200])
        return []

    # {"items": [...]} beklenen biçim; model bazen doğrudan liste döndürüyor.
    if isinstance(data, dict):
        data = data.get("items", [])
    if not isinstance(data, list):
        return []

    return [item for item in data if isinstance(item, dict) and str(item.get("name", "")).strip()]


@timed(slow_ms=5000)
def analyze_plate_from_image(image_base64: str) -> list[dict]:
    """Fotoğraftaki yemekleri TANIR + porsiyonunu gram olarak TAHMİN eder.

    detect_ingredients_from_image'ın kardeşi ama farklı soruyu soruyor: orada
    "bu malzemelerle ne pişirebilirim" için ham malzeme adları lazım; burada
    "bu tabakta ne kadar var" için SERVİS EDİLDİĞİ HALİYLE yemek ve porsiyonu
    lazım. Aynı fotoğraf, iki farklı okuma.

    TEK ÇAĞRIDA BESİN TAHMİNİ DE İSTENİYOR (kota bilinçli bir karar): kota model
    başına günde 20 istek. Tanıma ve tahmin ayrı çağrılar olsaydı her fotoğraf
    iki hak yerdi. FatSecret erişilebiliyorsa bu tahminler zaten aranmış verinin
    yerine geçiyor (nutrition.build_plate) — yani ikinci çağrı çoğu zaman boşa
    gitmiş olurdu.
    """
    image_bytes = _decode_image(image_base64)

    prompt = """Look at this photo of food and identify each distinct food item you can see, as it is served.

For each item, estimate the portion size in grams as shown in the photo, and estimate its nutrition FOR THAT PORTION (not per 100g).

Rules:
- Name each item the way a nutrition database would label it: the plain food name, one or two words where possible, in English. No brand names.
- Leave out decorative words: colours, "fresh", "spicy", "assorted", "medley", "mix", "selection". They make the name unsearchable.
  "fresh red and yellow chilies" -> "chili pepper"
  "spicy bean sprout salad"      -> "bean sprouts"
  "white rice and grain mix"     -> "white rice"
  "mushroom medley"              -> "mushrooms"
- BUT keep a cooking method when it changes the nutrition ("grilled chicken breast", "fried egg", "boiled potato"). Drop it only when it is purely descriptive.
- If two different foods are on the plate, list them separately rather than inventing a combined name for them.
- List each KIND of food once. If there are several pieces of the same food (for example five cherry tomatoes), report them as a single item whose grams are the combined weight — never one entry per piece.
- If the photo contains no food at all, return an empty items list.

Respond with ONLY JSON in exactly this shape:
{"items": [{"name": "white rice", "grams": 180, "calories": 234, "protein_g": 4.9, "carbs_g": 50.6, "fat_g": 0.5}]}
"""

    response = _generate(
        VISION_MODELS,
        [
            {"inline_data": {"mime_type": "image/jpeg", "data": image_bytes}},
            prompt,
        ],
        # JSON modu: çıktıyı serbest metinden ayıklamaya çalışmak yerine modelden
        # doğrudan yapılandırılmış cevap istiyoruz. _parse_plate_json yine de
        # savunmacı — mime type bir garanti değil, bir talep.
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )

    return _parse_plate_json(response.text)


@timed(slow_ms=5000)
def read_barcode_from_image(image_base64: str) -> str | None:
    """Fotoğraftaki barkodun ALTINDA YAZAN rakamları okur. Yoksa None.

    NEDEN VAR — bu bir yedek yol: tarayıcının yerleşik `BarcodeDetector` API'si
    Chrome'da yalnızca Android, macOS ve ChromeOS'ta çalışıyor; Windows'ta ve
    iOS Safari'de HİÇ YOK. Tek yol o olsaydı özellik masaüstünde görünmezdi
    (ve geliştirme makinesinde test bile edilemezdi). Destek varsa istemci
    zaten kendi çözüyor ve buraya hiç gelinmiyor — yani bu çağrı, ve harcadığı
    kota, yalnızca desteğin olmadığı yerlerde ödeniyor.

    ÇUBUKLARI ÇÖZMÜYOR, RAKAMLARI OKUYOR: barkodun altında insan tarafından
    okunabilir hâli zaten basılı, yani bu bir görüntü çözme değil OCR işi ve
    modeller bunda iyi. Çubukları saydırmaya çalışmak (çizgi kalınlığı, açı,
    parlama) bir vision modelinin işi değil.

    YANLIŞ OKUMA RİSKİ KODDA KARŞILANIYOR: tek bir haneyi yanlış görmek burada
    sessizce BAŞKA BİR ÜRÜNÜ getirebilirdi. `nutrition.normalize_barcode` GTIN
    kontrol hanesini doğruluyor ve tek haneli okuma hatalarının tamamını
    yakalıyor — sonuç "yanlış ürün" değil "okunamadı" oluyor.
    """
    image_bytes = _decode_image(image_base64)

    prompt = """Look at this photo and find the product barcode in it.

Read the digits printed underneath the barcode and reply with ONLY those digits — no spaces, no dashes, no other words.
Most retail barcodes have 13 digits (EAN-13) or 12 digits (UPC-A).
If there is no barcode in the photo, or its digits are not clearly readable, reply with exactly: NONE
"""

    response = _generate(
        VISION_MODELS,
        [{"inline_data": {"mime_type": "image/jpeg", "data": image_bytes}}, prompt],
        # Transkripsiyon işi — yaratıcılık istemiyoruz, aynı fotoğraf her zaman
        # aynı rakamları vermeli. Sınıflandırıcıdaki temperature=0 kararının aynısı.
        config=types.GenerateContentConfig(temperature=0.0),
    )

    # ASCII rakam süzgeci: `str.isdigit()` Unicode'a duyarlı ve Arap-Hint
    # rakamlarını da geçirirdi; onlar kontrol hanesi aritmetiğine hiç girmemeli.
    digits = "".join(ch for ch in (response.text or "") if ch in "0123456789")
    if not digits:
        log.info("No barcode digits read from photo")
        return None
    return digits


# --- TEST ---
if __name__ == "__main__":
    # Test 1: Metin tabanlı cevap üretimi
    fake_recipes = [
        {"name": "Quick India Chicken", "total_time_min": 20, "calories": 315.7, "category": "Chicken Breast"},
        {"name": "Quick Chicken Soup", "total_time_min": 25, "calories": 390.1, "category": "Chicken Breast"},
    ]
    answer = generate_answer("quick chicken dinner", fake_recipes)
    print("LLM Answer:")
    print(answer)

    # Test 2: Fotoğraftan malzeme tanıma
    test_image_path = "test_photo.jpg"
    if os.path.exists(test_image_path):
        with open(test_image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")
        ingredients = detect_ingredients_from_image(image_data)
        print("\nDetected ingredients:", ingredients)
    else:
        print(f"\nTest image not found at {test_image_path}. Skipping image test.")