"""
Zeytin dalı — marka işaretinin GEOMETRİSİ. Tek kaynak.

NEDEN AYRI DOSYA: aynı şekil iki farklı yerde, iki farklı teknikle çiziliyor —
PNG ikonlarında piksel piksel (make_icons.py), sayfalardaki süslemede SVG
(frontend/icons/olive-branch*.svg). İkisi ayrı ayrı elle çizilseydi kaçınılmaz
olarak birbirinden ayrışırlardı: biri düzeltilir, diğeri eski hâlinde kalır ve
"ikondaki şeklin silüeti" iddiası sessizce yalan olurdu. Burada sayılar bir kez
yazılıyor, iki çıktı da bunlardan türetiliyor.

ŞEKİL, HEPSİ MESAFE FONKSİYONU OLAN ÜÇ İLKELDEN kuruluyor. Bu seçim keyfi
değil — her ilkelin hem tam bir SDF'i (raster için) hem tam bir SVG karşılığı
(vektör için) var, yani iki çıktı YAKLAŞIK değil AYNI şekli veriyor:

    kapsül (yuvarlak uçlu kalın çizgi)  ->  <path> + stroke-linecap="round"
    mercek (iki dairenin kesişimi)      ->  iki yaylı <path>   (yaprak: sivri uçlu)
    daire                                ->  <circle>           (zeytin taneleri)

Yaprak için ELİPS KULLANILMADI: elipsin ucu küt, zeytin yaprağı sivri. İki
dairenin kesişimi (vesica) doğal olarak sivri uçlu ve SVG'de iki yayla birebir
ifade edilebiliyor — döndürülmüş bir elipsin SDF'i ise ancak YAKLAŞIK
hesaplanabilirdi, yani raster ile vektör sessizce ayrışırdı.

Koordinat sistemi: 100x100, y AŞAĞI doğru artıyor (SVG ile aynı).
"""
import math

# ── Dal ────────────────────────────────────────────────────
# Kuadratik bezier: sol alttan sağ üste yükselen bir yay.
_STEM = ((10.0, 88.0), (26.0, 30.0), (90.0, 12.0))
_STEM_SAMPLES = 22         # yayı kaç noktaya bölerek kapsül zincirine çevirelim
_STEM_RADIUS = 2.4         # dolu (ikon) sürümünde sapın yarı kalınlığı

# ── Yapraklar ──────────────────────────────────────────────
# (t, taraf, uzunluk, genişlik, teğetten sapma açısı)
#   t      : sap üzerindeki konum (0 = dip, 1 = uç)
#   taraf  : +1 sağ/alt, -1 sol/üst
#   sapma  : yaprak sapa ne kadar yatık duruyor (küçük açı = sapa yapışık)
_LEAVES = [
    (0.18, -1, 26.0, 7.4, 50.0),
    (0.30, +1, 23.0, 6.6, 58.0),
    (0.52, -1, 27.0, 7.6, 44.0),
    (0.74, +1, 23.0, 6.6, 52.0),
    (0.88, -1, 22.0, 6.2, 42.0),
    (1.00,  0, 20.0, 5.8,  0.0),   # uç yaprağı: sapın devamı, teğet yönünde
]

# ── Zeytin taneleri ────────────────────────────────────────
# (t, teğetten açı, saptan uzaklık, yarıçap)
# İkisi de sapın AYNI yerinden sarkıyor — gerçek bir salkım gibi. Farklı
# t'lere dağıtmak yapraklarla çakışıyordu (ilk çizimde görüldü: daireler
# yaprak konturlarını kesiyor, çizgi sürümü karışıyordu).
_OLIVES = [
    (0.50,  64.0, 17.5, 6.2),
    (0.50, 112.0, 15.5, 5.4),
]
_STALK_RADIUS = 1.3

# Kareye oturtma: şekil ham hâlde 100x100'ün dışına taşıyor. Sınırları elle
# ayarlamak yerine ölçülüp ölçekleniyor — ileride bir yaprağın açısı
# değiştiğinde kompozisyon kendiliğinden düzeliyor, kırpılmıyor.
_MARGIN = 6.0


# ── Ham bezier ─────────────────────────────────────────────

def _raw_point(t):
    (x0, y0), (x1, y1), (x2, y2) = _STEM
    u = 1.0 - t
    return (u * u * x0 + 2 * u * t * x1 + t * t * x2,
            u * u * y0 + 2 * u * t * y1 + t * t * y2)


