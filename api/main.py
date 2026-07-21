from fastapi import FastAPI, Depends
import os
from pydantic import BaseModel
import chromadb
from filters import extract_filters
from llm import generate_answer, detect_ingredients_from_image
from auth import get_current_user_email
from favorites import add_favorite, get_favorites, remove_favorite
from logger import get_logger, timed, timed_block
from fastapi.middleware.cors import CORSMiddleware

log = get_logger("main")

app = FastAPI(title="Recipe RAG Assistant API")
# CORS: hangi sitelerin bu API'yi tarayıcıdan çağırabileceği. Geliştirmede "*"'dı;
# production'da kendi origin'lerimizle sınırlı.
#   - allow_origins: canlı frontend (Vercel production domain'i)
#   - allow_origin_regex ile ek olarak izin verilenler:
#       * Vercel'in bu projeye ait preview deploy'ları (her deploy'da host değişiyor)
#       * yerel geliştirme: localhost / 127.0.0.1 / LAN IP (herhangi bir port)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://recipe-rag-assistant.vercel.app"],
    allow_origin_regex=r"https://recipe-rag-assistant[a-z0-9-]*\.vercel\.app|http://(localhost|127\.0\.0\.1|(\d{1,3}\.){3}\d{1,3})(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Tarifler salt-okunur veri: bir kez ingestion ile yazılır, sonra sadece okunur.
# Bu yüzden ayrı bir ChromaDB sunucusuna değil, image'a gömülü klasöre bakıyor.
# (Favoriler Faz 9'da Firestore'a taşındı; chromadb servisi tamamen kalktı.)
CHROMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chroma_data")
log.info("Opening recipes database: %s", CHROMA_PATH)
with timed_block("chromadb open", logger_name="main"):
    chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
    # Embedding'i ChromaDB'nin varsayılan fonksiyonu üretiyor: aynı all-MiniLM-L6-v2
    # modeli, torch yerine ONNX motoruyla.
    collection = chroma_client.get_collection("recipes")

log.info("Ready! Collection has %s recipes.", collection.count())


class SearchRequest(BaseModel):
    query: str
    n_results: int = 5


def _recipe_card(recipe_id: str, meta: dict, doc: str) -> dict:
    """Liste kartlarının ihtiyaç duyduğu alanlar (detay sayfasınınkinden dar)."""
    return {
        "id": recipe_id,
        "name": meta["name"],
        "category": meta["category"],
        "total_time_min": meta["total_time_min"],
        "calories": meta["calories"],
        "diet_tags": {
            "gluten_free": meta["gluten_free"],
            "dairy_free": meta["dairy_free"],
            "nut_free": meta["nut_free"],
            "vegetarian": meta["vegetarian"],
            "pescatarian": meta["pescatarian"],
            "vegan": meta["vegan"],
        },
        "description": doc,
    }


def _cards_from_query(results: dict) -> list[dict]:
    """collection.query() sonucunu kart listesine çevirir (tek sorgu varsayımı)."""
    return [
        _recipe_card(recipe_id, meta, doc)
        for doc, meta, recipe_id in zip(
            results["documents"][0], results["metadatas"][0], results["ids"][0]
        )
    ]


@app.get("/")
def root():
    return {"message": "Recipe RAG Assistant API is running"}


@app.post("/api/recipes/search")
@timed  # dış ölçüm: endpoint'in ucundan ucuna süresi
def search_recipes(request: SearchRequest, user_email: str = Depends(get_current_user_email)):
    log.info("Text search: %r (n=%s)", request.query, request.n_results)

    # 1. Kullanıcı sorgusundan filtre çıkar
    with timed_block("extract_filters"):
        where_filter = extract_filters(request.query)

    # 2. ChromaDB'de semantic + metadata arama yap
    #    (embedding üretimi de bu çağrının içinde — query_texts veriyoruz)
    with timed_block("chromadb query"):
        results = collection.query(
            query_texts=[request.query],
            n_results=request.n_results,
            where=where_filter
        )

    recipes = _cards_from_query(results)

    # Sonuçsuz arama hata değil ama sessizce geçilmemeli: filtre çıkarımı fazla
    # daraltmış olabilir, log'da sarı bir satır olarak görünsün.
    if not recipes:
        log.warning("No results for %r (filters: %s)", request.query, where_filter)

    # LLM burada BEKLENMİYOR. Tarifler ~0.3sn'de hazır oluyordu ama endpoint
    # Gemini'yi bekliyordu; Gemini yavaşladığında (503 + SDK retry) toplam süre
    # 10sn'yi buluyor ve kullanıcı elde hazır duran sonuçları göremiyordu.
    # AI yorumu artık ayrı bir istekle geliyor: /api/recipes/commentary.
    return {
        "query": request.query,
        "applied_filters": where_filter,
        "results": recipes
    }


