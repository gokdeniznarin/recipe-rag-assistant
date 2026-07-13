import os
from datetime import datetime, timezone
import chromadb

CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
chroma_client = chromadb.HttpClient(host=CHROMA_HOST, port=8000)
favorites_collection = chroma_client.get_or_create_collection("favorites")


def _make_favorite_id(user_email: str, recipe_id: str) -> str:
    """Bileşik anahtar: aynı kullanıcı aynı tarifi iki kez favorileyemesin"""
    return f"{user_email}_{recipe_id}"


def add_favorite(user_email: str, recipe_id: str):
    fav_id = _make_favorite_id(user_email, recipe_id)

    existing = favorites_collection.get(ids=[fav_id])
    if len(existing["ids"]) > 0:
        raise ValueError("This recipe is already in favorites.")

    favorites_collection.add(
        ids=[fav_id],
        embeddings=[[0.0] * 384],  # favoriler için embedding'e gerek yok
        documents=[recipe_id],
        metadatas=[{
            "user_email": user_email,
            "recipe_id": recipe_id,
            "added_at": str(datetime.now(timezone.utc)),
        }]
    )


def get_favorites(user_email: str) -> list[dict]:
    results = favorites_collection.get(
        where={"user_email": user_email}
    )

    favorites = []
    for meta in results["metadatas"]:
        favorites.append({
            "recipe_id": meta["recipe_id"],
            "added_at": meta["added_at"],
        })
    return favorites


def remove_favorite(user_email: str, recipe_id: str):
    fav_id = _make_favorite_id(user_email, recipe_id)

    existing = favorites_collection.get(ids=[fav_id])
    if len(existing["ids"]) == 0:
        raise ValueError("This recipe is not in favorites.")

    favorites_collection.delete(ids=[fav_id])