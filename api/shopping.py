"""Alışveriş Listesi — yol haritasının GELİR adımı.

ÇEKİRDEK FİKİR: liste saklanan değil HESAPLANAN bir şey:

    Eksikler = (plandaki tariflerin malzemeleri)  −  (dolaptakiler)
               └──────── meal_plan ────────┘         └── pantry ──┘

Yani Plan + Pantry'nin türevi (pantry rozetiyle aynı mantık). Ayrı bir "liste
üret" adımı yok → asla bayatlamıyor. Bunu MÜMKÜN KILAN şey Faz 17'de eklenen
yapılandırılmış `ingredients` metadata'sı; o olmadan "tarifin malzemeleri −
dolap" çıkarması yapılamazdı.

ÜSTÜNE İNCE BİR KATMAN (overlay) biniyor — hafta başına tek doküman, meal_plan'ın
bileşik-ID desenin aynısı:

    shopping_lists/{email}_{hafta} → {
        owner_email, week_start,
        checked: [ "tomatoes", ... ],        # markette 'aldım' işaretlenenler (isim kümesi)
        custom:  [ {name, added_at}, ... ]    # elle eklenenler ("bir de deterjan")
    }

Türev kısım (eksikler) SAKLANMIYOR, her okumada hesaplanıyor. Sadece overlay
saklanıyor. Bayatlama sorunu böyle çözülüyor: `checked` bir İSİM KÜMESİ, render
anında türev listeyle kesiştiriliyor — plan değişip bir malzeme listeden çıkarsa
ondaki bayat işaret sessizce yok sayılıyor, sync bug'ı yok.

DOLAP EŞLEŞTİRMESİ pantry.ingredient_in_pantry ile — rozetle TEK KAYNAK, asla
çelişmesinler (rozet "3/5 var" diyorsa liste diğer 2'yi ister).
"""
from datetime import datetime, timezone

# firebase_admin'i başlatan yer auth.py (favorites/collections/pantry/meal_plan deseni)
import auth  # noqa: F401
from firebase_admin import firestore

from pantry import ingredient_in_pantry, validate_ingredient_name, canonical_ingredient
from logger import timed

_db = firestore.client()
_shopping = _db.collection("shopping_lists")


# ── Saf fonksiyonlar (Katman 1'de test ediliyor) ──────────

def aggregate_ingredients(planned: list[dict]) -> dict:
    """Plandaki tüm tariflerin malzemelerini tekilleştirir (ilk görülme sırası).

    planned: [{recipe_id, name, ingredients: [...]}, ...]
    döner:   {kanonik_anahtar: {"name": orijinal, "from_recipes": [tarif adları]}}

    Tekilleştirme ÇOĞUL-DUYARLI (`canonical_ingredient`): "garlic clove" ile
    "garlic cloves" tek satıra iner — bazı tarifler aynı malzemenin hem tekilini
    hem çoğulunu içeriyor (dataset kusuru). Görünen ad ilk görülen orijinal
    yazım. Sınır: "chicken breast" ≠ "boneless skinless chicken breast halves"
    (tam malzeme normalizasyonu zor bir NLP işi, kapsam dışı).
    """
    agg: dict = {}   # dict insertion order'ı koruyor
    for recipe in planned:
        rname = (recipe.get("name") or "").strip()
        for ing in recipe.get("ingredients", []):
            original = (ing or "").strip()
            key = canonical_ingredient(original)   # çoğul-duyarlı anahtar
            if not key:
                continue
            if key not in agg:
                agg[key] = {"name": original, "from_recipes": []}
            if rname and rname not in agg[key]["from_recipes"]:
                agg[key]["from_recipes"].append(rname)
    return agg


def missing_ingredients(planned: list[dict], pantry_names: list[str]) -> list[dict]:
    """Plandaki tariflerin, dolapta OLMAYAN malzemeleri (tekilleştirilmiş).

    Saf fonksiyon. Dolap eşleştirmesi pantry.ingredient_in_pantry ile — rozetle
    aynı kural, o yüzden "elimde var" dediğimiz şey listede istenmiyor.
    """
    agg = aggregate_ingredients(planned)
    return [item for item in agg.values() if not ingredient_in_pantry(item["name"], pantry_names)]


