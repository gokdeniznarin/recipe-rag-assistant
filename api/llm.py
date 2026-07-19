import os
import base64
from dotenv import load_dotenv
from google import genai

# .env dosyasındaki GEMINI_API_KEY'i yükle
load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# Free tier kotası MODEL BAŞINA veriliyor — 429 hatasının kendisi söylüyor:
#   quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier, quotaValue: 20
# Tek bir modele bağlı kalmak, o modelin günlük 20 isteği bitince tüm LLM
# özelliklerinin ölmesi demekti (kamera araması dahil). Bunun yerine sırayla
# denenen bir liste tutuyoruz: baştaki model kotasını doldurursa bir sonrakine
# geçiliyor, yani pratikte 3 ayrı kota havuzu.
#
# İki akış farklı sırayla gidiyor ki biri diğerinin kotasını tüketmesin:
# yorum hafif bir iş (2-4 cümle), en hızlı modelle başlıyor; malzeme tanıma
# ise asıl işi yapan görsel analiz, daha güçlü modelle başlıyor.
#
# Ölçüm (aynı yorum promptu): gemini-3.1-flash-lite 0.65sn, gemini-3.5-flash
# 5.17sn, gemini-2.5-flash ~8.5sn. gemini-2.5-flash-lite ve 2.0-flash-lite
# elendi (sırasıyla "no longer available to new users" ve kota paylaşımı).
COMMENTARY_MODELS = ("gemini-3.1-flash-lite", "gemini-3.5-flash", "gemini-2.5-flash")
VISION_MODELS = ("gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-2.5-flash")


def _generate(models: tuple[str, ...], contents):
    """
    Modelleri sırayla dener. Yalnızca "bu model şu an kullanılamıyor" anlamına
    gelen hatalarda (kota dolu / model yok) sonrakine geçer — bozuk istek ya da
    ağ hatası gibi durumlarda denemeye devam etmek yanıltıcı olurdu, o yüzden
    onlar olduğu gibi yukarı fırlatılır.
    """
    last_error = None
    for model in models:
        try:
            return client.models.generate_content(model=model, contents=contents)
        except Exception as e:
            text = str(e)
            unavailable = any(
                s in text for s in ("429", "RESOURCE_EXHAUSTED", "404", "NOT_FOUND")
            )
            if not unavailable:
                raise
            print(f"Model {model} unavailable, falling back: {text[:120]}")
            last_error = e
    raise last_error


def generate_answer(user_query: str, recipes: list) -> str:
    """Bulunan tarifleri LLM'e verip doğal bir öneri cevabı üretir."""

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