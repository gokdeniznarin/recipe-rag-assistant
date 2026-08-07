"""
Anonim (giriş gerektirmeyen) uçlar için basit hız sınırı.

NEDEN VAR: tarif detayı Faz 29'da girişsiz erişilebilir hale geldi — Pinterest'ten
gelen ziyaretçi ve arama motoru kazıyıcıları için. Token doğrulaması artık kapıda
durmadığı için, uç kapasitesiz kalıyor: Render ücretsiz katmanı **0.1 vCPU** ve
9.795 tarifi sırayla çeken bir script hiçbir şey ödemeden konteyneri meşgul eder.

TASARIM — bilerek en basiti (projedeki "design pattern zorlamıyoruz" ilkesi):
sabit pencere + genel süpürme. Kayan pencere (sliding window) sınır anında daha
adil olurdu ama IP başına zaman damgası listesi tutmayı gerektirir; burada
korunan şey saniyeler süren bir hesap değil, milisaniyelik bir okuma. Sabit
pencerede sınırın pencere sınırında iki katına çıkabilmesi kabul edilmiş bir
ödünleşim — amaç kötüye kullanımı durdurmak, kota satmak değil.

BELLEK: sözlük IP başına büyüyor. Pencere dolunca **tamamı siliniyor**, yani
bellek "bir penceredeki tekil IP sayısı" ile sınırlı. IP başına ayrı zamanlayıcı
tutulsaydı sözlüğü ayrıca süpürmek gerekirdi ve unutulan bir süpürme 512 MB'lık
konteynerde sessiz bir bellek sızıntısı olurdu.
"""

import os
import time
from threading import Lock

# 60 istek/dakika: ölçülen maliyet istek başına 1.1–2.8 ms (ID ile `get`,
# 6.4 sn'lik `query` yolu DEĞİL), yani dakikada 60 istek ≈ 0.2 sn CPU. İnsan
# gezinmesinin (sayfa başına 1 çağrı) çok üstünde, scriptli kazımanın altında.
WINDOW_SEC = 60
MAX_REQUESTS = 60

_lock = Lock()
_window_start = 0.0
_hits: dict[str, int] = {}


def client_key(request) -> str:
    """
    İsteği yapan gerçek istemciyi ayırt eden anahtar.

    ⚠️ `request.client.host` TEK BAŞINA KULLANILAMAZ: Render uygulamayı kendi
    proxy'sinin arkasında çalıştırıyor, yani orada her isteğin kaynağı proxy
    görünür. Ona göre sayarsak tek bir yoğun ziyaretçi **bütün interneti**
    sınırlar — koruma, hizmet kesintisine dönüşür. Gerçek istemci
    `X-Forwarded-For`'un ilk girdisinde.

    Başlık istemci tarafından uydurulabilir (yani kararlı bir kimlik değil), ama
    burada amaç kimlik doğrulamak değil kazara/tembel kötüye kullanımı
    yavaşlatmak. Uydurmaya çalışan biri zaten her istekte farklı IP yazabilir;
    ona karşı savunma bu katmanın işi değil.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def is_internal(request) -> bool:
    """
    İstek kendi SSR fonksiyonumuzdan mı geliyor?

    ⚠️ BU MUAFİYET OPSİYONEL DEĞİL: Vercel'deki SSR fonksiyonu tarif detayını
    sunucu tarafında çekiyor, dolayısıyla o çağrıların hepsi **Vercel'in
    IP'lerinden** geliyor. Muafiyet olmasaydı bütün ziyaretçilerin trafiği
    birkaç IP'de toplanır ve SSR yolu birkaç ziyaretçiden sonra kendi kendini
    429'a düşürürdü — hem de tam olarak Pinterest'ten trafik geldiği anda.

    `INTERNAL_API_KEY` ortamda yoksa muafiyet hiç çalışmıyor (yerel geliştirme
    ve testler etkilenmesin diye). Sır olmayan bir varsayılan BİLEREK yok:
    varsayılan bir değer olsaydı herkes onu göndererek sınırı atlardı.
    """
    key = os.getenv("INTERNAL_API_KEY")
    return bool(key) and request.headers.get("x-internal-key") == key


def allow(request) -> bool:
    """
    True = isteğe izin var. Sayacı da bu çağrı artırıyor.

    Kilit gerekli: endpoint `async def` değil düz `def`, yani FastAPI onu bir
    thread havuzunda çalıştırıyor ve eşzamanlı thread'ler aynı sözlüğe yazıyor.
    """
    if is_internal(request):
        return True

    global _window_start

    now = time.monotonic()
    key = client_key(request)

    with _lock:
        if now - _window_start > WINDOW_SEC:
            _hits.clear()          # bellek sınırı buradan geliyor
            _window_start = now

        count = _hits.get(key, 0) + 1
        _hits[key] = count
        return count <= MAX_REQUESTS


def reset() -> None:
    """Testler için: sayaçları sıfırla (testler birbirinin sayacını görmesin)."""
    global _window_start
    with _lock:
        _hits.clear()
        _window_start = 0.0
