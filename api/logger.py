"""
Merkezi logging + süre ölçümü.

İki iş yapar:
  1. Tek bir yerde logging kurulumu — seviyeler (DEBUG/INFO/WARNING/ERROR) ve
     her seviyeye ayrı renk. Uygulamanın hiçbir yerinde `print` kalmasın diye.
  2. `@timed` decorator'ı ve `timed_block` context manager'ı ile fonksiyon /
     kod bloğu çalışma süresi ölçümü.

Neden decorator? Süre ölçümü fonksiyonun ASIL işiyle ilgisi olmayan bir kaygı
(cross-cutting concern). Her fonksiyonun başına `t0 = time.perf_counter()`,
sonuna `print(...)` yazmak hem tekrar hem de kirlilik: fonksiyon artık iki iş
yapıyor. Decorator bu ölçümü fonksiyonun DIŞINDA, tek bir yerde tutar; ölçülen
fonksiyonun gövdesi hiç değişmez. (Bu, Decorator pattern'in Python'daki
sözdizimsel karşılığı — GoF'un sarmalayıcı nesnesi yerine sarmalayıcı fonksiyon.)

Modül adı bilerek `logger.py` — `logging.py` olsaydı standart kütüphanenin
`logging` modülünü gölgeleyip her şeyi kırardı.

Ortam değişkenleri:
  LOG_LEVEL  DEBUG | INFO | WARNING | ERROR      (varsayılan: INFO)
  LOG_COLOR  1 | 0                               (varsayılan: 1 — renkli)
  SLOW_MS    kaç ms üstü "yavaş" sayılsın        (varsayılan: 1000)
"""

import functools
import inspect
import logging
import os
import sys
import time
from contextlib import contextmanager

# --- Renkler -----------------------------------------------------------------
# ANSI escape kodları. Renk için ek bir kütüphane (colorama vb.) kurmuyoruz:
# hedef ortam Linux container, orada bu kodlar doğrudan çalışıyor.
_RESET = "\033[0m"
_DIM = "\033[2m"
_LEVEL_COLORS = {
    logging.DEBUG: "\033[36m",     # cyan
    logging.INFO: "\033[32m",      # yeşil
    logging.WARNING: "\033[33m",   # sarı
    logging.ERROR: "\033[31m",     # kırmızı
    logging.CRITICAL: "\033[1;37;41m",  # beyaz üstüne kırmızı zemin
}


def _color_enabled() -> bool:
    """
    Varsayılan açık. Renkleri anlamayan bir log toplayıcıya yazılıyorsa
    (ekranda `[32m` gibi çöp görünüyorsa) LOG_COLOR=0 ile kapatılabilir.
    """
    return os.getenv("LOG_COLOR", "1").lower() not in ("0", "false", "off", "no")


def _enable_windows_ansi() -> None:
    """
    Windows'ta eski konsollar ANSI kodlarını varsayılan olarak yorumlamaz.
    Sunucu Linux, ama uvicorn yerelde Windows'ta da çalıştırılabiliyor.
    Başarısız olursa sorun değil — renk yerine düz metin görünür.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        # 7 = stdout(-11) + stderr(-12) için ENABLE_VIRTUAL_TERMINAL_PROCESSING
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-12), 7)
    except Exception:
        pass


class ColorFormatter(logging.Formatter):
    """Seviyeye göre renklendiren formatter. Renksiz modda aynı hizalamayı korur."""

    def __init__(self, use_color: bool):
        super().__init__(datefmt="%H:%M:%S")
        self.use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        level = f"{record.levelname:<8}"
        name = f"{record.name:<10}"
        message = record.getMessage()

        if self.use_color:
            color = _LEVEL_COLORS.get(record.levelno, "")
            level = f"{color}{level}{_RESET}"
            name = f"{_DIM}{name}{_RESET}"
            message = f"{color}{message}{_RESET}" if record.levelno >= logging.WARNING else message

        line = f"{self.formatTime(record, self.datefmt)} | {level} | {name} | {message}"

        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


# --- Kurulum -----------------------------------------------------------------
_configured = False


def setup_logging() -> None:
    """
    Root logger'a tek bir stdout handler bağlar. İki kez çağrılırsa hiçbir şey
    yapmaz — aksi halde her satır iki kez basılırdı (handler birikmesi).

    stdout'a yazıyoruz çünkü Render (ve genel olarak container platformları)
    log akışını stdout/stderr'den okuyor; ayrıca bir dosyaya yazmak
    stateless container'da anlamsız — container ölünce dosya da gider.
    """
    global _configured
    if _configured:
        return

    if _color_enabled():
        _enable_windows_ansi()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(ColorFormatter(use_color=_color_enabled()))

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())

    # Üçüncü parti kütüphaneler INFO seviyesinde çok gürültülü; kendi
    # loglarımız onların arasında kaybolmasın.
    # Not: `google_genai` alt çizgili, yani "google" logger'ının ÇOCUĞU DEĞİL —
    # ayrıca yazılmalı (test sırasında her Gemini çağrısında bir "AFC is enabled"
    # satırı sızdığı görüldü).
    for noisy in (
        "httpx", "httpcore", "urllib3", "chromadb", "google", "google_genai", "grpc"
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Modül başına logger. İlk çağrı kurulumu da yapar."""
    setup_logging()
    return logging.getLogger(name)