class CommentaryRequest(BaseModel):
    query: str
    recipe_ids: list[str]


@app.post("/api/recipes/commentary")
# Bu endpoint Gemini'yi bekliyor; "yavaş" eşiği aramanınkinden yüksek olmalı
# yoksa normal çalışan her istek WARNING üretir ve uyarı anlamını yitirir.
@timed(slow_ms=5000)
def recipe_commentary(
    request: CommentaryRequest,
    user_email: str = Depends(get_current_user_email),
):
    """
    Arama sonuçları için AI yorumu. Aramadan AYRI tutuluyor: tarifler ChromaDB'den
    ~0.3sn'de geliyor, Gemini ise 3.5sn (yavaş günlerde 10sn+). Aynı istekte
    olduklarında kullanıcı hazır sonuçları LLM bitene kadar göremiyordu.

    Tarif bilgisi istemciden DEĞİL, ID'lerden okunuyor — istemcinin gönderdiği
    metne göre prompt kurmak, LLM'e keyfi içerik enjekte etmeye açık kapı bırakır.
    """
    if not request.recipe_ids:
        return {"answer": None}

    results = collection.get(ids=request.recipe_ids[:10])
    recipes = [
        _recipe_card(recipe_id, meta, doc)
        for recipe_id, meta, doc in zip(
            results["ids"], results["metadatas"], results["documents"]
        )
    ]

    if not recipes:
        return {"answer": None}

    try:
        return {"answer": generate_answer(request.query, recipes)}
    except Exception as e:
        # Kota dolması buraya düşüyor. Arama zaten tamamlandı; yorumun gelmemesi
        # sayfayı bozmuyor, frontend kutuyu gizliyor.
        log.error("LLM error (commentary skipped): %s", e)
        return {"answer": None, "error": "commentary_unavailable"}


@app.get("/api/auth/me")
def get_me(user_email: str = Depends(get_current_user_email)):
    return {"email": user_email}


class ImageSearchRequest(BaseModel):
    image_base64: str
    additional_text: str = ""
    n_results: int = 5


@app.post("/api/recipes/from-image")
# Vision çağrısını içerdiği için metin aramasından yavaş olması normal.
@timed(slow_ms=5000)
def search_recipes_from_image(
    request: ImageSearchRequest,
    user_email: str = Depends(get_current_user_email)
):
    # 1. Fotoğraftan malzemeleri tanı.
    #    Metin aramasının aksine bu Gemini çağrısı ZORUNLU — malzeme listesi
    #    olmadan arama yapılamaz. Hata yakalanmazsa endpoint 500 döner ve o 500,
    #    CORS middleware'ine uğramadan çıktığı için tarayıcıda gerçek sebep yerine
    #    yanıltıcı bir "blocked by CORS policy" hatası görünür.
    try:
        detected_ingredients = detect_ingredients_from_image(request.image_base64)
    except Exception as e:
        log.error("Vision error: %s", e)
        quota_exhausted = "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)
        return {
            "error": (
                "Daily AI quota reached, so photo search is unavailable right now. "
                "Text search still works."
                if quota_exhausted
                else "Could not read the photo. Please try again or use text search."
            )
        }

    if len(detected_ingredients) == 0:
        log.warning("No ingredients detected in the image")
        return {"error": "No ingredients detected in the image"}

    # Bu metin de bize dışarıdan geliyor (LLM üretiyor) — yine %r.
    log.info("Detected ingredients: %r", ", ".join(detected_ingredients))

    # 2. Malzemeleri + (varsa) kullanıcının ek notunu birleştirip arama sorgusu oluştur
    ingredients_text = ", ".join(detected_ingredients)
    if request.additional_text.strip():
        combined_query = f"{ingredients_text}. {request.additional_text.strip()}"
    else:
        combined_query = ingredients_text

    # 3. Aynı arama akışını kullan (filtre + embedding + ChromaDB + LLM)
    with timed_block("extract_filters"):
        where_filter = extract_filters(combined_query)

    with timed_block("chromadb query"):
        results = collection.query(
            query_texts=[combined_query],
            n_results=request.n_results,
            where=where_filter
        )

    recipes = _cards_from_query(results)

    if not recipes:
        log.warning("No results for image query %r (filters: %s)", combined_query, where_filter)

    # Metin aramasındaki gibi: LLM yorumu beklenmiyor, ayrı istekle geliyor.
    # (Buradaki Gemini vision çağrısı zorunlu — malzemeler olmadan arama yapılamaz.)
    return {
        "detected_ingredients": detected_ingredients,
        "additional_text": request.additional_text,
        "combined_query": combined_query,
        "applied_filters": where_filter,
        "results": recipes
    }





