"""Hesap silme — kullanıcının Firestore verisi + Firebase Auth kaydı.

NEDEN VAR: `privacy.html` kullanıcıya verisini sildirebileceğini söz veriyor
(bugüne kadar elle, e-posta ile). KVKK/GDPR bunu zaten istiyor, Capacitor'la
mağazaya çıkıldığında ise hem App Store hem Play **uygulama içinde** silme
akışı şart koşuyor. Yani bu, mağaza adımının önkoşulu.

⚠️ SIRA KRİTİK: ÖNCE Firestore, EN SON Auth.
Tersi yapılsaydı ve Firestore silme yarıda kalsaydı, kullanıcı bir daha giriş
YAPAMAYACAĞI için kalan verisine hiçbir şekilde ulaşamaz ve tekrar deneyemezdi
— yetim veri kalıcı olurdu. Bu sırayla yarıda kalan bir silme zararsız: kullanıcı
hâlâ giriş yapmış durumda, butona tekrar basması yeterli. Silme **idempotent**:
olmayan dokümanı silmek Firestore'da hata değil, no-op.
"""

# firebase_admin'i başlatan yer auth.py — import etmek onu garantiye alır.
import auth  # noqa: F401
from firebase_admin import auth as firebase_auth, firestore
from google.cloud.firestore_v1 import FieldFilter

from logger import get_logger, timed

log = get_logger("account")

_db = firestore.client()

# Firestore batch'i en fazla 500 işlem alıyor; 400 güvenlik payı.
_BATCH_SIZE = 400

# ── Kullanıcıya ait koleksiyonların KAYDI ────────────────────────────────
# Silme mantığı bilerek TEK yerde: dört koleksiyon aynı işi yapıyor (bir
# eşitlik filtresi + toplu silme), beş modüle kopyalamak Faz 15d/19'daki
# "aynı kuralı iki yere yazma" ilkesine aykırı olurdu.
#
# Buradaki asıl risk kopya değil UNUTMAK: biri altıncı bir koleksiyon ekler
# ve bu listeye yazmayı atlarsa, silme sessizce eksik çalışır — kullanıcı
# "hesabım silindi" görür, verisi durmaya devam eder. O yüzden bir drift testi
# `api/*.py` içindeki her `_db.collection("...")` çağrısını bu iki listeyle
# karşılaştırıyor (test_account.py).
#
# Sorgular TEK eşitlik filtresi kullanıyor → bileşik indeks gerekmiyor
# (projede beşinci kez aynı tercih).
_OWNED_BY_FIELD = (
    ("favorites", "user_email"),        # favorites.py
    ("collections", "owner_email"),     # collections_store.py
    ("meal_plans", "owner_email"),      # meal_plan.py
    ("shopping_lists", "owner_email"),  # shopping.py
)

# Doküman ID'sinin KENDİSİ e-posta olan koleksiyonlar — sorguya gerek yok.
_OWNED_BY_DOC_ID = ("pantry",)          # pantry.py


def _delete_matching(collection: str, field: str, user_email: str) -> int:
    """Bir koleksiyondaki kullanıcıya ait tüm dokümanları siler, sayısını döner."""
    query = _db.collection(collection).where(
        filter=FieldFilter(field, "==", user_email)
    )

    deleted = 0
    batch = _db.batch()
    pending = 0

    for snap in query.stream():
        batch.delete(snap.reference)
        pending += 1
        deleted += 1
        if pending >= _BATCH_SIZE:
            batch.commit()
            batch = _db.batch()
            pending = 0

    if pending:
        batch.commit()

    return deleted


@timed(slow_ms=5000)
def delete_account(user_email: str) -> dict:
    """Kullanıcının tüm verisini ve hesabını siler.

    Döner: {"favorites": 9, ..., "auth_user": True}

    Auth kaydı EN SON siliniyor (yukarıdaki sıra gerekçesi). Auth silme
    başarısız olursa istisna yukarı fırlatılıyor — kullanıcı hâlâ giriş yapmış
    durumda olduğu için tekrar deneyebilir ve ikinci deneme, verisi zaten
    silinmiş olsa bile, sadece Auth kaydını siler.
    """
    removed: dict[str, int | bool] = {}

    for collection, field in _OWNED_BY_FIELD:
        removed[collection] = _delete_matching(collection, field, user_email)

    for collection in _OWNED_BY_DOC_ID:
        # Doküman ID'si e-postanın kendisi. `clear_pantry`'den farkı: o `items`
        # dizisini boşaltıp dokümanı bırakıyor, burada doküman TAMAMEN gidiyor.
        doc = _db.collection(collection).document(user_email)
        existed = doc.get().exists
        if existed:
            doc.delete()
        removed[collection] = int(existed)

    log.info("Firestore data removed for %r: %s", user_email, removed)

    # ── Auth kaydı — EN SON ──
    # UID token'da var ama `get_current_user_email` yalnızca e-postayı
    # döndürüyor; bu tek ekstra çağrı yalnızca hesap silmede yapılıyor.
    try:
        uid = firebase_auth.get_user_by_email(user_email).uid
        firebase_auth.delete_user(uid)
        removed["auth_user"] = True
    except firebase_auth.UserNotFoundError:
        # Yarıda kalmış bir silmenin ikinci denemesi buraya düşer. Hata değil:
        # istenen son durum zaten sağlanmış.
        log.warning("Auth user %r was already gone; treating as deleted", user_email)
        removed["auth_user"] = True

    return removed
