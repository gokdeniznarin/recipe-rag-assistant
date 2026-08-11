"""api/ingredient_vocab.json'u üretir — sorgudaki olumsuzlamanın hangi kelimeyi
gerçekten bir MALZEME saydığını belirleyen sözlük.

NEDEN GEREKİYOR: `exclusions.py` "no X" ifadesini bir dışlama olarak okuyor, ama
İngilizce'de "no" her zaman bir malzemeyi olumsuzlamıyor — "no bake cookies",
"no knead bread", "no boil lasagna" birer YEMEK ADI. Bunları elle bir kara
listeye yazmak yalnızca aklımıza gelenleri kapatırdı; kuralı veriye bağlamak
aklımıza gelmeyenleri de kapatıyor.

Ölçüldü (9.795 tarif): "bake", "knead", "churn", "fuss", "cook", "fail", "stir"
malzeme metinlerinde SIFIR kez geçiyor, dolayısıyla sözlüğe hiç girmiyorlar ve
"no bake" bir dışlama sayılmıyor. "mushroom" 464, "onion" 3313 kez geçiyor.

KURAL: bir kelime ya bir malzeme ifadesinin SON kelimesi olarak >= 2 kez
geçmeli (yani tek başına bir malzeme adı olabiliyor: "mushroom", "onion"), ya da
herhangi bir yerde >= 10 kez ("almond" hiç son kelime değil — veri hep "almond
butter"/"almond paste" diyor — ama açıkça bir malzeme).
⚠️ İki eşik de ÖLÇÜMLE seçildi. Yalnızca son-kelime kuralı `almond` ve `soy`u
kaçırıyordu; yalnızca sıklık kuralı ise "boil"/"roll"/"oven" gibi kelimeleri
içeri alıyordu (malzeme adlarında tesadüfen geçiyorlar) ve "no boil lasagna"
bozulurdu.

ÇALIŞTIRMA: ingestion'dan SONRA, çünkü kaynağı ChromaDB'nin kendisi —
`recipes_cleaned.csv` değil. Böylece sözlük her zaman GERÇEKTEN aranabilir olan
veriyle aynı; ikisi ayrışamaz.

    python ingestion/build_ingredient_vocab.py

Windows'ta çalıştırılabilir: bu script yalnızca OKUYOR (Faz 8'deki HNSW yazma
sorunu yazma yolunda). Yine de ChromaDB bir klasörü açarken `chroma.sqlite3`'e
dokunuyor — koşudan sonra `git status api/chroma_data` kontrol edilmeli.
"""
import json
import os
import re
from collections import Counter
from pathlib import Path

import chromadb

API_DIR = Path(__file__).resolve().parent.parent / "api"
# CHROMA_PATH env var'ı test_search.py'deki ile aynı amaçla: repodaki klasörü
# açmak commit'li chroma.sqlite3'ü kirletiyor (Faz 8), o yüzden bir kopyaya
# yöneltilebilmeli.
CHROMA_PATH = Path(os.getenv("CHROMA_PATH", API_DIR / "chroma_data"))
OUT_PATH = API_DIR / "ingredient_vocab.json"

MIN_HEAD_COUNT = 2      # "bir malzeme adının son kelimesi olabiliyor"
MIN_ANYWHERE_COUNT = 10  # "malzeme metinlerinde açıkça yaygın"
MIN_WORD_LENGTH = 3


def singularize(word: str) -> str:
    """pantry._singularize_word'ün kopyası — sözlük anahtarları o eşleştiriciyle
    aynı kanonik biçimde olmalı, yoksa "mushrooms" sözlükte bulunamaz."""
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("ss"):
        return word
    if word.endswith("s") and len(word) > 2:
        return word[:-1]
    return word


def build_vocab(ingredient_texts) -> list[str]:
    """`|` ayraçlı malzeme metinlerinden sözlüğü kurar. Saf fonksiyon — testte
    uydurma veriyle çalıştırılabilsin diye ChromaDB'den ayrı."""
    head, anywhere = Counter(), Counter()

    for raw in ingredient_texts:
        for phrase in (raw or "").split("|"):
            words = [
                singularize(w)
                for w in re.findall(r"[a-z]+", phrase.lower())
                if len(w) >= MIN_WORD_LENGTH
            ]
            if not words:
                continue
            head[words[-1]] += 1
            for w in words:
                anywhere[w] += 1

    vocab = {w for w, c in head.items() if c >= MIN_HEAD_COUNT}
    vocab |= {w for w, c in anywhere.items() if c >= MIN_ANYWHERE_COUNT}
    return sorted(vocab)


def build_descriptors(ingredient_texts) -> list[str]:
    """MALZEME metinlerinde geçen `-less` kelimeleri.

    NEDEN: `exclusions.py` "eggless cake" ifadesini bir dışlama olarak okuyor.
    Ama bazı `-less` kelimeleri dışlama isteği DEĞİL, bir malzemenin adının
    parçası: "boneless skinless chicken breast" yazan kullanıcı kemik ve deri
    dışlamak istemiyor, tavuğun cinsini tarif ediyor.

    AYIRT EDİCİ KURAL VERİDEN: bir `-less` kelimesi malzeme listelerinde
    geçiyorsa malzeme tarifidir; yalnızca tarif ADLARINDA geçiyorsa dışlama
    iddiasıdır. Ölçüldü (9.795 tarif):
        malzemede : boneless 456 · skinless 346 · seedless 42   ← istisna
        yalnız adda: crustless · flourless · eggless · meatless ·
                     beefless · creamless · sugarless · cheeseless
    Yani liste tahminle değil sayımla çıkıyor ve yeniden ingestion'da
    kendiliğinden güncelleniyor.
    """
    found = Counter()
    for raw in ingredient_texts:
        for m in re.finditer(r"\b([a-z]{3,})less\b", (raw or "").lower()):
            found[m.group(0)] += 1
    return sorted(found)


def main():
    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    collection = client.get_collection("recipes")
    got = collection.get(include=["metadatas"])

    texts = [md.get("ingredients", "") for md in got["metadatas"]]
    payload = {
        "words": build_vocab(texts),
        "descriptors": build_descriptors(texts),
    }

    OUT_PATH.write_text(json.dumps(payload), encoding="utf-8")
    print(f"recipes:     {len(got['ids'])}")
    print(f"words:       {len(payload['words'])}")
    print(f"descriptors: {payload['descriptors']}")
    print(f"-> {OUT_PATH} ({OUT_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
