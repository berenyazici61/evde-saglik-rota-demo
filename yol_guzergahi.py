"""
Gerçek yol ağı (OpenStreetMap) üzerinde hesaplar:
  - olcumler(): noktalar arası YOL mesafesi (km) ve ham sürüş süresi -> rota hesabı (mesafe.py) kullanır
  - guzergah() / rota_cizgisi(): haritada yolların üzerinden giden kıvrımlı çizgi

Yol ağı herkese açık OpenStreetMap verisidir; bir kez indirilip harita_verisi/ klasörüne kaydedilmiştir
(araclar/yol_agi_indir.py). Bütün hesap bu bilgisayarda yapılır; hiçbir konum dışarı gönderilmez.
Yol ağı dosyası yoksa ya da bir nokta yola çok uzaksa çağıran taraf eski kuş uçuşu tahminine döner.

Nokta -> yol bağlantısı: her nokta en yakın kavşağa/yol düğümüne bağlanır; aradaki kısa parça
kuş uçuşu × BAGLANTI_KATSAYISI uzunlukta ve BAGLANTI_HIZ_KMSA hızla sayılır (ev önündeki ara sokak).
"""

import gzip
import heapq
import math
import pickle
from functools import lru_cache
from pathlib import Path

import numpy as np

import ayarlar

YOL_AGI_DOSYASI = Path(__file__).parent / "harita_verisi" / "yol_agi.pkl.gz"
EN_FAZLA_YOLA_UZAKLIK_M = 3000   # nokta en yakın yola bundan uzaksa yol ağı kullanılmaz
EN_YUKSEK_HIZ_MS = 130 / 3.6     # A* tahmini için (sürelerin alt sınırı)
BAGLANTI_KATSAYISI = 1.3
BAGLANTI_HIZ_KMSA = 20

_ag = None  # (koordinat dizisi, komşuluk [(j, süre_sn, uzunluk_m)], ara noktalar)


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
    esik = ayarlar.YOL_AGI_ANA_YOL_ESIGI_KMSA
    for (u, v), (sure, uzunluk, noktalar) in veri["kenarlar"].items():
        if u not in sira or v not in sira:
            continue
        i, j = sira[u], sira[v]
        # OSM hız sınırından ortalama sürüş hızına (kalibrasyon: ayarlar.YOL_AGI_*)
        ana_yol = sure > 0 and uzunluk / sure * 3.6 >= esik
        sure = sure / (ayarlar.YOL_AGI_ANA_YOL_ORANI if ana_yol else ayarlar.YOL_AGI_SEHIR_ICI_ORANI)
        komsu[i].append((j, sure, uzunluk))
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


def _dijkstra(komsu, bas, hedefler: set) -> dict:
    """bas'tan hedeflere en kısa SÜRELİ yollar: {hedef: (süre_sn, uzunluk_m)}.
    Bütün hedefler kesinleşince durur."""
    kalan = set(hedefler)
    sonuc = {}
    en_iyi = {bas: 0.0}
    kuyruk = [(0.0, 0.0, bas)]
    while kuyruk and kalan:
        sure, uzunluk, i = heapq.heappop(kuyruk)
        if sure > en_iyi.get(i, math.inf):
            continue
        if i in kalan:
            sonuc[i] = (sure, uzunluk)
            kalan.discard(i)
        for j, s, u in komsu[i]:
            yeni = sure + s
            if yeni < en_iyi.get(j, math.inf):
                en_iyi[j] = yeni
                heapq.heappush(kuyruk, (yeni, uzunluk + u, j))
    return sonuc


def _baglanti(mesafe_m):
    """Nokta ile en yakın yol düğümü arasındaki kısa parça: (uzunluk_m, süre_sn)."""
    uzunluk = mesafe_m * BAGLANTI_KATSAYISI
    return uzunluk, uzunluk / (BAGLANTI_HIZ_KMSA / 3.6)


def olcumler(noktalar) -> list | None:
    """Noktalar arası yol ölçümleri: m[i][j] = (km, süre_dk) ya da None (o çift için yol ağı kullanılamaz).
    Yol ağı yoksa None döner. Süre, kalibre edilmiş ortalama hızlarla hesaplanır (ayarlar.YOL_AGI_*)."""
    ag = _yukle()
    if ag is None:
        return None
    koord, komsu, _ = ag
    n = len(noktalar)
    yakin = [_en_yakin(koord, p) for p in noktalar]
    kullanilir = [d <= EN_FAZLA_YOLA_UZAKLIK_M for _, d in yakin]
    hedef_dugumler = {yakin[j][0] for j in range(n) if kullanilir[j]}
    tablo = {}
    for kaynak in {yakin[i][0] for i in range(n) if kullanilir[i]}:
        tablo[kaynak] = _dijkstra(komsu, kaynak, hedef_dugumler)

    m = [[None] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i == j or tuple(noktalar[i]) == tuple(noktalar[j]):
                m[i][j] = (0.0, 0.0)
                continue
            if not (kullanilir[i] and kullanilir[j]):
                continue
            (di, mi), (dj, mj) = yakin[i], yakin[j]
            yol = tablo[di].get(dj) if di != dj else (0.0, 0.0)
            if yol is None:
                continue
            ui, si = _baglanti(mi)
            uj, sj = _baglanti(mj)
            if di == dj:  # aynı düğüme bağlılar: doğrudan aradaki kısa yol
                ui, si = _baglanti(_metre(noktalar[i], noktalar[j]))
                uj = sj = 0.0
            m[i][j] = ((yol[1] + ui + uj) / 1000, (yol[0] + si + sj) / 60)
    return m


# ---------------------------------------------------------------------------
# Haritada gösterilecek güzergâh çizgisi
# ---------------------------------------------------------------------------
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
        for j, sure, _u in komsu[i]:
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
