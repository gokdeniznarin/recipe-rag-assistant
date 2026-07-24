"""Katman 2 (HTTP sözleşme testleri) için ortak kurulum.

NEDEN GEREKLİ — `import main` tek başına dört dış servise bağlanıyor:
    auth.py:19       firebase_admin.initialize_app()   → kimlik dosyası arar
    favorites.py:18  firestore.client()
    llm.py:13        genai.Client(api_key=...)
    main.py:36       chromadb.PersistentClient(...) + get_collection("recipes")

Bu modül hepsini import ZİNCİRİ BAŞLAMADAN sahteliyor. ChromaDB'nin sahtelenmesi
özellikle kritik: gerçek `PersistentClient` bir klasörü AÇARKEN BİLE
`chroma.sqlite3`'e yazıyor, yani sahtelenmezse her `pytest` çalıştırması commit'li
35MB'lık veritabanını kirletir (doğrulandı: bu conftest'le git temiz kalıyor).

Bu testler gerçek tariflere ihtiyaç duymuyor — sahte bir `collection` hem daha
hızlı hem de "boş sonuç", "eksik alan" gibi senaryoları kontrollü kuruyor.
"""
import sys
from unittest.mock import MagicMock

import pytest


# ── Import-anı yan etkilerini sahtele (test toplama BAŞLAMADAN) ──
# conftest.py, test modüllerinden ÖNCE import edilir; buradaki sys.modules
# atamaları o yüzden "import main" güvenli hale gelmeden yerleşiyor.
#   - firebase_admin: auth.py initialize_app + verify_id_token, favorites firestore
#   - google.cloud.firestore_v1: FieldFilter
#   - google.genai: llm.py'deki genai.Client (API anahtarı gerekmesin)
for _name in ("firebase_admin", "google.cloud", "google.cloud.firestore_v1", "google.genai"):
    sys.modules.setdefault(_name, MagicMock())

# `from google import genai` bunu arıyor; google gerçek namespace paketi olduğu
# için genai'yi ayrıca sys.modules'e koymak gerekiyor.
sys.modules.setdefault("google", MagicMock())


def _default_collection() -> MagicMock:
    """Testlerin gerektiğinde ezeceği makul bir sahte ChromaDB koleksiyonu."""
    meta = {
        "name": "Test Recipe", "category": "Chicken", "total_time_min": 20,
        "calories": 300.0, "protein_content": 25.0, "carbohydrate_content": 10.0,
        "fat_content": 5.0, "instructions": "1. Cook it.",
        # ChromaDB metadata liste tutamıyor → `|` ile ayrılmış metin (Faz 17)
        "ingredients": "chicken breast|tomatoes|olive oil|garlic",
        "gluten_free": True, "dairy_free": True, "nut_free": True,
        "vegetarian": False, "pescatarian": False, "vegan": False,
    }
    collection = MagicMock()
    collection.count.return_value = 4886
    # collection.query() → tek sorguluk sonuç (n_results kadar tekrarlanmaz,
    # tek tarif yeterli; testler gerektiğinde return_value'yu eziyor).
    collection.query.return_value = {
        "documents": [["Test Recipe description"]],
        "metadatas": [[meta]],
        "ids": [["17450"]],
        "distances": [[0.5]],
    }
    # collection.get() → ID listesiyle çağrılıyor (detay, commentary, favoriler)
    collection.get.return_value = {
        "documents": ["Test Recipe description"],
        "metadatas": [meta],
        "ids": ["17450"],
    }
    return collection


@pytest.fixture(scope="session")
def api():
    """(main modülü, sahte collection) — chromadb yamalı halde import edilmiş.

    Session kapsamlı: main bir kez import ediliyor (ChromaDB açılışı sahte
    olduğu için hızlı) ve sahte collection tüm testlerce paylaşılıyor.
    """
    from unittest.mock import patch

    collection = _default_collection()
    with patch("chromadb.PersistentClient") as persistent_client:
        persistent_client.return_value.get_collection.return_value = collection
        import main  # noqa: F401  (yamalar aktifken import ediliyor)

    return main, collection


@pytest.fixture
def collection(api):
    """Sahte ChromaDB koleksiyonu; her testten önce varsayılana sıfırlanır."""
    main, coll = api
    fresh = _default_collection()
    coll.query.side_effect = None
    coll.query.return_value = fresh.query.return_value
    coll.get.side_effect = None
    coll.get.return_value = fresh.get.return_value
    coll.count.return_value = 4886
    coll.reset_mock()
    coll.query.return_value = fresh.query.return_value
    coll.get.return_value = fresh.get.return_value
    coll.count.return_value = 4886
    return coll


@pytest.fixture
def client(api):
    """Auth OVERRIDE'SIZ TestClient — gerçek get_current_user_email çalışır.

    Auth sözleşme testleri (422/401) bunu kullanıyor; token doğrulamasının
    kendisini test ettikleri için bypass edilmemeli.
    """
    from fastapi.testclient import TestClient

    main, _ = api
    return TestClient(main.app, raise_server_exceptions=False)


@pytest.fixture
def auth_client(api):
    """Auth BYPASS'lı TestClient — endpoint mantığını test etmek için.

    get_current_user_email dependency'si sabit bir e-posta döndürecek şekilde
    ezilir. Teardown'da override TEMİZLENİR: dependency_overrides global bir
    sözlük, temizlenmezse bir testin bypass'ı diğerine sızar ve 401 testleri
    sahte yeşil verir.
    """
    from fastapi.testclient import TestClient

    main, _ = api
    main.app.dependency_overrides[main.get_current_user_email] = lambda: "test@example.com"
    yield TestClient(main.app, raise_server_exceptions=False)
    main.app.dependency_overrides.clear()
