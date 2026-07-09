import os
from dotenv import load_dotenv
from google import genai

# .env dosyasındaki GEMINI_API_KEY'i yükle
load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

MODEL_NAME = "gemini-2.5-flash"


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

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt
    )
    return response.text


# --- TEST ---
if __name__ == "__main__":
    fake_recipes = [
        {"name": "Quick India Chicken", "total_time_min": 20, "calories": 315.7, "category": "Chicken Breast"},
        {"name": "Quick Chicken Soup", "total_time_min": 25, "calories": 390.1, "category": "Chicken Breast"},
    ]

    answer = generate_answer("quick chicken dinner", fake_recipes)
    print("LLM Answer:")
    print(answer)