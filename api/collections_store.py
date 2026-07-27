"""Kullanıcının tariflerini adlandırılmış gruplara ("collections") ayırması.

Favorilerin ÜSTÜNE binen bir düzenleme katmanı — favorileri değiştirmez:
    - Favoriler ("All Saved") master liste (favorites.py, el değmedi).
    - Koleksiyon, favorilerin adlandırılmış bir ALT KÜMESİ.
    - Bir tarif 0, 1 veya birden fazla koleksiyonda olabilir.
İlişki kuralı main.py'de kurulu: koleksiyona ekleme otomatik favoriye de ekler,
favoriden çıkarma tarifi tüm koleksiyonlardan da düşürür.

⚠️ DOSYA ADI `collections.py` DEĞİL: `collections` Python standart kütüphanesinin
bir modülü (OrderedDict, namedtuple, collections.abc ...). `pythonpath = api`
olduğu için düz bir `collections.py` onu gölgeleyip pydantic/fastapi dahil her
şeyi kırardı — aynı sebeple logger dosyası da `logging.py` değil `logger.py`.
API yolu ve arayüz terimi "collections" olarak kalıyor; yalnızca dosya adında
`_store` eki var.

Üyelik, koleksiyon dokümanında bir `recipe_ids` DİZİSİ olarak tutuluyor (ayrı
üyelik dokümanları değil): favori/koleksiyon sayısı kişisel ölçekte küçük olduğu
için dizi yaklaşımı N+1 sorgu, bileşik indeks ve order_by derdini ortadan
kaldırıyor — favorites.py'deki "sıralamayı bellekte yap" kararıyla aynı gerekçe.
"""
from datetime import datetime, timezone

# firebase_admin'i başlatan yer auth.py — import etmek onu garantiye alır
# (favorites.py ile aynı desen).
import auth  # noqa: F401
from firebase_admin import firestore
from google.cloud.firestore_v1 import FieldFilter

from logger import timed

_db = firestore.client()
_collections = _db.collection("collections")

# Koleksiyon adı için üst sınır. Pydantic tarafında daha yüksek bir sınır 422
# üretiyor; bu değer kullanıcıya anlaşılır bir mesaj döndürmek için.
MAX_NAME_LENGTH = 60


def validate_collection_name(name: str) -> str:
    """Adı temizler ve döner; kullanılamazsa kullanıcıya gösterilecek bir mesajla
    ValueError fırlatır. Saf fonksiyon (veritabanına dokunmuyor) — validate_query
    gibi tek başına test edilebilir.
    """
    cleaned = (name or "").strip()
    if not cleaned:
        raise ValueError("Collection name can't be empty.")
    if len(cleaned) > MAX_NAME_LENGTH:
        raise ValueError(f"Collection name is too long (max {MAX_NAME_LENGTH} characters).")
    return cleaned


def _owned_doc(user_email: str, collection_id: str):
    """Koleksiyon dokümanını sahiplik kontrolüyle getirir.

    Doküman ID'si Firestore auto-ID (favorilerdeki bileşik anahtarın aksine
    kullanıcıya bağlı değil), o yüzden owner_email'i açıkça doğruluyoruz.
    Bulunamama ve "başkasının koleksiyonu" AYNI mesajı veriyor — varlık sızdırmamak
    için (favoriler için önemli değildi, burada ID tahmin edilebilir olduğundan var).
    """
    snap = _collections.document(collection_id).get()
    if not snap.exists or snap.to_dict().get("owner_email") != user_email:
        raise ValueError("Collection not found.")
    return snap


def create_collection(user_email: str, name: str) -> dict:
    cleaned = validate_collection_name(name)

    # Aynı isim yasağı (kullanıcı başına, büyük/küçük harf duyarsız). Kontrol
    # bellekte: where(owner) tek eşitlik filtresi + Python'da karşılaştırma —
    # ikinci bir eşitlik filtresi eklemekten kaçınıyoruz ki bileşik indeks
    # gerekmesin (favorites.py'deki order_by kaçınmasıyla aynı ilke).
    for existing in get_collections(user_email):
        if existing["name"].lower() == cleaned.lower():
            raise ValueError("You already have a collection with this name.")

    created_at = str(datetime.now(timezone.utc))
    doc_ref = _collections.document()  # Firestore auto-ID
    doc_ref.set({
        "owner_email": user_email,
        "name": cleaned,
        "recipe_ids": [],
        "created_at": created_at,
    })
    return {"id": doc_ref.id, "name": cleaned, "recipe_ids": [], "created_at": created_at}


