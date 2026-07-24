"""Meal Planner — kullanıcının haftalık yemek takvimi.

NEDEN VAR: Pantry şu anın fotoğrafı ("elimde ne var"), plan geleceğe verilmiş bir
söz ("ne pişireceğim"). Aynı zamanda alışveriş listesinin ÖNKOŞULU — "ne almam
lazım?" sorusu ancak plan bilinirse hesaplanabilir:

    Pantry (elimde ne var) + Plan (ne pişireceğim) → Eksikler → Alışveriş listesi

ŞEMA — hafta başına TEK doküman, bileşik ID (favorilerdeki desen):

    meal_plans/{email}_{2026-07-27} → {
        owner_email, week_start,
        entries: [ {date, slot, recipe_id, added_at}, ... ]
    }

Birim neden HAFTA: ekranda her zaman tek bir hafta var, dolayısıyla hafta
görünümü tek okuma. Elenen iki alternatif:
  - Tüm haftalar tek dokümanda (pantry gibi) → bir haftayı göstermek için bütün
    geçmişi okumak gerekirdi.
  - Girdi başına doküman (favoriler gibi) → owner + tarih aralığı sorgusu
    BİLEŞİK İNDEKS isterdi; bu projede üç kez bilinçli olarak kaçınıldı.

Sahiplik ID'nin içinde olduğu için koleksiyonlardaki `_owned_doc` kontrolüne
gerek yok (orada auto-ID kullanıldığı için gerekiyordu).

FAVORİLERLE İLİŞKİ YOK (koleksiyonların aksine, bilinçli): plan bir takvim,
düzenleme katmanı değil. Bir tarifi bir kez denemek için planlamak onu kalıcı
kaydetmek anlamına gelmez; otomatik favorileme listeyi tek seferlik denemelerle
kirletirdi. Ters yön daha da kötü olurdu: favoriden silmek salı akşamını sessizce
boşaltırdı. Sarkan kayıt riski yok, çünkü tarif verisi Firestore'da değil
SALT-OKUNUR ChromaDB'de — plan girdisi hiçbir zaman kırık ID'ye işaret edemez.
"""
from datetime import date, datetime, timedelta, timezone

# firebase_admin'i başlatan yer auth.py (favorites/collections_store/pantry deseni)
import auth  # noqa: F401
from firebase_admin import firestore

from logger import timed

_db = firestore.client()
_plans = _db.collection("meal_plans")

SLOTS = ("breakfast", "lunch", "dinner")

# Tarih aralığı sınırı: `year=9999` gibi çöp dokümanlar açılmasın. Gün cinsinden
# tutuluyor çünkü `date.replace(year=...)` 29 ŞUBAT'ta ValueError fırlatır — o
# gün her tarih reddedilirdi (dört yılda bir uygulamayı kilitleyen tür bir hata).
MAX_YEARS_AHEAD = 1
MAX_YEARS_BACK = 1
_MAX_DAYS_AHEAD = 366 * MAX_YEARS_AHEAD
_MAX_DAYS_BACK = 366 * MAX_YEARS_BACK


# ── Saf fonksiyonlar (Katman 1'de test ediliyor) ──────────

def week_start_for(date_str: str) -> str:
    """Verilen tarihin içinde bulunduğu haftanın PAZARTESİSİ (ISO 8601).

    KRİTİK FONKSİYON: doküman ID'sini bu belirliyor, yani okuma ve yazma aynı
    sonucu vermezse veri iki ayrı dokümana bölünür ve kullanıcı planını
    kaybetmiş gibi görünür.

    Hafta pazartesi başlıyor (ISO 8601). Bu karar doküman ID'sine GÖMÜLÜ —
    sonradan pazara çevirmek mevcut haftaları yetim bırakır.
    """
    d = _parse_date(date_str)
    return (d - timedelta(days=d.weekday())).isoformat()  # weekday(): Pazartesi = 0


