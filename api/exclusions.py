"""Sorgudaki olumsuzlamayı ("mantarsız makarna") gerçek bir kısıta çevirir.

🔴 NEDEN VAR — ÖLÇÜLDÜ (9.795 tarifin tamamı, canlı veri, top-5):

    "pasta without mushrooms" → 5/5 sonuçta mantar VAR, 1. sonuç "Mushroom Pasta for 2"
    "salad without onions"    → 5/5 sonuçta soğan VAR, 1. sonuç "Sweet Onion Salad"

    6 vaka toplamı:  "with X" sorguları 22/30 · "without X" sorguları 23/30
    Yani "without" eklemek HİÇBİR ŞEY yapmıyordu — hatta bir tık ters etki.

KÖK SEBEP — bi-encoder cümleyi token vektörlerinin ortalamasına indiriyor.
"mushroom" token'ı vektörü mantar bölgesine ÇEKİYOR; "without" düşük bilgili bir
fonksiyon kelimesi ve ortalamada küçük bir katkı. Ortalama alma işleminde bir
yönü TERSİNE ÇEVİRECEK mekanizma yok. Ölçüldü:

    cos("pasta with mushrooms", "pasta without mushrooms") = 0.9181
    cos("pasta with mushrooms", "noodles with mushrooms")  = 0.8803

Yani model için cümleyi OLUMSUZLAMAK, "pasta"yı "noodles" yapmaktan daha küçük
bir fark. Modelin kusuru değil, eğitim hedefinin sonucu: cümle benzerliği (STS)
veri setlerinde "I like cats" / "I don't like cats" çifti YÜKSEK benzerlikle
etiketlidir — olumsuzlamayı yok saymak öğretilmiş bir davranış.

⚠️ MESAFE BUNU YAKALAYAMIYOR: 6 vakanın 4'ünde "without" sorgusu "with"
sorgusundan DAHA İYİ (düşük) mesafe aldı. Sistem tamamen yanlış cevap verirken
kendinden daha emin — yani eşik/skor tabanlı bir koruma buraya kurulamaz.
(Faz 15'teki mesafe eşiğinin elenme gerekçesiyle aynı aile.)

ÇÖZÜM İKİ ADIMLI, VE TEK BAŞINA İKİSİ DE YETMİYOR:
  1. Dışlanan malzeme sorgu METNİNDEN çıkarılıyor → embedding artık o yöne hiç
     çekilmiyor ("pasta without mushrooms" → "pasta").
  2. Aday havuzu yapılandırılmış `ingredients` metadata'sına göre eleniyor →
     dönen tarifte o malzemenin gerçekten olmadığı GARANTİ.
  (1) olmadan aday havuzunun tamamı mantarlı gelir, eleme sonrası elde neredeyse
  hiç sonuç kalmaz. (2) olmadan sıralama düzelir ama garanti olmaz.

`filters.py`'deki `high protein` düzeltmesiyle AYNI AİLE (karşıt anlam
duyarsızlığı); tek fark oradaki kısıtın sayısal bir metadata alanına
yazılabilmesiydi.

ALERJEN TERİMLERİ BURADA DEĞİL: gluten/dairy/nut için `filters.py`'nin küratörlü
boolean etiketleri var ve onlar bu alt-dizi eşleştirmesinden daha iyi. Burada
tekrar ele alınırlarsa iki farklı kural aynı sorguya uygulanır ve sonuç
gereksiz daralır.
"""
import json
import re
from pathlib import Path

from logger import get_logger

log = get_logger(__name__)

VOCAB_PATH = Path(__file__).resolve().parent / "ingredient_vocab.json"

# Bir sorgudan kaç dışlama kabul edilir. Akıl sağlığı sınırı: normal bir kullanıcı
# iki üç şey dışlar, 15 terimlik bir liste ya saldırı ya ayrıştırma hatasıdır.
MAX_EXCLUSIONS = 3