@timed  # Firestore ağ üzerinden konuşuyor; süresi değişken (favorites.py gibi)
def get_collections(user_email: str) -> list[dict]:
    """Kullanıcının koleksiyonları, en son oluşturulan en üstte."""
    docs = _collections.where(filter=FieldFilter("owner_email", "==", user_email)).stream()

    result = []
    for doc in docs:
        data = doc.to_dict()
        result.append({
            "id": doc.id,
            # `.get` ile — `data["name"]` idi ve alanı olmayan TEK bir doküman
            # KeyError fırlatıp endpoint'i 500 yapıyordu, yani bozuk bir kayıt
            # favoriler sayfasının tamamını açılmaz hâle getiriyordu. Canlı
            # görüldü (konsoldan elle düzenlenmiş bir dokümanda). Bir kaydın
            # bozukluğu diğerlerini götürmemeli.
            "name": data.get("name") or "(untitled)",
            "recipe_ids": data.get("recipe_ids", []),
            "created_at": data.get("created_at", ""),
        })

    # Sıralama Firestore'da değil burada: where + order_by bileşik indeks isterdi.
    # created_at sabit UTC formatında yazıldığı için metin sıralaması kronolojik.
    result.sort(key=lambda c: c["created_at"], reverse=True)
    return result


def get_collection_detail(user_email: str, collection_id: str) -> dict:
    """Tek bir koleksiyonun metadatası + tarif ID'leri (kart bilgileri değil —
    onları main.py ChromaDB'den okuyup ekliyor, favorilerdeki include_details gibi).
    """
    data = _owned_doc(user_email, collection_id).to_dict()
    return {
        "id": collection_id,
        "name": data.get("name") or "(untitled)",   # bkz. get_collections
        "recipe_ids": data.get("recipe_ids", []),
        "created_at": data.get("created_at", ""),
    }


def rename_collection(user_email: str, collection_id: str, name: str) -> dict:
    cleaned = validate_collection_name(name)
    self_snap = _owned_doc(user_email, collection_id)  # sahiplik + varlık

    # Aynı isim yasağı (kendisi hariç)
    for existing in get_collections(user_email):
        if existing["id"] != collection_id and existing["name"].lower() == cleaned.lower():
            raise ValueError("You already have a collection with this name.")

    self_snap.reference.update({"name": cleaned})
    return {"id": collection_id, "name": cleaned}


def delete_collection(user_email: str, collection_id: str):
    """Koleksiyonu siler. Tarifler favorilerde KALIR — sadece grup kalkar."""
    _owned_doc(user_email, collection_id).reference.delete()


def add_recipe_to_collection(user_email: str, collection_id: str, recipe_id: str):
    """Tarifi koleksiyona ekler. Zaten içindeyse no-op (picker toggle'ında güvenli).

    recipe_ids dizisini okuyup-değiştirip-yazıyoruz: sahiplik kontrolü zaten
    dokümanı okuduğu için ArrayUnion'a göre ek bir tur getirmiyor ve kod daha sade.
    """
    snap = _owned_doc(user_email, collection_id)
    recipe_ids = snap.to_dict().get("recipe_ids", [])
    if recipe_id not in recipe_ids:
        recipe_ids.append(recipe_id)
        snap.reference.update({"recipe_ids": recipe_ids})


def remove_recipe_from_collection(user_email: str, collection_id: str, recipe_id: str):
    """Tarifi koleksiyondan çıkarır (favoride KALIR). İçinde değilse no-op."""
    snap = _owned_doc(user_email, collection_id)
    recipe_ids = snap.to_dict().get("recipe_ids", [])
    if recipe_id in recipe_ids:
        recipe_ids.remove(recipe_id)
        snap.reference.update({"recipe_ids": recipe_ids})


@timed
def remove_recipe_from_all_collections(user_email: str, recipe_id: str):
    """Tarifi kullanıcının HER koleksiyonundan düşürür.

    İlişki kuralının uygulanışı: favoriden çıkan tarif tüm koleksiyonlardan da
    çıkmalı (koleksiyon üyeliği ⊆ favoriler değişmezliği korunuyor). main.py'deki
    favori-silme endpoint'i çağırıyor.
    """
    docs = _collections.where(filter=FieldFilter("owner_email", "==", user_email)).stream()
    for doc in docs:
        recipe_ids = doc.to_dict().get("recipe_ids", [])
        if recipe_id in recipe_ids:
            recipe_ids.remove(recipe_id)
            doc.reference.update({"recipe_ids": recipe_ids})
