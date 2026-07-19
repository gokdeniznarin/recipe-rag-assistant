from datetime import datetime, timezone

# firebase_admin'i başlatan yer auth.py — import etmek onu garantiye alır
# (import sırası hangisi olursa olsun app başlatılmış olur).
import auth  # noqa: F401
from firebase_admin import firestore
from google.cloud.firestore_v1 import FieldFilter

# Favoriler çalışma anında değişen tek veri. ChromaDB'den Firestore'a taşındı:
# vektör veritabanına vektörü olmayan veri konuyordu (eskiden her kayda sahte bir
# [[0.0] * 384] embedding yazılıyordu) ve API'nin kalıcı disk istemesinin tek
# sebebi buydu. Bkz. CLAUDE.md → "şekil sorunu".
#
# firestore.client() ağ bağlantısı kurmaz (tembel) — ChromaDB HttpClient'ın aksine
# Firestore erişilemez olsa bile API açılır, sadece favori istekleri hata verir.
_db = firestore.client()
_favorites = _db.collection("favorites")


def _make_favorite_id(user_email: str, recipe_id: str) -> str:
    """Bileşik anahtar: aynı kullanıcı aynı tarifi iki kez favorileyemesin"""
    return f"{user_email}_{recipe_id}"


def add_favorite(user_email: str, recipe_id: str):
    doc = _favorites.document(_make_favorite_id(user_email, recipe_id))

    if doc.get().exists:
        raise ValueError("This recipe is already in favorites.")

    doc.set({
        "user_email": user_email,
        "recipe_id": recipe_id,
        "added_at": str(datetime.now(timezone.utc)),
    })


def get_favorites(user_email: str) -> list[dict]:
    """En son eklenen favori en üstte döner."""
    docs = _favorites.where(filter=FieldFilter("user_email", "==", user_email)).stream()

    favorites = []
    for doc in docs:
        data = doc.to_dict()
        favorites.append({
            "recipe_id": data["recipe_id"],
            "added_at": data["added_at"],
        })

    # Sıralama Firestore'da değil burada yapılıyor: where + order_by birlikte
    # kullanılınca Firestore bileşik indeks (composite index) istiyor, yani elle
    # kurulması gereken bir altyapı adımı. Bir kullanıcının favori sayısı küçük
    # olduğu için bellekte sıralamak bu bağımlılığa değmez.
    #
    # added_at ISO benzeri sabit formatta yazılıyor ("2026-07-19 09:16:46.695222+00:00")
    # ve hepsi UTC; alanlar sıfır dolgulu olduğu için metin sıralaması kronolojik
    # sıralamayla aynı sonucu veriyor.
    favorites.sort(key=lambda f: f["added_at"], reverse=True)
    return favorites


def remove_favorite(user_email: str, recipe_id: str):
    doc = _favorites.document(_make_favorite_id(user_email, recipe_id))

    if not doc.get().exists:
        raise ValueError("This recipe is not in favorites.")

    doc.delete()