def _parse_date(date_str: str) -> date:
    """`YYYY-MM-DD` metnini date'e çevirir; olmazsa kullanıcıya gösterilecek
    mesajla ValueError fırlatır."""
    try:
        return date.fromisoformat((date_str or "").strip())
    except (ValueError, AttributeError):
        raise ValueError("Invalid date. Expected format: YYYY-MM-DD.")


def validate_date(date_str: str, bounded: bool = True) -> str:
    """Tarihi doğrular ve `YYYY-MM-DD` olarak döner.

    SUNUCU "BUGÜN"Ü PLAN KARARI İÇİN KULLANMIYOR: Render UTC'de çalışıyor,
    kullanıcı Istanbul'da. Pazartesi 01:00'de plan yapan kullanıcı için sunucuda
    hâlâ pazar olurdu ve "bu tarih geçmişte" gibi yanlış kararlar çıkardı. Tarih
    her zaman istemciden geliyor; buradaki tek iş takvim aritmetiği. Aralık
    sınırı da yıl ölçeğinde olduğu için saat dilimi farkı kararı değiştiremez.

    `bounded=False` OKUMA ve SİLME yollarında kullanılıyor. Sınırın amacı
    `year=9999` gibi ÇÖP DOKÜMAN AÇILMASINI engellemek, yani yalnızca yazmayla
    ilgili. Okumada da uygulansaydı bir yıldan eski planlar zamanla erişilemez
    hale gelirdi: ne görüntülenebilir ne silinebilirlerdi. Kayıtlı veriye her
    zaman ulaşılabilmeli.
    """
    d = _parse_date(date_str)

    if bounded:
        today = datetime.now(timezone.utc).date()
        if d < today - timedelta(days=_MAX_DAYS_BACK):
            raise ValueError("That date is too far in the past.")
        if d > today + timedelta(days=_MAX_DAYS_AHEAD):
            raise ValueError("That date is too far in the future.")

    return d.isoformat()


def validate_slot(slot: str) -> str:
    cleaned = (slot or "").strip().lower()
    if cleaned not in SLOTS:
        raise ValueError(f"Invalid meal slot. Expected one of: {', '.join(SLOTS)}.")
    return cleaned


def validate_week(week_str: str) -> str:
    """Hafta parametresini doğrular ve o haftanın pazartesisine NORMALİZE eder.

    İstemci haftanın ortasından bir tarih gönderse bile doğru dokümana
    yöneliyoruz — aksi hâlde `?week=2026-07-29` ayrı bir doküman açardı ve aynı
    hafta iki yere bölünürdü.

    Sınırsız (`bounded=False`): yalnızca okuma ve hafta temizlemede kullanılıyor,
    yeni doküman açmıyor — kullanıcı istediği kadar geriye/ileriye gidebilmeli.
    """
    return week_start_for(validate_date(week_str, bounded=False))


def _entry_key(entry: dict) -> tuple:
    return (entry.get("date"), entry.get("slot"))


def upsert_entry(entries: list[dict], date_str: str, slot: str, recipe_id: str) -> list[dict]:
    """Slota tarif koyar; slot doluysa ÜZERİNE YAZAR. Saf fonksiyon.

    Replace davranışı bilinçli: kullanıcı salı akşamını değiştirmek istediğinde
    frontend'in "önce sil, sonra ekle" diye iki tur atmasına gerek kalmıyor.

    SLOT BAŞINA TEK TARİF bir POLİTİKA, şema kısıtı değil — `entries` bir dizi
    ve aynı (date, slot) ikilisi teknik olarak iki kez bulunabilir. Yani
    ileride "akşam yemeği = ana yemek + garnitür" istenirse MİGRASYON GEREKMEZ.
    """
    key = (date_str, slot)
    kept = [e for e in entries if _entry_key(e) != key]
    kept.append({
        "date": date_str,
        "slot": slot,
        "recipe_id": str(recipe_id),
        "added_at": str(datetime.now(timezone.utc)),
    })
    return kept


