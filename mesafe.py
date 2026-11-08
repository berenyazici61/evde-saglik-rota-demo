"""
Noktalar arası mesafe ve yol süresi tahmini.

Şimdilik kuş uçuşu mesafe (Haversine formülü) kullanıyoruz ve bunu bir
yol katsayısıyla uzatıp ortalama hıza bölüyoruz. İleride gerçek yol ağı
süreleri (OSRM / OpenRouteService) ile değiştirilecek.
"""

import math

import ayarlar

DUNYA_YARICAPI_KM = 6371.0


def kus_ucusu_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """İki (enlem, boylam) noktası arasındaki kuş uçuşu mesafe (km)."""
    e1, b1, e2, b2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((e2 - e1) / 2) ** 2 + math.cos(e1) * math.cos(e2) * math.sin((b2 - b1) / 2) ** 2
    return 2 * DUNYA_YARICAPI_KM * math.asin(math.sqrt(h))


def yol_km(a, b) -> float:
    """
    Tahmini yol mesafesi (km). Kısa mesafelerde yollar daha dolambaçlı (katsayı 1,3),
    uzun mesafelerde sahil yolu kıyıya paralel olduğu için kuş uçuşuna yakın (1,1).
    """
    d = kus_ucusu_km(a, b)
    yakin = min(d, ayarlar.YAKIN_KM)
    uzak = max(0.0, d - ayarlar.YAKIN_KM)
    return yakin * ayarlar.YOL_KATSAYISI_YAKIN + uzak * ayarlar.YOL_KATSAYISI_UZAK


def yol_suresi_dk(a, b) -> int:
    """
    Tahmini yol süresi (tam dakika, yukarı yuvarlanır).
    İlk birkaç km şehir içi (yavaş), kalanı ana yol / sahil yolu (hızlı) kabul edilir.
    """
    km = yol_km(a, b)
    sehir = min(km, ayarlar.SEHIR_ICI_KM)
    ana_yol = max(0.0, km - ayarlar.SEHIR_ICI_KM)
    saat = sehir / ayarlar.SEHIR_ICI_HIZ_KMSA + ana_yol / ayarlar.ANA_YOL_HIZ_KMSA
    return math.ceil(saat * 60)


def sure_matrisi(noktalar: list[tuple[float, float]]) -> list[list[int]]:
    """Tüm nokta çiftleri için yol süresi matrisi (dk)."""
    return [[0 if i == j else yol_suresi_dk(a, b) for j, b in enumerate(noktalar)]
            for i, a in enumerate(noktalar)]
