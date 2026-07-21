"""
Yerel (Docker) ve canlı (Render) backend'i AYNI istemciden, AYNI isteklerle
ölçüp karşılaştırır.

NEDEN BÖYLE: tarayıcıdan bakınca "canlı yavaş" demek kolay, ama yavaşlığın
ağdan mı yoksa sunucudaki hesaptan mı geldiği ayırt edilemiyor. Aynı istemci
iki ortama da aynı istekleri atınca fark okunabilir hâle geliyor:

  - /api/recipes/{id} sunucuda neredeyse hiç iş yapmıyor (yerelde ~3 ms),
    dolayısıyla canlıdaki süresi neredeyse tamamen AĞ bedeli.
  - /api/recipes/search ise embedding hesabı yapıyor. Oradaki fazlalıktan ağ
    bedelini düşünce geriye kalan CPU payı oluyor — Render ücretsiz katmanda
    0.1 vCPU verdiği için bu pay büyük.

Gemini kullanan uçlar (commentary, from-image) BİLEREK ölçülmüyor: günlük kota
model başına 20 istek, ölçüm uğruna yakmaya değmez.

ÇALIŞTIRMA (repo kökünden, container ayaktayken):
    docker compose exec api python /scripts/benchmark.py

Ayarlar (hepsi opsiyonel):
    REPEAT=10 docker compose exec ... python /scripts/benchmark.py
    LIVE_URL=https://... (varsayılan: Render adresi)
"""
import json
import os
import statistics
import sys
import time
import urllib.request

# Bu script api container'ının içinde çalışır; uygulama kodu orada /app'te.
# Python, `python /scripts/x.py` çağrısında sys.path'e script'in klasörünü
# koyuyor (çalışma dizinini değil), o yüzden /app elle ekleniyor.
sys.path.insert(0, os.getenv("APP_DIR", "/app"))

from firebase_admin import auth as fa  # noqa: E402

import auth  # firebase_admin'i başlatır  # noqa: F401,E402

# Bu iki değer zaten public: web API key'i frontend/js/firebase.js'te,
# Render adresi frontend/js/config.js'te commit'li. Gizli olan bir şey yok.
API_KEY = os.getenv("FIREBASE_WEB_API_KEY", "AIzaSyBRqjiiyobEKHsPRFQp_eyeLKkT82WhTZg")
LIVE = os.getenv("LIVE_URL", "https://recipe-rag-assistant-api-7g6a.onrender.com")
LOCAL = os.getenv("LOCAL_URL", "http://localhost:8080")
REPEAT = int(os.getenv("REPEAT", "5"))

# Ölçümde kullanılan sabit tarif: aramanın referans sonuçlarından biri.
RECIPE_ID = "17450"
QUERY = "gluten free quick chicken dinner"


def call(url, payload=None, headers=None, timeout=180):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    if data:
        req.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read())


def get_id_token():
    """
    Endpoint'ler korumalı olduğu için gerçek bir Firebase ID token gerekiyor.
    Mevcut bir kullanıcının uid'si için Admin SDK ile custom token üretilip
    Identity Toolkit üzerinden ID token'a çevriliyor — yeni kullanıcı
    oluşturulmuyor, mevcut veriye dokunulmuyor.
    """
    user = next(iter(fa.list_users().iterate_all()))
    custom = fa.create_custom_token(user.uid).decode()
    token = call(
        f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken?key={API_KEY}",
        {"token": custom, "returnSecureToken": True},
    )["idToken"]
    return token, user.email


def fmt(ms):
    return f"{ms:.0f} ms" if ms < 1000 else f"{ms / 1000:.2f} s"


def main():
    token, email = get_id_token()
    headers = {"authorization": f"Bearer {token}"}
    print(f"Token alindi (kullanici: {email})")

    cases = [
        ("POST /api/recipes/search",
         lambda base: call(f"{base}/api/recipes/search",
                           {"query": QUERY, "n_results": 5}, headers)),
        (f"GET  /api/recipes/{RECIPE_ID}",
         lambda base: call(f"{base}/api/recipes/{RECIPE_ID}", None, headers)),
        ("GET  /api/favorites",
         lambda base: call(f"{base}/api/favorites", None, headers)),
        ("GET  /api/favorites?include_details=true",
         lambda base: call(f"{base}/api/favorites?include_details=true", None, headers)),
    ]

    # Isınma turu iki işe yarıyor:
    #  1. Yeni üretilen token'ın "gelecekte üretilmiş" sayılmaması için birkaç
    #     saniye geçmesi gerekebiliyor (container saati Google'ınkinden sapabilir;
    #     Docker Desktop/WSL2'de bilinen bir durum). Isınmadan 401 alınabiliyor.
    #  2. Canlı uykudaysa ilk istek onu uyandırıyor (30-60 sn) — o süre ölçüme
    #     karışmasın.
    print("Isinma turu (canli uykudaysa uyandirir, 30-60 sn surebilir)...", flush=True)
    time.sleep(5)
    for base in (LOCAL, LIVE):
        for _, fn in cases:
            try:
                fn(base)
            except Exception as e:
                print(f"  isinma {base}: {e}")

    results = {}
    for label, fn in cases:
        results[label] = {}
        for env, base in (("yerel", LOCAL), ("canli", LIVE)):
            times = []
            for _ in range(REPEAT):
                start = time.perf_counter()
                try:
                    fn(base)
                    times.append((time.perf_counter() - start) * 1000)
                except Exception as e:
                    print(f"  HATA {label} @ {env}: {e}")
            results[label][env] = times

    print(f"\nHer istek {REPEAT} kez calistirildi; asagidaki degerler ORTANCA (medyan).\n")
    print(f"{'Istek':<42}{'YEREL':>11}{'CANLI':>11}{'FARK':>11}{'KAT':>7}")
    print("-" * 82)
    medians = {}
    for label, data in results.items():
        if not data["yerel"] or not data["canli"]:
            continue
        lo = statistics.median(data["yerel"])
        li = statistics.median(data["canli"])
        medians[label] = (lo, li)
        print(f"{label:<42}{fmt(lo):>11}{fmt(li):>11}{fmt(li - lo):>11}{li / lo:>6.1f}x")

    # --- Yorum ---------------------------------------------------------------
    # Tarif detayi sunucuda is yapmiyor; canlidaki fazlaligi saf ag bedeli sayip
    # aramadaki fazlaliktan dusuyoruz. Kalan, sunucudaki hesap farki.
    detail = next((k for k in medians if k.startswith("GET  /api/recipes/")), None)
    search = "POST /api/recipes/search"
    if detail and search in medians:
        net = medians[detail][1] - medians[detail][0]
        total = medians[search][1] - medians[search][0]
        cpu = total - net
        print("\nYORUM")
        print(f"  Ag bedeli (tarif detayindan)        : {fmt(net)}")
        print(f"  Aramadaki toplam fazlalik           : {fmt(total)}")
        print(f"  Bunun agla acilanmayan kismi (CPU)  : {fmt(cpu)}")
        print("  -> Render ucretsiz katman 0.1 vCPU veriyor; embedding hesabi CPU'ya bagli.")
        print("     Dogrulamak icin Render Logs'ta 'chromadb query took ...' satirina bak.")

    print("\nHam olcumler (ms):")
    for label, data in results.items():
        print(f"  {label}")
        print(f"    yerel: {', '.join(f'{t:.0f}' for t in data['yerel']) or '-'}")
        print(f"    canli: {', '.join(f'{t:.0f}' for t in data['canli']) or '-'}")


if __name__ == "__main__":
    main()
