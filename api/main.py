from fastapi import FastAPI
from pydantic import BaseModel
import chromadb
from sentence_transformers import SentenceTransformer
from filters import extract_filters
from llm import generate_answer
from auth import create_user, get_user_by_email, verify_password, create_access_token

app = FastAPI(title="Recipe RAG Assistant API")

print("Loading embedding model...")
model = SentenceTransformer('all-MiniLM-L6-v2')

print("Connecting to ChromaDB...")
chroma_client = chromadb.HttpClient(host='localhost', port=8000)
collection = chroma_client.get_collection("recipes")

print(f"Ready! Collection has {collection.count()} recipes.")


class SearchRequest(BaseModel):
    query: str
    n_results: int = 5


@app.get("/")
def root():
    return {"message": "Recipe RAG Assistant API is running"}


@app.post("/api/recipes/search")
def search_recipes(request: SearchRequest):
    query_embedding = model.encode(request.query).tolist()

    # 1. Kullanıcı sorgusundan filtre çıkar
    where_filter = extract_filters(request.query)

    # 2. ChromaDB'de semantic + metadata arama yap
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=request.n_results,
        where=where_filter
    )

    recipes = []
    for doc, meta, recipe_id in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["ids"][0]
    ):
        recipes.append({
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
            "description": doc
        })

    # 3. LLM'e bulunan tarifleri ver, doğal cevap üret
    llm_answer = None
    if len(recipes) > 0:
        llm_answer = generate_answer(request.query, recipes)

    return {
        "query": request.query,
        "applied_filters": where_filter,
        "answer": llm_answer,
        "results": recipes
    }


class RegisterRequest(BaseModel):
    email: str
    password: str


@app.post("/api/auth/register")
def register(request: RegisterRequest):
    try:
        create_user(request.email, request.password)
        return {"message": "User registered successfully", "email": request.email}
    except ValueError as e:
        return {"error": str(e)}
    


class LoginRequest(BaseModel):
    email: str
    password: str


@app.post("/api/auth/login")
def login(request: LoginRequest):
    user = get_user_by_email(request.email)

    if user is None:
        return {"error": "Invalid email or password"}

    if not verify_password(request.password, user["hashed_password"]):
        return {"error": "Invalid email or password"}

    token = create_access_token(request.email)
    return {"access_token": token, "token_type": "bearer"}    