def build_list(derived_items: list[dict], checked_names: list[str], custom_items: list) -> list[dict]:
    """Türev eksikler + elle eklenenler; işaret durumunu uygular. Saf fonksiyon.

    Döner: sıralı [{name, source: 'recipe'|'custom', from_recipes, checked}].
    Türevle aynı isimli elle öğe ATLANIR (kullanıcı hem plandan geleni hem elle
    aynısını eklemişse tek satır görünsün).
    """
    checked_set = {(c or "").strip().lower() for c in checked_names}
    seen: set = set()
    out: list[dict] = []

    for item in derived_items:
        key = item["name"].strip().lower()
        seen.add(key)
        out.append({
            "name": item["name"],
            "source": "recipe",
            "from_recipes": item.get("from_recipes", []),
            "checked": key in checked_set,
        })

    for c in custom_items:
        name = (c.get("name") if isinstance(c, dict) else c) or ""
        key = name.strip().lower()
        if not key or key in seen:      # boş ya da türevle çakışan elle öğeyi atla
            continue
        seen.add(key)
        out.append({
            "name": name.strip(),
            "source": "custom",
            "from_recipes": [],
            "checked": key in checked_set,
        })

    return out


# ── Firestore (overlay) ───────────────────────────────────

def _doc_id(user_email: str, week_start: str) -> str:
    return f"{user_email}_{week_start}"


@timed
def get_overlay(user_email: str, week_start: str) -> dict:
    """Haftanın kayıtlı overlay'i (checked + custom). Tek okuma."""
    snap = _shopping.document(_doc_id(user_email, week_start)).get()
    if not snap.exists:
        return {"checked": [], "custom": []}
    data = snap.to_dict()
    return {"checked": data.get("checked", []), "custom": data.get("custom", [])}


@timed
def set_checked(user_email: str, week_start: str, name: str, checked: bool):
    """Bir malzemeyi 'alındı' olarak işaretler / işareti kaldırır.

    İşaret durumu bir İSİM KÜMESİ; türev ya da elle, herhangi bir öğe
    işaretlenebilir. Bayat isimler (plan değişince listeden düşen) zararsız —
    render anında yok sayılıyor.
    """
    key = (name or "").strip()
    if not key:
        raise ValueError("Item name can't be empty.")

    doc_ref = _shopping.document(_doc_id(user_email, week_start))
    snap = doc_ref.get()
    data = snap.to_dict() if snap.exists else {}
    checked_list = data.get("checked", [])

    low = key.lower()
    exists = any((c or "").strip().lower() == low for c in checked_list)
    if checked and not exists:
        checked_list.append(key)
    elif not checked and exists:
        checked_list = [c for c in checked_list if (c or "").strip().lower() != low]
    else:
        return  # değişiklik yok, boşuna yazma

    doc_ref.set({
        "owner_email": user_email,
        "week_start": week_start,
        "checked": checked_list,
    }, merge=True)


@timed
def add_custom(user_email: str, week_start: str, name: str) -> dict:
    """Elle malzeme ekler. Zaten varsa sessizce atlar (pantry deseni).

    İsim doğrulaması pantry.validate_ingredient_name ile (aynı kurallar:
    boş değil, 60 karakter sınırı).
    """
    cleaned = validate_ingredient_name(name)

    doc_ref = _shopping.document(_doc_id(user_email, week_start))
    snap = doc_ref.get()
    data = snap.to_dict() if snap.exists else {}
    custom = data.get("custom", [])

    if any((c.get("name") or "").strip().lower() == cleaned.lower() for c in custom):
        return {"added": None, "skipped": cleaned}

    custom.append({"name": cleaned, "added_at": str(datetime.now(timezone.utc))})
    doc_ref.set({
        "owner_email": user_email,
        "week_start": week_start,
        "custom": custom,
    }, merge=True)
    return {"added": cleaned, "skipped": None}


@timed
def remove_custom(user_email: str, week_start: str, name: str):
    """Elle eklenen bir malzemeyi çıkarır. (Türev malzemeler çıkarılamaz —
    onlar plandan geliyor; plandan/dolaptan değişir.)"""
    doc_ref = _shopping.document(_doc_id(user_email, week_start))
    snap = doc_ref.get()
    if not snap.exists:
        raise ValueError("That item is not on your list.")

    custom = snap.to_dict().get("custom", [])
    low = (name or "").strip().lower()
    remaining = [c for c in custom if (c.get("name") or "").strip().lower() != low]

    if len(remaining) == len(custom):
        raise ValueError("That item is not on your list.")

    doc_ref.set({"custom": remaining}, merge=True)
