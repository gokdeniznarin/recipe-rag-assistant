"""
PWA ikonlarını ve sayfa süslemesini üretir (frontend/icons/).

    python scripts/make_icons.py

NEDEN SCRIPT: ikonlar ikili dosya, ama üretimleri KOD olarak dursun istiyoruz —
palet değişirse ya da yeni bir boyut gerekirse elle Photoshop'a dönmek yerine
sayıyı değiştirip tekrar çalıştırmak yeterli. (Aynı gerekçeyle Pillow'a bağımlılık
eklenmedi: PNG encoder'ı stdlib `zlib` + `struct` ile ~20 satır.)

TASARIM: marka işareti bir ZEYTİN DALI — beyaz zemin üstünde koyu zeytin yeşili
dal/yaprak, turuncu taneler. Şeklin kendisi `olive_branch.py`'de tanımlı ve
BURADAKİ PNG'ler ile sayfalardaki SVG silüeti aynı sayılardan türetiliyor;
gerekçesi o dosyanın başında.

⚠️ İKİ ÇIKTI DA BU SCRIPT'TEN geliyor (PNG + SVG). Ayrı ayrı üretilselerdi
"sayfadaki çizgi = ikondaki şekil" iddiası ilk düzenlemede sessizce bozulurdu.

TÜM İKONLAR OPAK ve TAM KARE (kendi köşe yuvarlaması YOK):
  - iOS `apple-touch-icon`'u kendisi yuvarlıyor; biz de yuvarlarsak köşelerde
    çift kesim ya da beyaz köşe artığı oluşur.
  - Alfa kanalı yok, çünkü iOS şeffaf ikonu SİYAH zemine bindiriyor.

KENAR YUMUŞATMA: eskiden piksel başına 3x3 örnek alınıyordu (şekil bir eşitsizlikle
tanımlıydı, "içinde miyim" dışında bir bilgi vermiyordu). Zeytin dalı İŞARETLİ
MESAFE ile tanımlı, yani her pikselde kenara olan uzaklık biliniyor — kapsama
oranı tek örnekle, doğrudan hesaplanıyor. Hem daha doğru hem 9 kat ucuz.
"""
import os
import struct
import zlib

import olive_branch as branch

WHITE = (0xFF, 0xFF, 0xFF)
OLIVE = (0x2D, 0x3B, 0x2D)
ORANGE = (0xE8, 0x82, 0x4A)

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend", "icons")


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


def render(size, fill):
    """Beyaz zemin + zeytin yeşili dal + turuncu taneler.

    `fill`: şeklin kareyi ne kadarını kaplayacağı. maskable ikonda küçük
    veriliyor, çünkü Android ikonun kenarlarını kırpabiliyor (güvenli alan =
    ortadaki %80'lik daire).
    """
    unit = 100.0 / (size * fill)              # bir pikselin birim cinsinden boyu
    offset = (100.0 - 100.0 / fill) / 2.0     # şekli ortalamak için kaydırma

    rows = []
    for py in range(size):
        y = (py + 0.5) * unit + offset
        row = bytearray()
        for px in range(size):
            x = (px + 0.5) * unit + offset
            color = WHITE

            a = _coverage(branch.sdf_branch(x, y), unit)
            if a:
                color = _blend(color, OLIVE, a)
            a = _coverage(branch.sdf_olives(x, y), unit)
            if a:
                color = _blend(color, ORANGE, a)

            row.extend(color)
        rows.append(row)
    return rows


def _coverage(distance, unit):
    """İşaretli mesafe -> pikselin ne kadarı şeklin içinde (0..1)."""
    return max(0.0, min(1.0, 0.5 - distance / unit))


def _blend(base, color, a):
    return tuple(max(0, min(255, int(base[i] * (1 - a) + color[i] * a + 0.5))) for i in range(3))


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    # (dosya, boyut, doluluk)
    jobs = [
        ("icon-192.png", 192, 0.94),
        ("icon-512.png", 512, 0.94),
        ("icon-maskable-512.png", 512, 0.74),
        ("apple-touch-icon.png", 180, 0.94),
    ]
    for name, size, fill in jobs:
        path = os.path.join(OUT_DIR, name)
        write_png(path, size, size, render(size, fill))
        print(f"[OK] {name}  {size}x{size}  {os.path.getsize(path):,} bytes")

    # Sayfa süslemesi: aynı şeklin İÇİ DOLU OLMAYAN, ince turuncu çizgi hâli.
    #
    # Saydamlık DOSYANIN İÇİNE gömülü, CSS'te değil: süsleme `background-image`
    # olarak kullanılıyor ve bir arka plan görselinin saydamlığı CSS'ten ayrı
    # ayarlanamıyor. (Pseudo-eleman + `opacity` yolu da vardı ama `z-index: -1`
    # gerektiriyordu; o da `.page`'i bir yığın bağlamına çevirip içindeki
    # koleksiyon seçicisini/modalları kenar çubuğunun ALTINA düşürebilirdi.)
    svg_path = os.path.join(OUT_DIR, "olive-branch.svg")
    with open(svg_path, "w", encoding="utf-8") as f:
        f.write(branch.svg(stroke_width=1.6, opacity=0.45))
    print(f"[OK] olive-branch.svg  {os.path.getsize(svg_path):,} bytes")


if __name__ == "__main__":
    main()
