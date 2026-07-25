from fastapi import FastAPI, Depends
import os
from pydantic import BaseModel, Field
import chromadb
from filters import extract_filters
from validation import validate_query
from llm import generate_answer, detect_ingredients_from_image, is_food_request
from auth import get_current_user_email
from favorites import add_favorite, get_favorites, remove_favorite
from collections_store import (
    create_collection,
    get_collections,
    get_collection_detail,
    rename_collection,
    delete_collection,
    add_recipe_to_collection,
    remove_recipe_from_collection,
    remove_recipe_from_all_collections,
)
from pantry import (
    get_pantry,
    add_pantry_items,
    remove_pantry_item,
    clear_pantry,
    count_pantry_matches,
    build_pantry_query,
)
from meal_plan import (
    validate_date,
    validate_slot,
    validate_week,
    get_week,
    set_entry,
    remove_entry,
    clear_week,
)
from shopping import (
    missing_ingredients,
    build_list,
    get_overlay,
    set_checked as shopping_set_checked,
    add_custom as shopping_add_custom,
    remove_custom as shopping_remove_custom,
)
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
    # Üst sınır olmadan istemci n_results=100000 isteyebiliyordu. Frontend her
    # zaman 5 gönderiyor; sınır elle kurulmuş isteklere karşı.
    n_results: int = Field(5, ge=1, le=20)


def _ingredients_list(meta: dict) -> list[str]:
    """Malzeme listesi. ChromaDB metadata'sı liste tutamadığı için `|` ile
    ayrılmış tek metin olarak saklanıyor (bkz. load_to_chromadb.py)."""
    raw = meta.get("ingredients", "")
    return [part.strip() for part in raw.split("|") if part.strip()] if raw else []


def _recipe_card(recipe_id: str, meta: dict, doc: str) -> dict:
    """Liste kartlarının ihtiyaç duyduğu alanlar (detay sayfasınınkinden dar)."""
    return {
        "id": recipe_id,
        "name": meta["name"],
        "category": meta["category"],
        "total_time_min": meta["total_time_min"],
        "calories": meta["calories"],
        "ingredients": _ingredients_list(meta),
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
    # [:100] — uzunluk kontrolü henüz yapılmadığı için bu satır 200+ karakterlik
    # bir sorguyu olduğu gibi basabilirdi. %r log injection'a karşı (satır sonunu
    # kaçırıyor); aşağıdaki WARNING de aynı şekilde kırpıyor.
    log.info("Text search: %r (n=%s)", request.query[:100], request.n_results)

    # 0. Sorgu kullanılabilir mi? En pahalı adımlardan (embedding + ChromaDB,
    #    Render'da ~5.4 sn) ve frontend'in ardından tetikleyeceği Gemini
    #    çağrısından ÖNCE. Bkz. validation.py.
    #    422 değil 200 + {"error": ...} dönüyoruz: from-image'daki yerleşik
    #    kalıp bu (Faz 11b) ve search.js zaten data.error'ı showError'a veriyor,
    #    yani frontend'de tek satır değişmeden düzgün mesaj gösteriliyor.
    invalid = validate_query(request.query)
    if invalid:
        log.warning("Rejected query %r: %s", request.query[:100], invalid)
        return {
            "query": request.query,
            "applied_filters": None,
            "results": [],
            "error": invalid,
        }

    # 0.5 Sorgu bir yemek/tarif isteği mi? Non-food sorgular (coğrafya soruları,
    #     klavye ezmesi vb.) burada TAMAMEN reddediliyor — sonuç bile
    #     gösterilmiyor. Kapı 1 yalnızca biçime bakıyordu ("lkjhgfdsa" harf
    #     içerdiği için geçiyordu); bu adım anlama bakıyor. is_food_request
    #     FAIL-OPEN: Gemini çökerse True döner, arama çalışmaya devam eder.
    #     ChromaDB'den ÖNCE: non-food sorgu Render'daki ~5.4 sn embedding'i de
    #     harcamıyor (sınıflandırıcı ~0.7 sn'de reddediyor).
    if not is_food_request(request.query):
        return {
            "query": request.query,
            "applied_filters": None,
            "results": [],
            "error": "This doesn't look like a food search. Try naming a dish or its ingredients.",
        }

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
        "results": recipes,
    }