# --- Süre ölçümü -------------------------------------------------------------
# Bu eşiğin üstündeki süreler WARNING olarak loglanır. Amaç: log'a bakan kişi
# okumadan, sadece renkten "burada bir yavaşlık var" diyebilsin.
SLOW_MS = float(os.getenv("SLOW_MS", "1000"))


def _fmt(elapsed_ms: float) -> str:
    return f"{elapsed_ms:.1f} ms" if elapsed_ms < 1000 else f"{elapsed_ms / 1000:.2f} s"


def log_duration(log: logging.Logger, label: str, elapsed_ms: float, slow_ms: float = None) -> None:
    """Ölçülmüş bir süreyi seviye kuralına göre loglar (decorator/context manager
    dışında, elle ölçüm yapan yerler için — bkz. llm.py'deki model denemeleri)."""
    if slow_ms is None:
        slow_ms = SLOW_MS
    if elapsed_ms >= slow_ms:
        log.warning("%s took %s (slow, >%s)", label, _fmt(elapsed_ms), _fmt(slow_ms))
    else:
        log.info("%s took %s", label, _fmt(elapsed_ms))


def timed(func=None, *, name: str = None, slow_ms: float = None, expected: tuple = ()):
    """
    Sarmaladığı fonksiyonun çalışma süresini ölçer ve loglar.

    Kullanım:
        @timed                      -> varsayılan eşikle
        @timed(slow_ms=3000)        -> bu fonksiyon için farklı "yavaş" eşiği
        @timed(name="chroma query") -> log'da farklı bir ad

    Seviye seçimi ölçümün kendisinden çıkıyor:
        hızlı  -> INFO     (yeşil)
        yavaş  -> WARNING  (sarı)
        hata   -> ERROR    (kırmızı) + süre yine loglanır, sonra hata yukarı
                  fırlatılır — decorator hatayı YUTMAZ, sadece kaydeder.

    `expected` ile bazı istisnalar ERROR yerine WARNING sayılır. Her istisna
    arıza değildir: süresi dolmuş bir token'ın 401 alması sistemin doğru
    çalıştığının işaretidir, kırmızı yanması yanıltıcı olur. Hangi istisnaların
    "beklenen" olduğunu çağıran bildiriyor — böylece logger.py hiçbir çerçeveye
    (FastAPI vb.) bağımlı kalmıyor:

        @timed(expected=(HTTPException,))

    FastAPI notu: `functools.wraps` `__wrapped__` alanını da kopyaladığı için
    FastAPI orijinal imzayı görmeye devam eder; `Depends(...)` ve Pydantic
    gövdesi decorator'dan etkilenmez. Bu yüzden decorator `@app.post(...)`
    satırının ALTINA yazılmalı (önce sarmala, sonra route'a kaydet).
    """

    def decorate(fn):
        label = name or fn.__name__
        threshold = SLOW_MS if slow_ms is None else slow_ms
        log = get_logger(fn.__module__)

        def report_failure(err, start):
            emit = log.warning if expected and isinstance(err, expected) else log.error
            emit("%s failed after %s: %s", label, _fmt((time.perf_counter() - start) * 1000), err)

        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args, **kwargs):
                start = time.perf_counter()
                try:
                    result = await fn(*args, **kwargs)
                except Exception as e:
                    report_failure(e, start)
                    raise
                log_duration(log, label, (time.perf_counter() - start) * 1000, threshold)
                return result

            return async_wrapper

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                result = fn(*args, **kwargs)
            except Exception as e:
                report_failure(e, start)
                raise
            log_duration(log, label, (time.perf_counter() - start) * 1000, threshold)
            return result

        return wrapper

    # @timed ve @timed(...) kullanımlarının ikisini de destekle
    return decorate(func) if func is not None else decorate


@contextmanager
def timed_block(label: str, logger_name: str = "timing", slow_ms: float = None):
    """
    Fonksiyonun tamamını değil, İÇİNDEKİ bir adımı ölçmek için.

    Aramanın toplam süresini bilmek "nerede yavaşlıyor?" sorusunu cevaplamıyor;
    asıl bilgi kırılımda: filtre çıkarımı ~0 ms, ChromaDB ~300 ms, Gemini
    saniyeler. Decorator dışarıyı, bu context manager içeriyi ölçüyor.

        with timed_block("chromadb query"):
            results = collection.query(...)
    """
    log = get_logger(logger_name)
    threshold = SLOW_MS if slow_ms is None else slow_ms
    start = time.perf_counter()
    try:
        yield
    except Exception as e:
        log.error("%s failed after %s: %s", label, _fmt((time.perf_counter() - start) * 1000), e)
        raise
    log_duration(log, label, (time.perf_counter() - start) * 1000, threshold)


# --- Demo --------------------------------------------------------------------
# `python logger.py` ile seviyeleri/renkleri ve decorator'ı bağımsız gösterir.
if __name__ == "__main__":
    log = get_logger("demo")
    log.debug("DEBUG gorunmuyor cunku varsayilan seviye INFO (LOG_LEVEL=DEBUG ile acilir)")
    log.info("INFO  - normal akis")
    log.warning("WARNING - beklenen ama dikkat isteyen durum")
    log.error("ERROR - islem basarisiz")

    @timed
    def fast_step():
        time.sleep(0.05)

    @timed(name="slow step", slow_ms=100)
    def slow_step():
        time.sleep(0.3)

    @timed
    def broken_step():
        raise ValueError("ornek hata")

    fast_step()
    slow_step()
    with timed_block("manuel blok"):
        time.sleep(0.02)
    try:
        broken_step()
    except ValueError:
        pass
