"""Pantry ("Dolabım") — kullanıcının evinde bulunan malzemelerin kalıcı listesi.

NEDEN VAR: kamera akışı bugüne kadar TEK SEFERLİKTİ — fotoğraftan tanınan
malzemeler ekranda gösterilip sayfa değişince uçuyordu. Pantry onları kalıcı
hale getiriyor: kullanıcı ertesi gün fotoğraf çekmeden "bugün ne pişirebilirim?"
diyebiliyor. Genel bir yapay zekaya dolabını her seferinde baştan anlatman
gerekir; uygulama hatırlıyor.

ŞEMA — kullanıcı başına TEK doküman:
    pantry/{email} → { items: [ {name, added_at}, ... ] }

Dolap her zaman BÜTÜN olarak okunuyor ("hepsini göster", "hepsiyle ara"), o
yüzden tek okuma yetiyor; N+1 yok, bileşik indeks yok, dedup bellekte.
Koleksiyonlardaki dizi kararının aynı gerekçesi. Favorilerdeki "her kayıt ayrı
doküman" yaklaşımı burada gereksiz olurdu: favoriler tek tek eklenip çıkarılan
bağımsız kayıtlar, dolap ise tek bir liste.
"""
import re
from datetime import datetime, timezone

# firebase_admin'i başlatan yer auth.py (favorites/collections_store ile aynı desen)
import auth  # noqa: F401
from firebase_admin import firestore

from logger import timed

_db = firestore.client()
_pantry = _db.collection("pantry")

MAX_NAME_LENGTH = 60
# Üretilen sorgu metninin TOPLAM sınırı. /api/recipes/commentary `query` alanını
# 500 karakterle sınırlıyor (Faz 15c) ve frontend bu metni oraya gönderiyor;
# aşarsa yorum sessizce 422 alıp hiç gelmez.
#
# DİKKAT: bu sınır ek metin DAHİL toplam olmalı. Önce yalnızca malzeme kısmı
# 400'e kırpılıyordu ve üstüne 200 karakterlik additional_text ekleniyordu —
# ölçüldü: 586 karakter, yani sınır aşılıyordu.
MAX_QUERY_CHARS = 500


def validate_ingredient_name(name: str) -> str:
    """Adı temizler ve döner; kullanılamazsa kullanıcıya gösterilecek mesajla
    ValueError fırlatır. Saf fonksiyon — validate_collection_name ile aynı desen.
    """
    cleaned = (name or "").strip()
    if not cleaned:
        raise ValueError("Ingredient name can't be empty.")
    if len(cleaned) > MAX_NAME_LENGTH:
        raise ValueError(f"Ingredient name is too long (max {MAX_NAME_LENGTH} characters).")
    return cleaned


# ── Dolap ↔ tarif eşleştirmesi ────────────────────────────

def _variants(term: str) -> set[str]:
    """Bir terimin tekil/çoğul varyantları.

    Eşleştirmenin İKİ YÖNDE de çalışması gerekiyor: dolapta "tomato" varken
    tarifte "tomatoes" geçebilir, ya da tersi. Kaba ama yeterli bir kural —
    tam bir çekim (lemmatization) kütüphanesi bu iş için fazla ağır olurdu.
    """
    t = term.strip().lower()
    out = {t}
    if t.endswith("ies") and len(t) > 4:
        out.add(t[:-3] + "y")          # berries → berry
    if t.endswith("es") and len(t) > 3:
        out.add(t[:-2])                # tomatoes → tomato
    if t.endswith("s") and len(t) > 2:
        out.add(t[:-1])                # eggs → egg
    return out


def _pantry_patterns(name: str) -> list:
    """Bir dolap malzemesi adı → varyantlarının kelime-sınırlı regex'leri.

    TEK KAYNAK: hem count_pantry_matches (rozet) hem ingredient_in_pantry
    (alışveriş listesi 'eksikler') bunu kullanıyor. Rozet "3/5 malzemen var"
    diyorsa liste tam olarak diğer 2'yi istemeli — iki taraf aynı kuralı
    kullanmazsa çelişir ve kullanıcı fark eder.
    """
    return [re.compile(r"\b" + re.escape(v) + r"(?:es|s)?\b") for v in _variants(name)]


def count_pantry_matches(pantry_names: list[str], recipe_ingredients: list[str]) -> list[str]:
    """Tarifin kullandığı dolap malzemelerini döner (orijinal yazımlarıyla).

    Saf fonksiyon — Katman 1'de test ediliyor.

    KELİME SINIRI ŞART: veri gerçek ve uzun ifadelerden oluşuyor ("boneless
    skinless chicken breast halves", "fat free mozzarella cheese"), o yüzden
    eşleştirme alt-dizi bazlı olmalı — "chicken" ⊂ "boneless skinless chicken
    breast halves" tutmalı. Ama düz `in` kontrolü "egg"i "eggplant" içinde de
    bulurdu; `\\b` sınırı bunu engelliyor.
    """
    if not pantry_names or not recipe_ingredients:
        return []

    lowered = [ing.strip().lower() for ing in recipe_ingredients if ing and ing.strip()]
    if not lowered:
        return []

    matched = []
    for name in pantry_names:
        base = (name or "").strip()
        if not base:
            continue
        # Herhangi bir varyant, herhangi bir malzeme ifadesinde geçiyor mu?
        patterns = _pantry_patterns(base)
        if any(p.search(ing) for p in patterns for ing in lowered):
            matched.append(name)

    return matched


