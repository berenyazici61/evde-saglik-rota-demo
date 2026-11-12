"""
Haritada gösterilecek GÜZERGÂH: duraklar arasında gerçek yolların üzerinden geçen kıvrımlı çizgi.

- Yalnızca GÖSTERİM içindir. Rota hesabı ve süreler değişmez (kuş uçuşu tahmin: mesafe.py).
- Yol ağı herkese açık OpenStreetMap verisidir ve bir kez indirilip harita_verisi/ klasörüne kaydedilmiştir
  (araclar/yol_agi_indir.py). Güzergâh bu bilgisayarda hesaplanır; hiçbir konum dışarı gönderilmez.
- Yol ağı dosyası yoksa ya da bir nokta yola çok uzaksa eskisi gibi düz çizgi çizilir.
"""

import gzip
import heapq
import math
import pickle
from functools import lru_cache
from pathlib import Path

import numpy as np

YOL_AGI_DOSYASI = Path(__file__).parent / "harita_verisi" / "yol_agi.pkl.gz"
EN_FAZLA_YOLA_UZAKLIK_M = 3000   # nokta en yakın yola bundan uzaksa düz çizgi
EN_YUKSEK_HIZ_MS = 130 / 3.6     # A* tahmini için (sürelerin alt sınırı)

_ag = None  # (koordinat dizisi, düğüm kimlikleri, komşuluk, ara noktalar)


def _metre(a, b) -> float:
    """İki (enlem, boylam) arası yaklaşık kuş uçuşu mesafe (m)."""
    enlem = math.radians((a[0] + b[0]) / 2)
    dy = (a[0] - b[0]) * 111_320
    dx = (a[1] - b[1]) * 111_320 * math.cos(enlem)
    return math.hypot(dx, dy)


def _yukle():
    global _ag
    if _ag is not None:
        return _ag or None
    if not YOL_AGI_DOSYASI.exists():
        _ag = False
        return None
    with gzip.open(YOL_AGI_DOSYASI, "rb") as f:
        veri = pickle.load(f)
    kimlikler = list(veri["dugumler"])
    sira = {n: i for i, n in enumerate(kimlikler)}
    koord = np.array([veri["dugumler"][n] for n in kimlikler], dtype=float)
    komsu = [[] for _ in kimlikler]
    ara = {}
    for (u, v), (sure, _uzunluk, noktalar) in veri["kenarlar"].items():
        i, j = sira[u], sira[v]
        komsu[i].append((j, sure))
        if noktalar:
            ara[(i, j)] = noktalar
    _ag = (koord, komsu, ara)
    return _ag


def hazir() -> bool:
    """Yol ağı dosyası var ve okunabiliyor mu?"""
    return _yukle() is not None


def _en_yakin(koord, nokta):
    enlem_kat = math.cos(math.radians(nokta[0]))
    d2 = (koord[:, 0] - nokta[0]) ** 2 + ((koord[:, 1] - nokta[1]) * enlem_kat) ** 2
    i = int(np.argmin(d2))
    return i, math.sqrt(float(d2[i])) * 111_320


def _a_yildiz(koord, komsu, bas, son):
    """En kısa SÜRELİ yol (A*). Bulunamazsa None."""
    hedef = (koord[son, 0], koord[son, 1])

    def tahmin(i):
        return _metre((koord[i, 0], koord[i, 1]), hedef) / EN_YUKSEK_HIZ_MS

    en_iyi = {bas: 0.0}
    onceki = {}
    kuyruk = [(tahmin(bas), 0.0, bas)]
    while kuyruk:
        _, g, i = heapq.heappop(kuyruk)
        if i == son:
            yol = [i]
            while i in onceki:
                i = onceki[i]
                yol.append(i)
            return yol[::-1]
        if g > en_iyi.get(i, math.inf):
            continue
        for j, sure in komsu[i]:
            yeni = g + sure
            if yeni < en_iyi.get(j, math.inf):
                en_iyi[j] = yeni
                onceki[j] = i
                heapq.heappush(kuyruk, (yeni + tahmin(j), yeni, j))
    return None


@lru_cache(maxsize=20_000)
def _parca(a: tuple, b: tuple) -> tuple:
    ag = _yukle()
    if ag is None or a == b:
        return (a, b)
    koord, komsu, ara = ag
    i, da = _en_yakin(koord, a)
    j, db = _en_yakin(koord, b)
    if da > EN_FAZLA_YOLA_UZAKLIK_M or db > EN_FAZLA_YOLA_UZAKLIK_M:
        return (a, b)
    if i == j:
        return (a, (koord[i, 0], koord[i, 1]), b)
    dugumler = _a_yildiz(koord, komsu, i, j)
    if dugumler is None:
        return (a, b)
    cizgi = [a]
    for u, v in zip(dugumler, dugumler[1:]):
        cizgi.append((float(koord[u, 0]), float(koord[u, 1])))
        cizgi.extend(ara.get((u, v), ()))
    cizgi.append((float(koord[j, 0]), float(koord[j, 1])))
    cizgi.append(b)
    return tuple(cizgi)


def guzergah(a, b) -> list:
    """a'dan b'ye yol üzerinden geçen (enlem, boylam) listesi. Ağ yoksa [a, b]."""
    a = (round(float(a[0]), 6), round(float(a[1]), 6))
    b = (round(float(b[0]), 6), round(float(b[1]), 6))
    return list(_parca(a, b))


def rota_cizgisi(noktalar) -> list:
    """Sıralı duraklar için baştan sona yol üzerinden tek çizgi."""
    cizgi = []
    for a, b in zip(noktalar, noktalar[1:]):
        parca = guzergah(a, b)
        cizgi.extend(parca if not cizgi else parca[1:])
    return cizgi or list(noktalar)