class CommentaryRequest(BaseModel):
    # Bu metin doğrudan Gemini prompt'una giriyor (llm.generate_answer). Tarif
    # bilgisi bilinçli olarak ID'lerden okunuyor ama `query` istemciden geliyor,
    # yani sınırsız bırakılırsa prompt'a sınırsız metin sokulabilirdi.
    # Sınır 200 değil 500: kamera aramasında bu alan "malzemeler + kullanıcı notu"
    # birleşimi (combined_query) olarak geliyor, doğal olarak daha uzun.
    query: str = Field(..., max_length=500)
    # Zaten [:10] ile dilimleniyor; sınır, devasa gövdelerin JSON parse edilip
    # bellekte tutulmasını en baştan engelliyor.
    recipe_ids: list[str] = Field(..., max_length=50)


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
    # validate_query BURADA UYGULANMIYOR: alan opsiyonel (boş olabilir) ve asıl
    # sorguyu fotoğraftan tanınan malzemeler taşıyor — kullanıcının notu saçma
    # olsa bile arama malzemelerle anlamlı kalıyor. Ayrıca vision çağrısı bu
    # noktada zaten yapılmış oluyor, yani erken reddetmenin tasarruf ettireceği
    # bir şey yok. Yalnızca uzunluk sınırlanıyor: bu metin combined_query'ye,
    # oradan da Gemini prompt'una giriyor.
    additional_text: str = Field("", max_length=200)
    n_results: int = Field(5, ge=1, le=20)


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
    # Not: is_food_request BURADA yok — malzemeler zaten fotoğraftan tanınmış
    # yemek öğeleri, non-food sorgu diye bir durum oluşmuyor.
    return {
        "detected_ingredients": detected_ingredients,
        "additional_text": request.additional_text,
        "combined_query": combined_query,
        "applied_filters": where_filter,
        "results": recipes,
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
        # Faz 17'de eklendi: önceden malzemeler yalnızca gömme metninin içinde
        # düz yazı olarak vardı, detay sayfası hiç gösteremiyordu.
        "ingredients": _ingredients_list(meta),
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
        # İlişki kuralı: favoriden çıkan tarif tüm koleksiyonlardan da düşer
        # (koleksiyon üyeliği ⊆ favoriler değişmezliği). remove_favorite
        # başarılı olduysa çağrılıyor — tarif favori değilse zaten koleksiyonda
        # da olmamalı (auto-favorite kuralının tersi).
        remove_recipe_from_all_collections(user_email, recipe_id)
        return {"message": "Recipe removed from favorites", "recipe_id": recipe_id}
    except ValueError as e:
        log.warning("Remove favorite rejected (%r): %s", recipe_id, e)
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════
#  COLLECTIONS — favorilerin üstüne binen düzenleme katmanı.
#  Veri erişimi collections_store.py'de (dosya adı stdlib'i gölgelememek için
#  `collections.py` DEĞİL). Endpoint deseni favorilerinkiyle aynı: @timed +
#  ValueError → 200 + {"error": ...}.
# ═══════════════════════════════════════════════════════════

class CreateCollectionRequest(BaseModel):
    # Sınır 200: asıl (anlaşılır mesajlı) 60 karakter kuralı
    # validate_collection_name'de. Pydantic sadece devasa gövdeleri eliyor.
    name: str = Field(..., max_length=200)


class RenameCollectionRequest(BaseModel):
    name: str = Field(..., max_length=200)


class CollectionRecipeRequest(BaseModel):
    recipe_id: str


@app.post("/api/collections")
@timed
def create_collection_endpoint(
    request: CreateCollectionRequest,
    user_email: str = Depends(get_current_user_email),
):
    try:
        return create_collection(user_email, request.name)
    except ValueError as e:
        # Boş/uzun ad ya da aynı isim — beklenen ret, WARNING.
        log.warning("Create collection rejected (%r): %s", request.name[:60], e)
        return {"error": str(e)}


@app.get("/api/collections")
@timed
def list_collections_endpoint(user_email: str = Depends(get_current_user_email)):
    # recipe_ids de dönüyor: favoriler sayfası tarif SAYISINI, recipe.html'deki
    # "add to collection" seçici ise ÜYELİĞİ (bu tarif hangi koleksiyonlarda)
    # bundan hesaplıyor. Diziler küçük olduğu için tek istekte göndermek ucuz.
    return {"collections": get_collections(user_email)}


@app.get("/api/collections/{collection_id}")
@timed
def get_collection_endpoint(
    collection_id: str,
    include_details: bool = False,
    user_email: str = Depends(get_current_user_email),
):
    """Tek bir koleksiyon. include_details=true ile içindeki tariflerin kartları da
    gelir — favorilerdeki ?include_details=true ile birebir aynı mantık (tek
    ChromaDB `get`, sıra korunur, silinmiş tarif None).
    """
    try:
        coll = get_collection_detail(user_email, collection_id)
    except ValueError as e:
        log.warning("Get collection rejected (%r): %s", collection_id, e)
        return {"error": str(e)}

    if not include_details:
        return coll

    ids = coll["recipe_ids"]
    if not ids:
        return {**coll, "recipes": []}

    with timed_block(f"chromadb get ({len(ids)} recipes)"):
        results = collection.get(ids=ids)

    # ChromaDB sırayı garanti etmiyor ve olmayan ID'leri sessizce atlıyor;
    # id -> kart eşlemesiyle koleksiyon sırasını koruyoruz (favoriler gibi).
    cards = {
        recipe_id: _recipe_card(recipe_id, meta, doc)
        for recipe_id, meta, doc in zip(
            results["ids"], results["metadatas"], results["documents"]
        )
    }
    return {
        **coll,
        "recipes": [cards.get(rid) for rid in ids],  # silinmiş tarif → None
    }


@app.patch("/api/collections/{collection_id}")
@timed
def rename_collection_endpoint(
    collection_id: str,
    request: RenameCollectionRequest,
    user_email: str = Depends(get_current_user_email),
):
    try:
        return rename_collection(user_email, collection_id, request.name)
    except ValueError as e:
        log.warning("Rename collection rejected (%r): %s", collection_id, e)
        return {"error": str(e)}


@app.delete("/api/collections/{collection_id}")
@timed
def delete_collection_endpoint(
    collection_id: str,
    user_email: str = Depends(get_current_user_email),
):
    try:
        delete_collection(user_email, collection_id)
        return {"message": "Collection deleted", "id": collection_id}
    except ValueError as e:
        log.warning("Delete collection rejected (%r): %s", collection_id, e)
        return {"error": str(e)}


@app.post("/api/collections/{collection_id}/recipes")
@timed
def add_recipe_to_collection_endpoint(
    collection_id: str,
    request: CollectionRecipeRequest,
    user_email: str = Depends(get_current_user_email),
):
    try:
        add_recipe_to_collection(user_email, collection_id, request.recipe_id)
    except ValueError as e:
        log.warning("Add to collection rejected (%r): %s", collection_id, e)
        return {"error": str(e)}

    # İlişki kuralı: koleksiyondaki her tarif aynı zamanda favoridir
    # (koleksiyon = favorilerin alt kümesi). Zaten favoriyse add_favorite
    # ValueError atıyor — beklenen, yutuluyor.
    try:
        add_favorite(user_email, request.recipe_id)
    except ValueError:
        pass

    return {"message": "Recipe added to collection", "recipe_id": request.recipe_id}


@app.delete("/api/collections/{collection_id}/recipes/{recipe_id}")
@timed
def remove_recipe_from_collection_endpoint(
    collection_id: str,
    recipe_id: str,
    user_email: str = Depends(get_current_user_email),
):
    # Koleksiyondan çıkarma favoriyi ETKİLEMEZ (tarif "All Saved"da kalır).
    try:
        remove_recipe_from_collection(user_email, collection_id, recipe_id)
        return {"message": "Recipe removed from collection", "recipe_id": recipe_id}
    except ValueError as e:
        log.warning("Remove from collection rejected (%r): %s", collection_id, e)
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════
#  PANTRY ("Dolabım") — kalıcı malzeme listesi.
#  Kamera akışını tek seferlik olmaktan çıkarıp kalıcı kullanıcı verisine
#  dönüştürüyor. Veri erişimi pantry.py'de.
# ═══════════════════════════════════════════════════════════

class PantryAddRequest(BaseModel):
    # Liste olarak alıyoruz ki tek endpoint hem elle eklemeyi (1 malzeme) hem
    # kameradan toplu eklemeyi karşılasın.
    names: list[str] = Field(..., max_length=50)


@app.get("/api/pantry")
@timed
def list_pantry_endpoint(user_email: str = Depends(get_current_user_email)):
    return {"items": get_pantry(user_email)}


@app.post("/api/pantry")
@timed
def add_pantry_endpoint(
    request: PantryAddRequest,
    user_email: str = Depends(get_current_user_email),
):
    try:
        result = add_pantry_items(user_email, request.names)
    except ValueError as e:
        log.warning("Add to pantry rejected: %s", e)
        return {"error": str(e)}

    # Güncel listeyi de dönüyoruz: frontend ekleme sonrası ikinci bir GET
    # atmasın (kamera akışında 8 malzeme eklenince fark ediliyor).
    return {**result, "items": get_pantry(user_email)}


@app.delete("/api/pantry/all")
@timed
def clear_pantry_endpoint(user_email: str = Depends(get_current_user_email)):
    """Dolabı tamamen boşaltır.

    AYRI BİR YOL, `?name` boş bırakılınca değil: silme parametresini opsiyonel
    yapıp "yoksa hepsini sil" demek klasik bir tuzak olurdu — frontend'de
    parametreyi düşüren tek bir hata bütün dolabı silerdi. Yıkıcı işlem açıkça
    ayrı bir adres istiyor. (`/api/pantry/all` literal yol; `{name}` parametreli
    bir rota kalmadığı için gölgeleme riski de yok.)
    """
    removed = clear_pantry(user_email)
    log.info("Pantry cleared (%s items)", removed)
    return {"message": "Pantry cleared", "removed": removed}


@app.delete("/api/pantry")
@timed
def remove_pantry_endpoint(
    # Malzeme adı YOL parametresi DEĞİL sorgu parametresi: ASGI `scope["path"]`
    # yüzde-çözülmüş geliyor, yani "salt%2Fpepper" gerçek bölü işaretine dönüşüp
    # tek segmentlik `/{name}` yolunu eşleştirmiyordu (404). Malzeme adları
    # serbest metin olduğu için bu gerçek bir risk.
    name: str,
    user_email: str = Depends(get_current_user_email),
):
    try:
        remove_pantry_item(user_email, name)
        return {"message": "Ingredient removed from pantry", "name": name}
    except ValueError as e:
        log.warning("Remove from pantry rejected (%r): %s", name, e)
        return {"error": str(e)}


class PantrySearchRequest(BaseModel):
    additional_text: str = Field("", max_length=200)
    n_results: int = Field(5, ge=1, le=20)


# Eşleşmeye göre yeniden sıralayabilmek için istenenden kaç kat fazla aday
# çekileceği. 4 seçildi: 5 sonuç için 20 aday, ChromaDB'ye maliyeti ihmal
# edilebilir ama semantik sırada geride kalmış yüksek eşleşmeli tarifleri
# yakalamaya yetiyor. MAX_CANDIDATES üst sınır (n_results=20 istenirse 80
# değil 50 aday çekilir).
CANDIDATE_MULTIPLIER = 4
MAX_CANDIDATES = 50


@app.post("/api/recipes/from-pantry")
@timed
def search_recipes_from_pantry(
    request: PantrySearchRequest,
    user_email: str = Depends(get_current_user_email),
):
    """Dolaptakilerle tarif arama — /api/recipes/from-image'ın kardeşi.

    YENİ BİR ARAMA MANTIĞI YOK: aynı RAG pipeline'ı (embedding → ChromaDB
    semantic + metadata filtresi), yalnızca malzeme listesinin KAYNAĞI farklı
    (Firestore vs Gemini vision).

    Malzemeler istemciden DEĞİL Firestore'dan okunuyor — istemcinin gönderdiği
    listeye göre arama kurmak, commentary endpoint'indeki "tarif bilgisi
    ID'lerden okunur" korumasının aynı gerekçesiyle istenmez.

    `is_food_request` BURADA YOK: dolaptakiler zaten yemek malzemesi, non-food
    sorgu diye bir durum oluşmuyor (from-image'daki gerekçenin aynısı) — bir
    Gemini çağrısı da tasarruf ediliyor.
    """
    pantry_items = get_pantry(user_email)
    if not pantry_items:
        log.warning("Pantry search with empty pantry")
        return {
            "pantry_items": [],
            "results": [],
            "error": "Your pantry is empty. Add some ingredients first.",
        }

    names = [i["name"] for i in pantry_items]
    combined_query = build_pantry_query(names, request.additional_text)

    with timed_block("extract_filters"):
        where_filter = extract_filters(combined_query)

    # ADAY HAVUZU: istenenden FAZLA sonuç çekiliyor (over-fetch), çünkü aşağıda
    # eşleşme sayısına göre yeniden sıralayacağız. Yalnızca n_results kadar
    # çekseydik sıralama elimizdeki 5'i karıştırmaktan ibaret kalırdı — semantik
    # olarak 7. sırada olan ama dolapla 9/11 eşleşen bir tarif hiç görünmezdi.
    # ChromaDB'ye 20 aday sormak 5 sormakla neredeyse aynı maliyette (mesafe
    # hesabı zaten tüm koleksiyon üzerinde yapılıyor, fark sadece kaç tanesinin
    # döndürüldüğü).
    candidate_count = min(request.n_results * CANDIDATE_MULTIPLIER, MAX_CANDIDATES)

    with timed_block("chromadb query"):
        results = collection.query(
            query_texts=[combined_query],
            n_results=candidate_count,
            where=where_filter,
        )

    recipes = _cards_from_query(results)

    # Eşleşme rozeti ("dolabındaki 4/6 malzemeyi kullanıyor").
    # Burada BEDAVA: dolap zaten yukarıda okundu, ek Firestore turu yok.
    # Bilinçli olarak yalnızca bu endpoint'te — metin/kamera aramasına eklemek
    # her aramaya bir Firestore okuması bindirirdi (ölçüldü: ~100-250 ms sıcak,
    # container yeniden başladıktan sonraki ilk çağrıda 6.12 sn), yani Faz 11'de
    # kazanılan "arama hızlı" özelliğini aşındırırdı.
    for card in recipes:
        matched = count_pantry_matches(names, card["ingredients"])
        card["pantry_match"] = {
            "matched": matched,
            "count": len(matched),
            "pantry_total": len(names),
        }

    # EN ÇOK EŞLEŞEN ÜSTTE. Bu modda kullanıcının sorduğu soru "elimdekilerle ne
    # yapabilirim", dolayısıyla alaka ölçüsü eşleşme sayısı — rozeti gösterip
    # 8/11'i 4/11'in altında bırakmak görünür bir tutarsızlıktı.
    # sort STABLE: eşit sayıda eşleşen tarifler semantik sıralarını koruyor,
    # yani eşleşme ayırt etmediğinde vektör benzerliği hâlâ karar veriyor.
    recipes.sort(key=lambda c: c["pantry_match"]["count"], reverse=True)
    recipes = recipes[:request.n_results]

    if not recipes:
        log.warning("No results for pantry query (filters: %s)", where_filter)

    return {
        "pantry_items": names,
        "combined_query": combined_query,
        "applied_filters": where_filter,
        "results": recipes,
    }


# ═══════════════════════════════════════════════════════════
#  MEAL PLANNER — haftalık yemek takvimi.
#  Pantry "şu an elimde ne var", plan "ne pişireceğim" — alışveriş listesinin
#  önkoşulu. Veri erişimi meal_plan.py'de.
# ═══════════════════════════════════════════════════════════

class PlanEntryRequest(BaseModel):
    # Sınırlar cömert: biçim kararını validate_date/validate_slot veriyor ve
    # kullanıcıya anlaşılır bir mesaj dönüyor. Dar bir max_length (10) boşluklu
    # bir tarihi ham 422 ile keserdi, oysa validate_date onu zaten trim'liyor.
    date: str = Field(..., max_length=32)     # YYYY-MM-DD
    slot: str = Field(..., max_length=32)
    recipe_id: str = Field(..., max_length=50)


def _week_payload(week_start: str, entries: list[dict], include_details: bool):
    """Hafta yanıtını kurar; include_details=true ise tarif kartlarını da ekler.

    Kart bilgileri plan dokümanında SAKLANMIYOR, ID'lerden okunuyor —
    favoriler/koleksiyonlardaki `?include_details=true` deseninin aynısı.
    Denormalizasyon (adı dokümana kopyalamak) ÖLÇÜMLE elendi: canlıda
    `chromadb get` = 2.6 ms (embedding olmadığı için; 6.4 sn olan `query` yolu
    bu değil) ve bir hafta en fazla 21 girdi. Kazanacağı hız yok, karşılığında
    "hangisi doğru kaynak" sorunu getirirdi.
    """
    payload = {"week_start": week_start, "entries": entries}
    if not include_details:
        return payload

    ids = list({e["recipe_id"] for e in entries})   # aynı tarif iki slotta olabilir
    if not ids:
        return payload      # boş hafta → ChromaDB'ye hiç gidilmiyor

    with timed_block(f"chromadb get ({len(ids)} recipes)"):
        results = collection.get(ids=ids)

    cards = {
        recipe_id: _recipe_card(recipe_id, meta, doc)
        for recipe_id, meta, doc in zip(
            results["ids"], results["metadatas"], results["documents"]
        )
    }
    # Kart girdinin İÇİNE gömülüyor (koleksiyonlardaki ayrı `recipes` listesi
    # yerine): ızgarada her slot kendi tarifini gösteriyor, ayrı bir liste
    # frontend'de yeniden eşleştirme gerektirirdi.
    return {
        **payload,
        "entries": [
            {**e, "recipe": cards.get(e["recipe_id"])}   # silinmiş tarif → None
            for e in entries
        ],
    }


@app.get("/api/meal-plan")
@timed
def get_meal_plan_endpoint(
    week: str,
    include_details: bool = False,
    user_email: str = Depends(get_current_user_email),
):
    """Bir haftanın planı. `week` haftanın herhangi bir günü olabilir —
    validate_week onu pazartesiye normalize ediyor, yoksa aynı hafta iki ayrı
    dokümana bölünürdü."""
    try:
        week_start = validate_week(week)
    except ValueError as e:
        log.warning("Get meal plan rejected (%r): %s", week, e)
        return {"error": str(e)}

    entries = get_week(user_email, week_start)
    return _week_payload(week_start, entries, include_details)


@app.post("/api/meal-plan")
@timed
def set_meal_plan_entry_endpoint(
    request: PlanEntryRequest,
    user_email: str = Depends(get_current_user_email),
):
    """Slota tarif koyar; slot doluysa ÜZERİNE YAZAR (frontend'in "önce sil,
    sonra ekle" diye iki tur atmasına gerek kalmasın).

    Plana eklemek favoriye EKLEMEZ (koleksiyonların aksine — gerekçesi
    meal_plan.py'nin başında).
    """
    try:
        date_str = validate_date(request.date)
        slot = validate_slot(request.slot)
    except ValueError as e:
        log.warning("Set meal plan rejected (%r %r): %s", request.date, request.slot, e)
        return {"error": str(e)}

    result = set_entry(user_email, date_str, slot, request.recipe_id)
    log.info("Planned %r for %s %s", request.recipe_id, date_str, slot)
    return result


@app.delete("/api/meal-plan/week")
@timed
def clear_meal_plan_week_endpoint(
    week: str,
    user_email: str = Depends(get_current_user_email),
):
    """Haftanın tamamını temizler.

    AYRI BİR LİTERAL YOL (`/api/pantry/all` ile aynı gerekçe): yıkıcı işlem,
    "parametre boşsa hepsini sil" tuzağına düşmemeli. Tek okuma + tek yazma —
    21 slotu tek tek silmek 21 istek demekti.
    """
    try:
        week_start = validate_week(week)
    except ValueError as e:
        log.warning("Clear meal plan week rejected (%r): %s", week, e)
        return {"error": str(e)}

    removed = clear_week(user_email, week_start)
    log.info("Meal plan week %s cleared (%s entries)", week_start, removed)
    return {"message": "Week cleared", "week_start": week_start, "removed": removed}


@app.delete("/api/meal-plan")
@timed
def remove_meal_plan_entry_endpoint(
    # Tarih ve öğün YOL parametresi DEĞİL sorgu parametresi — pantry'de
    # öğrenildi (ASGI `scope["path"]`'i yüzde-çözüyor), ayrıca bileşik anahtar
    # için de doğrusu bu.
    date: str,
    slot: str,
    user_email: str = Depends(get_current_user_email),
):
    try:
        # bounded=False: sınır yeni doküman açılmasını engellemek için, silmeyi
        # değil. Bir yıldan eski bir planı silemeyecek olmak saçma olurdu.
        date_str = validate_date(date, bounded=False)
        slot_name = validate_slot(slot)
        remove_entry(user_email, date_str, slot_name)
        return {"message": "Removed from your plan", "date": date_str, "slot": slot_name}
    except ValueError as e:
        log.warning("Remove from meal plan rejected (%r %r): %s", date, slot, e)
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════
#  SHOPPING LIST — yol haritasının GELİR adımı.
#  Liste SAKLANMIYOR, hesaplanıyor: eksikler = plandaki tariflerin malzemeleri
#  − dolap. Üstüne hafta başına ince bir overlay (checked/custom) biniyor.
#  Veri erişimi shopping.py'de.
# ═══════════════════════════════════════════════════════════

def _planned_recipes_for_week(user_email: str, week_start: str) -> list[dict]:
    """Haftanın planındaki tarifleri malzemeleriyle döner (tekilleştirilmiş).

    Malzemeler plan dokümanında DEĞİL, ID'lerden ChromaDB'den okunuyor —
    meal-plan/favoriler/koleksiyonlardaki aynı desen. Yapılandırılmış
    `ingredients` metadata'sı (Faz 17) olmadan bu hesap yapılamazdı.
    """
    entries = get_week(user_email, week_start)
    recipe_ids = list({e["recipe_id"] for e in entries})
    if not recipe_ids:
        return []

    with timed_block(f"chromadb get ({len(recipe_ids)} recipes)"):
        results = collection.get(ids=recipe_ids)

    meta_by_id = dict(zip(results["ids"], results["metadatas"]))
    planned = []
    for rid in recipe_ids:
        meta = meta_by_id.get(rid)
        if not meta:          # silinmiş tarif → atla (sarkan ID zaten olmamalı)
            continue
        planned.append({
            "recipe_id": rid,
            "name": meta.get("name", ""),
            "ingredients": _ingredients_list(meta),
        })
    return planned


@app.get("/api/shopping-list")
@timed
def get_shopping_list_endpoint(
    week: str,
    user_email: str = Depends(get_current_user_email),
):
    """Haftanın alışveriş listesi: türev eksikler + overlay (checked/custom).

    `week` haftanın herhangi bir günü olabilir (validate_week pazartesiye
    normalize ediyor). Boş plan + hiç elle öğe → boş liste.
    """
    try:
        week_start = validate_week(week)
    except ValueError as e:
        log.warning("Get shopping list rejected (%r): %s", week, e)
        return {"error": str(e)}

    planned = _planned_recipes_for_week(user_email, week_start)
    pantry_names = [i["name"] for i in get_pantry(user_email)]

    derived = missing_ingredients(planned, pantry_names)
    overlay = get_overlay(user_email, week_start)
    items = build_list(derived, overlay["checked"], overlay["custom"])

    return {
        "week_start": week_start,
        "items": items,
        "recipe_count": len(planned),
        "pantry_count": len(pantry_names),
    }


class ShoppingCheckRequest(BaseModel):
    week: str = Field(..., max_length=32)
    # Malzeme adları tarif ifadeleri olabilir ("boneless skinless chicken breast
    # halves") — elle eklenenlerden (60) daha uzun, o yüzden sınır gevşek.
    name: str = Field(..., max_length=120)
    checked: bool


@app.post("/api/shopping-list/check")
@timed
def check_shopping_item_endpoint(
    request: ShoppingCheckRequest,
    user_email: str = Depends(get_current_user_email),
):
    """Bir malzemeyi 'alındı' işaretler / işareti kaldırır."""
    try:
        week_start = validate_week(request.week)
        shopping_set_checked(user_email, week_start, request.name, request.checked)
    except ValueError as e:
        log.warning("Check shopping item rejected (%r): %s", request.name, e)
        return {"error": str(e)}
    return {"message": "ok", "name": request.name, "checked": request.checked}


class ShoppingCustomRequest(BaseModel):
    week: str = Field(..., max_length=32)
    name: str = Field(..., max_length=80)


@app.post("/api/shopping-list/custom")
@timed
def add_custom_shopping_item_endpoint(
    request: ShoppingCustomRequest,
    user_email: str = Depends(get_current_user_email),
):
    """Listeye elle malzeme ekler ("bir de deterjan"). Zaten varsa atlar."""
    try:
        week_start = validate_week(request.week)
        result = shopping_add_custom(user_email, week_start, request.name)
    except ValueError as e:
        log.warning("Add custom shopping item rejected (%r): %s", request.name, e)
        return {"error": str(e)}
    return result


@app.delete("/api/shopping-list/custom")
@timed
def remove_custom_shopping_item_endpoint(
    # Adı YOL değil SORGU parametresi — pantry'deki `salt/pepper` dersi (ASGI
    # scope["path"]'i yüzde-çözüyor).
    week: str,
    name: str,
    user_email: str = Depends(get_current_user_email),
):
    """Elle eklenen malzemeyi çıkarır (türev malzemeler plandan gelir)."""
    try:
        week_start = validate_week(week)
        shopping_remove_custom(user_email, week_start, name)
        return {"message": "Removed from your list", "name": name}
    except ValueError as e:
        log.warning("Remove custom shopping item rejected (%r): %s", name, e)
        return {"error": str(e)}