def _raw_angle(t):
    (x0, y0), (x1, y1), (x2, y2) = _STEM
    u = 1.0 - t
    dx = 2 * u * (x1 - x0) + 2 * t * (x2 - x1)
    dy = 2 * u * (y1 - y0) + 2 * t * (y2 - y1)
    return math.atan2(dy, dx)


def _raw_leaf(t, side, length, width, spread_deg):
    """Yaprağı iki uç noktası + yay yarıçapına çevirir.

    Mercek = yarıçapı r olan iki dairenin kesişimi. h yarı-uzunluk, w yarı-
    genişlikken r = (h² + w²) / (2w) — yayın uçlardan geçip ortada w kadar
    şişmesini sağlayan yarıçap.
    """
    ax, ay = _raw_point(t)
    angle = _raw_angle(t) + side * math.radians(spread_deg)
    bx = ax + math.cos(angle) * length
    by = ay + math.sin(angle) * length
    h, w = length / 2.0, width / 2.0
    return (ax, ay), (bx, by), (h * h + w * w) / (2.0 * w)


def _raw_olive(t, angle_deg, dist, radius):
    """(sapçığın sap üstündeki başlangıcı, sapçığın BİTTİĞİ yer, merkez, r)

    Sapçık tanenin MERKEZİNE değil KENARINA kadar gidiyor: çizgi sürümünde
    daireyi delip içinde görünür bir çizgi bırakırdı.
    """
    ax, ay = _raw_point(t)
    angle = _raw_angle(t) + math.radians(angle_deg)
    dx, dy = math.cos(angle), math.sin(angle)
    cx, cy = ax + dx * dist, ay + dy * dist
    return (ax, ay), (ax + dx * (dist - radius), ay + dy * (dist - radius)), (cx, cy), radius


# ── Kareye oturtma ─────────────────────────────────────────

def _compute_fit():
    xs, ys = [], []

    def add(x, y, r=0.0):
        xs.extend((x - r, x + r))
        ys.extend((y - r, y + r))

    for i in range(_STEM_SAMPLES):
        add(*_raw_point(i / (_STEM_SAMPLES - 1)), _STEM_RADIUS)
    for params in _LEAVES:
        (ax, ay), (bx, by), _ = _raw_leaf(*params)
        w = params[3] / 2.0
        add(ax, ay, w)
        add(bx, by, w)
    for params in _OLIVES:
        _, _, (cx, cy), r = _raw_olive(*params)
        add(cx, cy, r)

    w = max(xs) - min(xs)
    h = max(ys) - min(ys)
    s = (100.0 - 2 * _MARGIN) / max(w, h)
    return s, (100.0 - w * s) / 2.0 - min(xs) * s, (100.0 - h * s) / 2.0 - min(ys) * s


_SCALE, _OX, _OY = _compute_fit()


def _fit(p):
    return (p[0] * _SCALE + _OX, p[1] * _SCALE + _OY)


# ── Oturtulmuş genel arayüz (iki çıktı da bunu kullanıyor) ──

STEM_RADIUS = _STEM_RADIUS * _SCALE
STALK_RADIUS = _STALK_RADIUS * _SCALE


def stem_polyline():
    return [_fit(_raw_point(i / (_STEM_SAMPLES - 1))) for i in range(_STEM_SAMPLES)]


def stem_curve():
    """SVG'nin <path ... Q> için ihtiyaç duyduğu üç kontrol noktası."""
    return tuple(_fit(p) for p in _STEM)


def leaves():
    for params in _LEAVES:
        a, b, r = _raw_leaf(*params)
        yield _fit(a), _fit(b), r * _SCALE


def olives():
    for params in _OLIVES:
        a, stalk_end, c, r = _raw_olive(*params)
        yield _fit(a), _fit(stalk_end), _fit(c), r * _SCALE


# ── SDF (raster için) ──────────────────────────────────────

def _capsule(px, py, ax, ay, bx, by, r):
    vx, vy = bx - ax, by - ay
    wx, wy = px - ax, py - ay
    denom = vx * vx + vy * vy
    h = 0.0 if denom == 0 else max(0.0, min(1.0, (wx * vx + wy * vy) / denom))
    return math.hypot(wx - vx * h, wy - vy * h) - r