# Dışlanan terim çıkarıldıktan sonra geriye anlamlı bir sorgu kalmalı. "without
# mushrooms" → "" olurdu; boş metni embed etmek anlamsız, o durumda ORİJİNAL
# sorguya dönülüyor (dışlama filtresi yine çalışıyor, yalnızca embedding
# eskisi gibi kalıyor).
MIN_SEARCH_TEXT_CHARS = 2

# Olumsuzlama tetikleyicileri. Hepsi "bundan sonra gelen şeyi İSTEMİYORUM" diyor.
_TRIGGERS = (
    ("without",),
    ("no",),
    ("not",),
    ("minus",),
    ("except",),
    ("skip",),
    ("hold", "the"),
    ("free", "of"),
    ("allergic", "to"),
    ("i", "hate"),
    ("i", "dislike"),
)

# Tetikleyiciden sonra atlanabilecek dolgu kelimeleri ("without ANY mushrooms").
_FILLERS = {"any", "the", "a", "an", "some", "extra", "added", "much", "more"}

# Terimleri birbirine bağlayanlar ("without mushrooms AND onions").
_CONNECTORS = {"and", "or", "plus", "also"}

# 🔴 SÖZLÜKTE OLAN AMA DIŞLAMA TERİMİ SAYILMAMASI GEREKEN KELİMELER.
# Bunlar malzeme metinlerinde gerçekten geçiyor ("QUICK-cooking oats",
# "MINUTE rice", "FAT FREE milk", "DESSERT topping", "stir FRY sauce") ama
# sorguda birer nitelik kelimesi. Olmasalardı "quick dinner without mushrooms"
# ifadesinde "quick" de bir dışlama sanılabilirdi.
# `fat` ve `free` ayrıca `filters.py`'de zaten ele alınıyor (low fat / diyet
# etiketleri) — burada ikinci kez yorumlamak gereksiz daralma üretirdi.
_NOT_EXCLUDABLE = {
    "quick", "minute", "free", "fat", "meal", "dessert", "fry",
    "time", "easy", "dish", "recipe", "serving", "portion",
}

# `filters.py`'nin küratörlü diyet etiketleriyle ele aldığı terimler (yukarıdaki
# docstring'e bak). Burada dışlama olarak İKİNCİ KEZ uygulanmıyorlar.
_DIET_HANDLED = {"gluten", "dairy", "lactose", "nut"}


def _load_vocab() -> set[str]:
    """Malzeme sözlüğü — hangi kelimenin gerçekten bir malzeme olduğu.

    ⚠️ FAIL-SAFE: dosya yoksa BOŞ küme dönüyor, yani hiçbir dışlama tanınmıyor ve
    arama Faz 29 öncesindeki gibi çalışmaya devam ediyor. Alternatif — sözlüksüz
    "trigger'dan sonraki her kelimeyi malzeme say" — "no bake cookies"i
    "cookies, bake'siz" diye okur ve düzeltmeye çalıştığımızdan daha kötü bir
    hata üretirdi.
    """
    try:
        words = json.loads(VOCAB_PATH.read_text(encoding="utf-8"))
        return {w.strip().lower() for w in words if w and w.strip()}
    except (OSError, ValueError) as e:
        log.warning("Ingredient vocabulary unavailable (%s) - query exclusions disabled", e)
        return set()


VOCAB = _load_vocab()


