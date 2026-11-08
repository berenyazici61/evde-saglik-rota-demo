"""
Bir tarih için rota hesaplamanın ortak adımları.
Hem Rota Planlama sayfası hem de otomatik günlük rota betiği bunu kullanır.
"""

import datetime as dt

import ayarlar
import konum
import optimizasyon
import veri_yukle


def sabit_noktalar():
    """(merkez, 7M Hastanesi) koordinatları; bulunamazsa hata verir."""
    merkez = konum.sabit_konum(ayarlar.MERKEZ)
    lab = konum.sabit_konum(ayarlar.KAN_TESLIM_YERI)
    if merkez is None or lab is None:
        raise RuntimeError("Merkez veya 7M Hastanesi koordinatı yok. Önce araclar/konumlari_bul.py çalıştırın.")
    return merkez, lab


def gunun_verisi(tarih: dt.date, konumsuzlari_varsay: bool = True):
    """(gun, tum_ziyaretler, rotaya_girecek_ziyaretler) döndürür."""
    gun = ayarlar.GUNLER[tarih.weekday()]
    merkez, _ = sabit_noktalar()
    tum = veri_yukle.gunun_ziyaretleri(gun)
    if konumsuzlari_varsay:
        z = veri_yukle.konumsuzlari_merkeze_yerlestir(tum, merkez)
    else:
        z = tum.dropna(subset=["enlem"])
    return gun, tum, z


def hesapla(z, sure_limiti_sn: int = 10):
    """(optimize, mevcut_bolge_sistemi) çözümlerini döndürür. Optimize çözüm mevcut sistemden kötü olamaz."""
    merkez, lab = sabit_noktalar()
    eski = optimizasyon.mevcut_sistem_coz(z, merkez, lab, sure_limiti_sn=max(3, sure_limiti_sn // 2))
    yeni = optimizasyon.rota_coz(z, merkez, lab, sure_limiti_sn=sure_limiti_sn, baslangic=eski)
    return yeni, eski