def sort_entries(entries: list[dict]) -> list[dict]:
    """Girdileri gün, sonra öğün sırasına dizer (kahvaltı → öğle → akşam).

    Sıralama Firestore'da değil bellekte — favoriler/koleksiyonlar/pantry'deki
    aynı gerekçe (bileşik indeks istemesin). Bir haftada en fazla 21 girdi var.
    """
    order = {slot: i for i, slot in enumerate(SLOTS)}
    return sorted(entries, key=lambda e: (e.get("date", ""), order.get(e.get("slot"), 99)))


# ── Firestore ─────────────────────────────────────────────

def _doc_id(user_email: str, week_start: str) -> str:
    """Bileşik ID — favorilerdeki `{email}_{recipe_id}` deseninin aynısı.
    Sahiplik ID'nin içinde olduğu için ayrıca owner kontrolü gerekmiyor."""
    return f"{user_email}_{week_start}"


@timed
def get_week(user_email: str, week_start: str) -> list[dict]:
    """Bir haftanın plan girdileri (tek okuma)."""
    snap = _plans.document(_doc_id(user_email, week_start)).get()
    if not snap.exists:
        return []
    return sort_entries(snap.to_dict().get("entries", []))


@timed
def set_entry(user_email: str, date_str: str, slot: str, recipe_id: str) -> dict:
    """Slota tarif koyar (doluysa değiştirir) ve haftanın güncel hâlini döner."""
    week_start = week_start_for(date_str)
    doc_ref = _plans.document(_doc_id(user_email, week_start))
    snap = doc_ref.get()
    entries = snap.to_dict().get("entries", []) if snap.exists else []

    entries = upsert_entry(entries, date_str, slot, recipe_id)

    # merge=True — doküman yoksa da oluşturuyor. owner_email/week_start okuma
    # için gerekli değil (ID yetiyor) ama dokümanı konsoldan bakınca okunabilir
    # kılıyor ve ileride bir bakım sorgusu gerekirse tek dayanak.
    doc_ref.set({
        "owner_email": user_email,
        "week_start": week_start,
        "entries": entries,
    }, merge=True)

    return {"week_start": week_start, "entries": sort_entries(entries)}


# expected=(ValueError,) → boş bir slotu silmeye çalışmak ARIZA DEĞİL, normal
# bir kullanıcı durumu (çift tıklama, bayat sekme). Faz 13'teki ayrımın aynısı:
# bu ERROR (kırmızı) yerine WARNING olarak loglanıyor, yoksa canlı loglarda
# gerçek hatalarla karışırdı.
@timed(expected=(ValueError,))
def remove_entry(user_email: str, date_str: str, slot: str):
    """Slotu boşaltır. Boşsa hata — kullanıcıya "zaten yoktu" demek doğru."""
    week_start = week_start_for(date_str)
    doc_ref = _plans.document(_doc_id(user_email, week_start))
    snap = doc_ref.get()
    if not snap.exists:
        raise ValueError("There is nothing planned for that slot.")

    entries = snap.to_dict().get("entries", [])
    remaining = [e for e in entries if _entry_key(e) != (date_str, slot)]

    if len(remaining) == len(entries):
        raise ValueError("There is nothing planned for that slot.")

    doc_ref.set({"entries": remaining}, merge=True)


@timed
def clear_week(user_email: str, week_start: str) -> int:
    """Haftanın tamamını temizler, silinen girdi sayısını döner.

    Tek okuma + tek yazma — pantry'deki `clear_pantry` ile aynı gerekçe (tek tek
    silmek 21 ayrı istek demekti).
    """
    doc_ref = _plans.document(_doc_id(user_email, week_start))
    snap = doc_ref.get()
    if not snap.exists:
        return 0

    count = len(snap.to_dict().get("entries", []))
    if count:
        doc_ref.set({"entries": []}, merge=True)
    return count
