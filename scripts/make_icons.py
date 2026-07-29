"""
PWA ikonlarını üretir (frontend/icons/).

    python scripts/make_icons.py

NEDEN SCRIPT: ikonlar ikili dosya, ama üretimleri KOD olarak dursun istiyoruz —
palet değişirse ya da yeni bir boyut gerekirse elle Photoshop'a dönmek yerine
sayıyı değiştirip tekrar çalıştırmak yeterli. (Aynı gerekçeyle Pillow'a bağımlılık
eklenmedi: PNG encoder'ı stdlib `zlib` + `struct` ile ~20 satır.)

TASARIM: marka işareti zaten sidebar'daki ✦ (dört köşeli parıltı). İkonu ondan
türetmek tutarlılık sağlıyor — kullanıcı ana ekranda gördüğü şeyi uygulamanın
içinde de görüyor. Şekil bir astroid: sqrt(|x|) + sqrt(|y|) <= 1.

TÜM İKONLAR OPAK ve TAM KARE (kendi köşe yuvarlaması YOK):
  - iOS `apple-touch-icon`'u kendisi yuvarlıyor; biz de yuvarlarsak köşelerde
    çift kesim ya da beyaz köşe artığı oluşur.
  - Alfa kanalı yok, çünkü iOS şeffaf ikonu SİYAH zemine bindiriyor.
"""
import math
import os
import struct
import zlib

OLIVE = (0x2D, 0x3B, 0x2D)
CREAM = (0xF5, 0xF0, 0xE8)
ORANGE = (0xE8, 0x82, 0x4A)

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend", "icons")

SS = 3  # supersampling: kenar yumuşatma için piksel başına SS×SS örnek


def write_png(path, width, height, rgb_rows):
    """Minimal PNG yazıcı: 8-bit truecolor (RGB), filtre yok."""
    raw = bytearray()
    for row in rgb_rows:
        raw.append(0)  # her satırın başında filtre tipi = None
        raw.extend(row)

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")

    with open(path, "wb") as f:
        f.write(png)


def sparkle_hit(x, y, cx, cy, r):
    """Dört köşeli parıltının içinde miyiz? (astroid: sqrt|dx| + sqrt|dy| <= 1)"""
    dx = abs(x - cx) / r
    dy = abs(y - cy) / r
    if dx > 1.0 or dy > 1.0:
        return False
    return math.sqrt(dx) + math.sqrt(dy) <= 1.0


def render(size, mark_r, small_r):
    """Olive zemin + krem ana parıltı + turuncu küçük parıltı.

    mark_r / small_r: kenar uzunluğuna ORANLA yarıçap. maskable ikonda küçük
    verilir, çünkü Android ikonun kenarlarını kırpabiliyor (güvenli alan =
    ortadaki %80'lik daire).
    """
    cx, cy = 0.5, 0.53                      # ana parıltı: optik olarak hafif aşağıda
    sx, sy = 0.5 + mark_r * 0.95, 0.53 - mark_r * 0.95   # küçük parıltı: sağ üst

    rows = []
    inv = 1.0 / (SS * size)
    weight = 1.0 / (SS * SS)

    for py in range(size):
        row = bytearray()
        for px in range(size):
            cream_cov = 0
            orange_cov = 0
            for sy_i in range(SS):
                y = (py * SS + sy_i + 0.5) * inv
                for sx_i in range(SS):
                    x = (px * SS + sx_i + 0.5) * inv
                    if sparkle_hit(x, y, sx, sy, small_r):
                        orange_cov += 1
                    elif sparkle_hit(x, y, cx, cy, mark_r):
                        cream_cov += 1

            if not cream_cov and not orange_cov:
                row.extend(OLIVE)
                continue

            a_c = cream_cov * weight
            a_o = orange_cov * weight
            a_bg = 1.0 - a_c - a_o
            for i in range(3):
                v = OLIVE[i] * a_bg + CREAM[i] * a_c + ORANGE[i] * a_o
                row.append(max(0, min(255, int(v + 0.5))))
        rows.append(row)
    return rows


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    # (dosya, boyut, ana yarıçap, küçük yarıçap)
    #   "any" ikonlar: işaret rahat büyük.
    #   maskable: güvenli alan ortadaki %80 daire olduğu için belirgin küçük.
    jobs = [
        ("icon-192.png", 192, 0.30, 0.105),
        ("icon-512.png", 512, 0.30, 0.105),
        ("icon-maskable-512.png", 512, 0.21, 0.075),
        ("apple-touch-icon.png", 180, 0.30, 0.105),
    ]

    for name, size, mark_r, small_r in jobs:
        path = os.path.join(OUT_DIR, name)
        write_png(path, size, size, render(size, mark_r, small_r))
        print(f"[OK] {name}  {size}x{size}  {os.path.getsize(path):,} bytes")


if __name__ == "__main__":
    main()