def ingredient_in_pantry(ingredient: str, pantry_names: list[str]) -> bool:
    """Bir tarif malzemesini dolaptaki HERHANGİ bir öğe karşılıyor mu?

    count_pantry_matches'in TERSİ yönü: orada "dolabın hangi öğeleri bu tarifte
    geçiyor" sorulur; burada "bu malzeme dolapta var mı" (yani alışveriş
    listesine EKLENMELİ mi). Aynı eşleştirme kuralı (`_pantry_patterns`) —
    kelime sınırı + iki yönlü çoğul. Saf fonksiyon.

    Alışveriş listesi bunu kullanıyor: eksikler = tarif malzemeleri − dolap.
    """
    ing = (ingredient or "").strip().lower()
    if not ing:
        return False
    for name in pantry_names:
        base = (name or "").strip()
        if not base:
            continue
        if any(p.search(ing) for p in _pantry_patterns(base)):
            return True
    return False


def build_pantry_query(pantry_names: list[str], additional_text: str = "") -> str:
    """Dolap içeriğinden arama sorgusu metni kurar.

    Kamera akışındaki `combined_query` ile aynı biçim — aynı RAG pipeline'ına
    giriyor (embedding → ChromaDB), yeni bir arama mantığı yok, yalnızca malzeme
    listesinin KAYNAĞI farklı (Firestore vs Gemini vision).
    """
    extra = (additional_text or "").strip()
    suffix = f". {extra}" if extra else ""

    # Kırpma bütçesi ek metin DÜŞÜLDÜKTEN sonra hesaplanıyor — yoksa toplam
    # MAX_QUERY_CHARS'ı aşabiliyordu (bkz. yukarıdaki not).
    budget = max(MAX_QUERY_CHARS - len(suffix), 0)

    text = ", ".join(n for n in pantry_names if n and n.strip())
    if len(text) > budget:
        text = text[:budget].rsplit(",", 1)[0]  # yarım malzeme adında kesme

    return f"{text}{suffix}"


# ── Firestore ─────────────────────────────────────────────

@timed
def get_pantry(user_email: str) -> list[dict]:
    """Dolaptaki malzemeler, en son eklenen en üstte."""
    snap = _pantry.document(user_email).get()
    if not snap.exists:
        return []

    items = snap.to_dict().get("items", [])
    # Sıralama bellekte (favoriler/koleksiyonlardaki gerekçe); added_at sabit
    # UTC formatında yazıldığı için metin sıralaması kronolojik.
    items.sort(key=lambda i: i.get("added_at", ""), reverse=True)
    return items


@timed
def add_pantry_items(user_email: str, names: list[str]) -> dict:
    """Birden çok malzemeyi tek seferde ekler (kamera akışı toplu gönderiyor).

    Zaten dolapta olanlar sessizce ATLANIYOR, hata verilmiyor: kullanıcı 8
    malzemelik bir fotoğraf çektiğinde 3'ü zaten varsa bu bir hata değil,
    normal durum.

    GEÇERSİZ İSİMLER DE PARTİYİ DÜŞÜRMÜYOR, ayrı ayrı atlanıyor. Önce her isim
    doğrulanıp ValueError fırlatılıyordu; kamera akışında Gemini'nin döndürdüğü
    TEK tuhaf öğe (boş dize ya da 60 karakterden uzun bir tarif cümlesi) yüzünden
    diğer 7 malzeme de kaydedilmeden istek hata veriyordu. Bunlar kullanıcının
    girdisi değil model çıktısı, dolayısıyla parti bazında cezalandırmak yanlış.

    Dönen sözlük üç kova veriyor: added / skipped (zaten vardı) / invalid.
    """
    doc_ref = _pantry.document(user_email)
    snap = doc_ref.get()
    items = snap.to_dict().get("items", []) if snap.exists else []

    existing = {i["name"].strip().lower() for i in items}
    added, skipped, invalid = [], [], []

    for raw in names:
        try:
            cleaned = validate_ingredient_name(raw)
        except ValueError:
            invalid.append(raw)
            continue

        if cleaned.lower() in existing:
            skipped.append(cleaned)
            continue

        items.append({"name": cleaned, "added_at": str(datetime.now(timezone.utc))})
        existing.add(cleaned.lower())
        added.append(cleaned)

    if added:
        # merge=True — doküman yoksa da oluşturuyor
        doc_ref.set({"items": items}, merge=True)

    return {"added": added, "skipped": skipped, "invalid": invalid}


@timed
def clear_pantry(user_email: str) -> int:
    """Dolabı tamamen boşaltır, silinen malzeme sayısını döner.

    Tek tek silmenin yerine geçiyor: 11 malzemelik bir dolabı boşaltmak 11 ayrı
    istek + 11 Firestore okuma/yazma turu demekti (ölçüldü: her biri ~250-580 ms,
    toplam ~4 sn). Burada tek okuma + tek yazma.
    """
    doc_ref = _pantry.document(user_email)
    snap = doc_ref.get()
    if not snap.exists:
        return 0

    count = len(snap.to_dict().get("items", []))
    if count:
        doc_ref.set({"items": []}, merge=True)
    return count


def remove_pantry_item(user_email: str, name: str):
    doc_ref = _pantry.document(user_email)
    snap = doc_ref.get()
    if not snap.exists:
        raise ValueError("This ingredient is not in your pantry.")

    items = snap.to_dict().get("items", [])
    target = (name or "").strip().lower()
    remaining = [i for i in items if i["name"].strip().lower() != target]

    if len(remaining) == len(items):
        raise ValueError("This ingredient is not in your pantry.")

    doc_ref.set({"items": remaining}, merge=True)
