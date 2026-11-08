"""
Veritabanı yedekleme ve yedekten geri dönme.

SQLite'ın kendi yedekleme özelliği kullanılır: uygulama çalışırken bile tutarlı bir kopya alınır.
Yedekler veri/yedekler klasörüne "evde_saglik_YYYYAAGG_SSDDss_<etiket>.db" adıyla yazılır.
En yeni YEDEK_SAKLAMA_SAYISI yedek tutulur, eskiler silinir.

ÖNEMLİ: Yedekler aynı bilgisayardadır. Bilgisayar arızasına karşı düzenli olarak
harici bir diske / kurumun güvenli sunucusuna kopyalayın. Yedekler hasta verisi içerir.
"""

import datetime as dt
import re
import sqlite3
from pathlib import Path

import pandas as pd

import ayarlar

AD_DESENI = re.compile(r"^evde_saglik_(\d{8}_\d{6})_([a-z_]+)\.db$")


def _kopyala(kaynak: Path, hedef: Path):
    k = sqlite3.connect(kaynak)
    h = sqlite3.connect(hedef)
    try:
        k.backup(h)
    finally:
        h.close()
        k.close()


def yedek_al(etiket: str = "elle") -> Path:
    """Veritabanının yedeğini alır ve yedek dosyasının yolunu döndürür."""
    etiket = re.sub(r"[^a-z_]", "_", etiket.lower())
    ayarlar.YEDEK_KLASORU.mkdir(parents=True, exist_ok=True)
    zaman = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    hedef = ayarlar.YEDEK_KLASORU / f"evde_saglik_{zaman}_{etiket}.db"
    sayac = 1
    while hedef.exists():  # aynı saniyede ikinci yedek
        hedef = ayarlar.YEDEK_KLASORU / f"evde_saglik_{zaman}_{etiket}{'_' * sayac}.db"
        sayac += 1
    _kopyala(ayarlar.VERITABANI, hedef)
    eskileri_temizle()
    return hedef


def yedekler() -> pd.DataFrame:
    """Yedek listesi (en yeni üstte): dosya, zaman, etiket, boyut_kb."""
    satirlar = []
    if ayarlar.YEDEK_KLASORU.exists():
        for p in ayarlar.YEDEK_KLASORU.glob("evde_saglik_*.db"):
            m = AD_DESENI.match(p.name)
            if not m:
                continue
            satirlar.append({"dosya": p.name,
                             "zaman": dt.datetime.strptime(m.group(1), "%Y%m%d_%H%M%S"),
                             "etiket": m.group(2).strip("_"),
                             "boyut_kb": round(p.stat().st_size / 1024)})
    df = pd.DataFrame(satirlar, columns=["dosya", "zaman", "etiket", "boyut_kb"])
    return df.sort_values("zaman", ascending=False).reset_index(drop=True)


def eskileri_temizle():
    liste = yedekler()
    for dosya in liste["dosya"].iloc[ayarlar.YEDEK_SAKLAMA_SAYISI:]:
        (ayarlar.YEDEK_KLASORU / dosya).unlink(missing_ok=True)


def yedek_yolu(dosya_adi: str) -> Path:
    """Yalnızca yedek klasöründeki, ad desenine uyan dosyalara izin verir."""
    if not AD_DESENI.match(dosya_adi):
        raise ValueError("Geçersiz yedek dosyası adı.")
    yol = ayarlar.YEDEK_KLASORU / dosya_adi
    if not yol.exists():
        raise FileNotFoundError(dosya_adi)
    return yol


def geri_don(dosya_adi: str) -> Path:
    """
    Veritabanını seçilen yedeğe geri döndürür.
    Önce mevcut durumun yedeği alınır (geri dönüş geri alınabilsin diye); o yedeğin yolu döndürülür.
    """
    kaynak = yedek_yolu(dosya_adi)
    with sqlite3.connect(kaynak) as k:  # bozuk / ilgisiz dosyaya karşı kontrol
        if k.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Yedek dosyası bozuk görünüyor.")
        k.execute("SELECT COUNT(*) FROM hastalar").fetchone()
    guvenlik = yedek_al("geri_donus_oncesi")
    _kopyala(kaynak, ayarlar.VERITABANI)
    return guvenlik
