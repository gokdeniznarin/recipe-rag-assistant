import os
import base64
import time
from dotenv import load_dotenv
from google import genai

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
COMMENTARY_MODELS = (
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
)
VISION_MODELS = (
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
)


def _generate(models: tuple[str, ...], contents):
    """
    Modelleri sırayla dener. Yalnızca "bu model şu an kullanılamıyor" anlamına
    gelen hatalarda (kota dolu / model yok) sonrakine geçer — bozuk istek ya da
    ağ hatası gibi durumlarda denemeye devam etmek yanıltıcı olurdu, o yüzden
    onlar olduğu gibi yukarı fırlatılır.
    """
    last_error = None
    for model in models:
        # Her model denemesi ayrı ölçülüyor: hangi modelin ne kadar sürdüğü
        # (0.65sn vs 8.5sn) doğrudan log'dan okunabilsin. Ölçüm burada elle
        # yapılıyor çünkü timed_block başarısızlığı ERROR sayardı — oysa 429
        # alıp bir sonraki modele geçmek hata değil, planlanmış davranış.
        start = time.perf_counter()
        try:
            response = client.models.generate_content(model=model, contents=contents)
            log_duration(log, f"gemini {model}", (time.perf_counter() - start) * 1000, slow_ms=5000)
            return response
        except Exception as e:
            text = str(e)
            unavailable = any(
                s in text for s in ("429", "RESOURCE_EXHAUSTED", "404", "NOT_FOUND")
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
def generate_answer(user_query: str, recipes: list) -> str | None:
    """Bulunan tarifleri LLM'e verip doğal bir öneri cevabı üretir.

    Sorgu gerçek bir yemek isteği değilse None döner — çağıran taraf bunu
    zaten "yorum yok" olarak ele alıyor ve frontend kutuyu gizliyor.
    """

    recipes_text = "\n".join([
        f"- {r['name']}: {r['total_time_min']} min, {r['calories']} calories, "
        f"category: {r['category']}"
        for r in recipes
    ])

    # IRRELEVANT kuralı, mesafe eşiğinin (validation.is_weak_match) kaçırdığı
    # sınır durumlar için: eşiğin hemen altında kalan saçma sorgularda model
    # eskiden "bu rastgele harf dizisi gibi görünüyor, yine de şunu deneyin..."
    # diyen bir kutu üretiyordu. Modelin bu yargıyı zaten yaptığı canlıda
    # gözlendi; tek eksik onu yapılandırılmış biçimde istemekti.
    # Ek maliyeti YOK: aynı çağrının içinde, ek token/gecikme getirmiyor.
    prompt = f"""
You are a helpful recipe assistant. The user asked: "{user_query}"

Here are some matching recipes found in the database:
{recipes_text}

If the user's request is not a genuine food or recipe request (for example random
letters, keyboard mashing, or a question about an unrelated topic), reply with
exactly IRRELEVANT and nothing else.

Otherwise pick the best matching recipe(s) and explain briefly why they fit the
user's request. Keep your answer concise (2-4 sentences). Respond in English.
"""

    response = _generate(COMMENTARY_MODELS, prompt)
    answer = (response.text or "").strip()

    if answer.upper().startswith("IRRELEVANT"):
        log.warning("Model judged the query irrelevant: %r", user_query[:100])
        return None

    return answer


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