def _lens(px, py, a, b, r):
    """İki dairenin kesişimi -> iki SDF'in maksimumu."""
    (ax, ay), (bx, by) = a, b
    mx, my = (ax + bx) / 2.0, (ay + by) / 2.0
    hx, hy = (bx - ax) / 2.0, (by - ay) / 2.0
    half = math.hypot(hx, hy)
    if half == 0 or r < half:
        return 1e9
    off = math.sqrt(r * r - half * half)
    nx, ny = -hy / half, hx / half
    d1 = math.hypot(px - (mx + nx * off), py - (my + ny * off)) - r
    d2 = math.hypot(px - (mx - nx * off), py - (my - ny * off)) - r
    return max(d1, d2)


_SEGMENTS = None
_LEAF_CACHE = None
_OLIVE_CACHE = None


def _cache():
    global _SEGMENTS, _LEAF_CACHE, _OLIVE_CACHE
    if _SEGMENTS is None:
        pts = stem_polyline()
        _SEGMENTS = list(zip(pts, pts[1:]))
        _LEAF_CACHE = list(leaves())
        _OLIVE_CACHE = list(olives())
    return _SEGMENTS, _LEAF_CACHE, _OLIVE_CACHE


def sdf_branch(px, py):
    """Sap + yapraklar + sapçıklar (zeytin TANELERİ hariç — onlar ayrı renkte)."""
    segments, leaf_list, olive_list = _cache()
    d = 1e9

    for (ax, ay), (bx, by) in segments:
        # Ucuz kutu elemesi: uzak segmentte karekök hesabına hiç girme.
        if px < min(ax, bx) - STEM_RADIUS - 1 or px > max(ax, bx) + STEM_RADIUS + 1:
            continue
        if py < min(ay, by) - STEM_RADIUS - 1 or py > max(ay, by) + STEM_RADIUS + 1:
            continue
        d = min(d, _capsule(px, py, ax, ay, bx, by, STEM_RADIUS))

    for a, b, r in leaf_list:
        d = min(d, _lens(px, py, a, b, r))

    for (ax, ay), (sx, sy), _, _ in olive_list:
        d = min(d, _capsule(px, py, ax, ay, sx, sy, STALK_RADIUS))

    return d


def sdf_olives(px, py):
    _, _, olive_list = _cache()
    return min(math.hypot(px - c[0], py - c[1]) - r for _, _, c, r in olive_list)


# ── SVG (silüet / çizgi sürümü) ────────────────────────────

def _f(v):
    return f"{v:.2f}".rstrip("0").rstrip(".")


def svg(stroke_width, color="#E8824A", opacity=None):
    """Şeklin İÇİ DOLU OLMAYAN, tek renk çizgi sürümü.

    `stroke_width` 100 birimlik kutuya göre: 1.6, ~170 px'lik bir süslemede
    ~2.7 px'lik ince bir çizgi demek. Sabit bir ORAN olduğu için şekil çok
    daha küçük basılırsa çizgi de incelir ve kaybolur — bu yüzden dosya
    yalnızca sayfa süslemesi için üretiliyor, küçük bir marka işareti için
    DEĞİL (ölçüldü: ~28 px'te şekil okunmuyor, ayrıntı birbirine giriyor).
    """
    (x0, y0), (x1, y1), (x2, y2) = stem_curve()
    parts = [f'<path d="M{_f(x0)} {_f(y0)}Q{_f(x1)} {_f(y1)} {_f(x2)} {_f(y2)}"/>']

    for (ax, ay), (bx, by), r in leaves():
        # İki yay: uçtan uca gidip geri dönerek merceği kapatıyor (vesica).
        parts.append(
            f'<path d="M{_f(ax)} {_f(ay)}A{_f(r)} {_f(r)} 0 0 1 {_f(bx)} {_f(by)}'
            f'A{_f(r)} {_f(r)} 0 0 1 {_f(ax)} {_f(ay)}Z"/>'
        )

    for (ax, ay), (sx, sy), (cx, cy), r in olives():
        parts.append(f'<path d="M{_f(ax)} {_f(ay)}L{_f(sx)} {_f(sy)}"/>')
        parts.append(f'<circle cx="{_f(cx)}" cy="{_f(cy)}" r="{_f(r)}"/>')

    body = "\n  ".join(parts)
    fade = f' opacity="{_f(opacity)}"' if opacity is not None else ""
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" '
        f'fill="none" stroke="{color}" stroke-width="{_f(stroke_width)}" '
        f'stroke-linecap="round" stroke-linejoin="round"{fade}>\n  {body}\n</svg>\n'
    )