@app.get("/api/recipes/{recipe_id}")
@timed
def get_recipe_detail(recipe_id: str, user_email: str = Depends(get_current_user_email)):
    results = collection.get(ids=[recipe_id])

    if len(results["ids"]) == 0:
        # %r (repr) kullanılıyor, %s değil: recipe_id kullanıcıdan geliyor ve
        # içinde satır sonu olabilir (URL'de %0A). Düz %s ile loglanırsa satır
        # sonu aynen basılır ve saldırgan log'a sahte bir satır uydurabilir
        # (log injection). repr satır sonunu \n olarak kaçırıyor.
        log.warning("Recipe not found: %r", recipe_id)
        return {"error": "Recipe not found"}

    meta = results["metadatas"][0]

    return {
        "id": results["ids"][0],
        "name": meta["name"],
        "category": meta["category"],
        "total_time_min": meta["total_time_min"],
        "calories": meta["calories"],
        "protein_content": meta["protein_content"],
        "carbohydrate_content": meta["carbohydrate_content"],
        "fat_content": meta["fat_content"],
        "instructions": meta.get("instructions", ""),
        "diet_tags": {
            "gluten_free": meta["gluten_free"],
            "dairy_free": meta["dairy_free"],
            "nut_free": meta["nut_free"],
            "vegetarian": meta["vegetarian"],
            "pescatarian": meta["pescatarian"],
            "vegan": meta["vegan"],
        },
        "description": results["documents"][0]
    }



class FavoriteRequest(BaseModel):
    recipe_id: str


@app.post("/api/favorites/add")
@timed
def add_favorite_endpoint(request: FavoriteRequest, user_email: str = Depends(get_current_user_email)):
    try:
        add_favorite(user_email, request.recipe_id)
        return {"message": "Recipe added to favorites", "recipe_id": request.recipe_id}
    except ValueError as e:
        # Beklenen bir ret (zaten favoride) — ERROR değil WARNING. Ölçüm de
        # bozulmuyor: hata burada yakalandığı için @timed normal dönüş görüyor.
        log.warning("Add favorite rejected (%r): %s", request.recipe_id, e)
        return {"error": str(e)}


@app.get("/api/favorites")
@timed
def list_favorites_endpoint(
    include_details: bool = False,
    user_email: str = Depends(get_current_user_email),
):
    """
    Varsayılan olarak sadece {recipe_id, added_at} döner — favori sayfası dışındaki
    çağıranlar (recipe.js'in "bu tarif favoride mi" kontrolü) tarif detayını
    gereksiz yere indirmesin diye.

    `include_details=true` ile her favorinin tarif bilgisi de gelir. Favoriler
    sayfası bunu kullanıyor: önceden her ID için AYRI bir /api/recipes/{id} isteği
    atıyordu (N favori = N+1 istek, her biri ayrıca token doğrulaması yapıyordu ve
    Render'ın 0.1 vCPU'sunda sıraya giriyordu). ChromaDB `get` zaten ID listesi
    aldığı için hepsi tek çağrıda okunuyor.
    """
    favorites = get_favorites(user_email)

    if not include_details or not favorites:
        return {"favorites": favorites}

    ids = [f["recipe_id"] for f in favorites]
    # Faz 11'de N+1'in kaldırıldığı yer: N ayrı istek yerine tek `get`.
    # Ölçüm burada duruyor ki iddiayı log'dan gösterebilelim.
    with timed_block(f"chromadb get ({len(ids)} recipes)"):
        results = collection.get(ids=ids)

    # ChromaDB dönüş sırasını garanti etmiyor ve olmayan ID'leri sessizce atlıyor;
    # id -> kart eşlemesi kurup favori sırasını koruyoruz.
    cards = {
        recipe_id: _recipe_card(recipe_id, meta, doc)
        for recipe_id, meta, doc in zip(
            results["ids"], results["metadatas"], results["documents"]
        )
    }

    return {
        "favorites": [
            {**f, "recipe": cards.get(f["recipe_id"])}  # silinmiş tarif → None
            for f in favorites
        ]
    }


@app.delete("/api/favorites/{recipe_id}")
@timed
def remove_favorite_endpoint(recipe_id: str, user_email: str = Depends(get_current_user_email)):
    try:
        remove_favorite(user_email, recipe_id)
        return {"message": "Recipe removed from favorites", "recipe_id": recipe_id}
    except ValueError as e:
        log.warning("Remove favorite rejected (%r): %s", recipe_id, e)
        return {"error": str(e)}