def _variants(term: str) -> set[str]:
    """pantry._variants'ın BİLİNÇLİ KOPYASI — tekil/çoğul varyant kümesi.

    Neden import edilmiyor: `pantry.py` modül seviyesinde `firestore.client()`
    çağırıyor, yani import etmek bu saf modüle bir Firestore bağımlılığı takardı
    (nutrition.canonical_food_name'in pantry.canonical_ingredient'ı kopyalama
    gerekçesinin aynısı, Faz 21). Kopyanın ayrışmasına karşı test var.

    ⚠️ pantry'de İKİ tekilleştirici var ve KARIŞTIRILMAMALI: `_variants`
    EŞLEŞTİRME için varyant kümesi üretiyor (`-es` kuralı DAHİL, "tomatoes" →
    "tomato"), `_singularize_word` ise dedup ANAHTARI için tek kanonik biçim
    veriyor ve `-es` kuralı bilerek YOK ("cloves" → "clov" verirdi). Buranın
    ihtiyacı eşleştirme, yani `_variants`. İlk sürüm yanlış kardeşi kopyaladı
    ve "without tomatoes" hiçbir domatesli tarifi elemiyordu — test yakaladı.
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


def _is_ingredient(word: str) -> bool:
    """Bu kelime gerçekten bir malzeme mi? (Sözlük — bkz. build_ingredient_vocab.py)

    Varyantların HERHANGİ biri sözlükte geçiyorsa yeterli: sözlük hem tekil hem
    çoğul biçimlerden üretiliyor ve sorgu ikisini de kullanabilir.
    """
    forms = _variants(word)
    if forms & (_NOT_EXCLUDABLE | _DIET_HANDLED):
        return False
    return bool(forms & VOCAB)


_WORD_RE = re.compile(r"[A-Za-z']+")
# "sugar-free", "egg free" — olumsuzlamanın son ek biçimi.
_FREE_SUFFIX_RE = re.compile(r"\b([A-Za-z]+)[-\s]free\b", re.I)


def _trigger_length(words: list[str], i: int) -> int:
    """i konumunda bir tetikleyici varsa kaç kelime uzunluğunda olduğunu döner."""
    for trigger in _TRIGGERS:
        n = len(trigger)
        if words[i:i + n] == list(trigger):
            return n
    return 0


def _collect_terms(words, matches, query: str, j: int, budget: int) -> tuple[list[str], int]:
    """Tetikleyiciden sonraki malzeme terimlerini toplar.

    TEK KELİMELİK terimler alınıyor, çok kelimeli ifadeler DEĞİL — ve bu bilinçli:
    eşleştirme kelime-sınırlı alt-dizi olduğu için "chicken" zaten "boneless
    skinless chicken breast halves"i yakalıyor. Yani kısa terim daha GENİŞ ve
    daha güvenli bir dışlama; "chicken breast" alsaydık göğüs olmayan tavuklu
    tarifler elenmezdi.

    ⚠️ İKİNCİ VE SONRAKİ TERİMLER İÇİN AYIRAÇ ŞART ("and"/"or" ya da virgül).
    Şart olmadan ardışık her malzeme kelimesi yutuluyordu: "pasta without
    mushrooms and cheese sauce" ifadesinde `sauce` da dışlanıyor ve soslu her
    tarif eleniyordu — kullanıcının istemediği tek şey mantarlı peynir sosuydu.
    Ayıraç kuralı ayrıca "without mushrooms tomato basil" gibi bitişik
    dizilimleri tek terime indiriyor.
    """
    terms: list[str] = []
    k = j
    saw_separator = True          # ilk terim ayıraç istemiyor
    while k < len(words) and len(terms) < budget:
        word = words[k]

        # Ham metinde virgül de ayıraç sayılıyor ("without mushrooms, onions")
        if k > 0 and "," in query[matches[k - 1].end():matches[k].start()]:
            saw_separator = True

        if word in _FILLERS:
            k += 1
            continue
        if terms and word in _CONNECTORS:
            saw_separator = True
            k += 1
            continue
        if terms and not saw_separator:
            break
        if not _is_ingredient(word):
            break

        terms.append(word)
        saw_separator = False
        k += 1
    return terms, k


def extract_exclusions(query: str) -> tuple[list[str], str]:
    """(dışlanacak malzemeler, embedding'e verilecek temizlenmiş sorgu).

    Saf fonksiyon — Katman 1'de test ediliyor.

    Hiçbir dışlama bulunamazsa ([], orijinal sorgu) dönüyor, yani çağıran taraf
    için "özellik kapalı" ile "eşleşme yok" aynı yol.
    """
    if not query or not query.strip():
        return [], query or ""

    matches = list(_WORD_RE.finditer(query))
    words = [m.group(0).lower() for m in matches]

    terms: list[str] = []
    cut_spans: list[tuple[int, int]] = []

    i = 0
    while i < len(words) and len(terms) < MAX_EXCLUSIONS:
        n = _trigger_length(words, i)
        if n:
            # Bütçe TOPLAM üzerinden veriliyor: sınırı sonradan `terms[:MAX]` ile
            # uygulamak, kırpılan terimleri yine de sorgudan silerdi — yani metin
            # o malzemeyi aramayı bırakır ama filtre onu elemezdi.
            found, end = _collect_terms(words, matches, query, i + n, MAX_EXCLUSIONS - len(terms))
            if found:
                terms.extend(found)
                # Tetikleyici + terimler sorgudan çıkarılıyor (adım 1).
                cut_spans.append((matches[i].start(), matches[end - 1].end()))
                i = end
                continue
        i += 1

    # Son ek biçimi: "sugar-free cake". Yalnızca kelimenin kendisi çıkarılıyor,
    # "free" duruyor — cümleyi daha fazla bozmanın kazancı yok.
    for m in _FREE_SUFFIX_RE.finditer(query):
        if len(terms) >= MAX_EXCLUSIONS:
            break
        word = m.group(1).lower()
        if _is_ingredient(word) and word not in terms:
            terms.append(word)
            cut_spans.append((m.start(1), m.end(1)))

    if not terms:
        return [], query

    # Metni sondan başa doğru kes ki önceki span'ların konumları kaymasın.
    cleaned = query
    for start, end in sorted(cut_spans, reverse=True):
        cleaned = cleaned[:start] + " " + cleaned[end:]
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.;-")

    if len(cleaned) < MIN_SEARCH_TEXT_CHARS:
        # "without mushrooms" gibi sorgularda geriye anlamlı metin kalmıyor.
        cleaned = query

    return terms, cleaned


def _term_patterns(term: str) -> list[re.Pattern]:
    """pantry._pantry_patterns ile AYNI kural: kelime sınırı + iki yönlü çoğul.

    Kelime sınırı burada da şart — düz alt-dizi araması "egg"i "eggplant"
    içinde bulurdu ve yumurtasız kek arayan kullanıcıdan patlıcanlı tarifleri
    saklardı. (Aynı tuzağın veri tarafındaki hâli: `ham` ⊂ `graham`, Faz 29.)
    """
    return [
        re.compile(r"\b" + re.escape(v) + r"(?:es|s)?\b")
        for v in _variants(term)
    ]


def excluded_terms_in_recipe(recipe_ingredients: list[str], terms: list[str]) -> list[str]:
    """Tarifte gerçekten bulunan dışlanmış terimler. Saf fonksiyon."""
    if not terms or not recipe_ingredients:
        return []

    lowered = [i.strip().lower() for i in recipe_ingredients if i and i.strip()]
    if not lowered:
        return []

    return [
        term
        for term in terms
        if any(p.search(ing) for p in _term_patterns(term) for ing in lowered)
    ]


def filter_excluded(cards: list[dict], terms: list[str]) -> list[dict]:
    """Dışlanan malzemeyi içeren kartları düşürür, sırayı korur.

    ⚠️ MALZEMESİ BOŞ OLAN TARİF ELENMİYOR: `ingredients` alanı Faz 17'de eklendi
    ve eski/eksik kayıtlarda boş olabilir. Boşu "temiz" saymak yanlış-negatif,
    "kirli" saymak ise sonucu sebepsiz yere yok etmek olurdu; ilki kullanıcıya
    daha az zarar veriyor ve mevcut veride hiç boş kayıt yok (9.795/9.795 dolu).
    """
    if not terms:
        return cards
    return [c for c in cards if not excluded_terms_in_recipe(c.get("ingredients", []), terms)]
