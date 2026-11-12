"""
Noktalar arası yol mesafesi (km) ve yol süresi (dk).

12.11.2026'dan itibaren GERÇEK YOL AĞI kullanılır (OpenStreetMap, bu bilgisayarda hesaplanır; bkz. yol_guzergahi.py):
  - mesafe: duraklar arasındaki en hızlı güzergâhın gerçek uzunluğu
  - süre: yol tipine göre ortalama hız (ayarlar.YOL_AGI_*; Of -> 7M ölçümüyle kalibre)
Yol ağı dosyası yoksa ya da bir nokta yola çok uzaksa eski kuş uçuşu tahmini kullanılır (tahmini_km / tahmini_sure_dk).
Trafik yok: süreler ortalama koşullar içindir.
"""

import math

import ayarlar
import yol_guzergahi

DUNYA_YARICAPI_KM = 6371.0

_onbellek: dict = {}   # ((enlem, boylam), (enlem, boylam)) -> (km, dk) ; yalnızca bellekte, diske yazılmaz


def kus_ucusu_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """İki (enlem, boylam) noktası arasındaki kuş uçuşu mesafe (km)."""
    e1, b1, e2, b2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((e2 - e1) / 2) ** 2 + math.cos(e1) * math.cos(e2) * math.sin((b2 - b1) / 2) ** 2
    return 2 * DUNYA_YARICAPI_KM * math.asin(math.sqrt(h))


# --- Eski yöntem (yedek): kuş uçuşu × yol katsayısı, iki kademeli hız ---
def tahmini_km(a, b) -> float:
    """Kısa mesafelerde yollar daha dolambaçlı (katsayı 1,3), uzun mesafelerde sahil yolu (1,1)."""
    d = kus_ucusu_km(a, b)
    yakin = min(d, ayarlar.YAKIN_KM)
    uzak = max(0.0, d - ayarlar.YAKIN_KM)
    return yakin * ayarlar.YOL_KATSAYISI_YAKIN + uzak * ayarlar.YOL_KATSAYISI_UZAK


def tahmini_sure_dk(a, b) -> float:
    km = tahmini_km(a, b)
    sehir = min(km, ayarlar.SEHIR_ICI_KM)
    ana_yol = max(0.0, km - ayarlar.SEHIR_ICI_KM)
    return (sehir / ayarlar.SEHIR_ICI_HIZ_KMSA + ana_yol / ayarlar.ANA_YOL_HIZ_KMSA) * 60


# --- Gerçek yol ağı ---
def _anahtar(p) -> tuple:
    return (round(float(p[0]), 6), round(float(p[1]), 6))


def _olc(noktalar) -> None:
    """Önbellekte olmayan çiftleri yol ağında hesaplayıp önbelleğe yazar."""
    tekil = list(dict.fromkeys(_anahtar(p) for p in noktalar))
    eksik = any((a, b) not in _onbellek for a in tekil for b in tekil)
    if not eksik:
        return
    m = yol_guzergahi.olcumler(tekil)
    for i, a in enumerate(tekil):
        for j, b in enumerate(tekil):
            if (a, b) in _onbellek:
                continue
            if a == b:
                _onbellek[(a, b)] = (0.0, 0.0)
            elif m is not None and m[i][j] is not None:
                _onbellek[(a, b)] = m[i][j]
            else:
                _onbellek[(a, b)] = (tahmini_km(a, b), tahmini_sure_dk(a, b))


def _cift(a, b) -> tuple:
    a, b = _anahtar(a), _anahtar(b)
    if (a, b) not in _onbellek:
        _olc([a, b])
    return _onbellek[(a, b)]


def yol_km(a, b) -> float:
    """a'dan b'ye yol mesafesi (km)."""
    return _cift(a, b)[0]


def yol_suresi_dk(a, b) -> int:
    """a'dan b'ye yol süresi (tam dakika, yukarı yuvarlanır)."""
    return math.ceil(_cift(a, b)[1] - 1e-9)


def sure_matrisi(noktalar: list[tuple[float, float]]) -> list[list[int]]:
    """Tüm nokta çiftleri için yol süresi matrisi (dk)."""
    _olc(noktalar)
    return [[0 if i == j else yol_suresi_dk(a, b) for j, b in enumerate(noktalar)]
            for i, a in enumerate(noktalar)]


def kaynak() -> str:
    """Arayüzde gösterilecek kısa açıklama."""
    if yol_guzergahi.hazir():
        return ("Yol mesafeleri gerçek yol ağından (OpenStreetMap) hesaplanıyor; süreler yol tipine göre ortalama "
                "hızla (Of→7M ölçümüyle kalibre), trafik hariç.")
    return "Yol süreleri kuş uçuşu mesafeden tahmin ediliyor (Of→7M ölçümüyle kalibre)."
