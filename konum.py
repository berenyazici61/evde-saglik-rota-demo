"""
Hasta, merkez ve kan teslim yeri için koordinat bulma.

GİZLİLİK KARARI (07.11.2026): Hastaların kesin ev konumları kullanılmayacak.
Her hasta, tarif edilen yerin (mahalle / bilinen yer / cadde) ~200 m çevresinde,
hasta koduna göre sabit kalan rastgele bir noktaya ("temsili ev") atanır.
Aynı hasta her çalıştırmada aynı noktaya düşer.

Koordinatlar veri/konum_onbellek.csv dosyasında saklanır. Bu dosyayı
araclar/konumlari_bul.py doldurur. Yanlış bir koordinatı dosyada elle
düzeltebilirsiniz (kaynak sütununa "elle" yazın; tekrar aranmaz).
"""

import hashlib

import pandas as pd

import ayarlar

ILCELER = {"Arsin", "Akçaabat", "Of", "Çarşıbaşı", "Yomra", "Sürmene", "Vakfıkebir"}

# Mahalle bilgisinden daha iyi bir sorgu bildiğimiz hastalar.
# Liste: sırayla denenecek sorgular (ilk bulunan kullanılır). Boş liste = konum bilinmiyor.
# "Kaşüstü hastanesi": Kaşüstü, Topal Osman Sk, 61290 Yomra/Trabzon (kullanıcı bildirdi)
# Topal Osman Sk. OpenStreetMap'te kayıtlı değil -> Kaşüstü mahalle merkezi kullanılıyor.
KASUSTU_HASTANE = ["Kaşüstü, Trabzon, Türkiye"]
KONAKLAR_IMAM_HATIP = ["Kanuni Anadolu İmam Hatip Lisesi, Trabzon, Türkiye",
                       "Konaklar, Ortahisar, Trabzon, Türkiye"]
OZEL_SORGULAR = {
    "H001": ["Arsin, Trabzon, Türkiye"],          # "Arma / Arsin", tarif belirsiz
    "H004": ["Yeşilyalı, Arsin, Trabzon, Türkiye"],
    "H031": ["Yeşilyalı, Arsin, Trabzon, Türkiye"],
    "H010": ["Of, Trabzon, Türkiye"],             # "Merkez / Of merkez"
    "H037": ["Çarşıbaşı, Trabzon, Türkiye"],      # kullanıcı teyit etti (Bahçecik değil)
    # 07.11.2026 kullanıcıdan gelen konumlar:
    "H003": KASUSTU_HASTANE,                      # "Kaşüstü hastanesinin yakını"
    "H036": KASUSTU_HASTANE,                      # "Kaşüstü hastanesinin yakını"
    "H022": ["Yedikaldırım, Trabzon, Türkiye",                # OSM: Yedikaldırım Caddesi, Çukurçayır
             "Çukurçayır, Ortahisar, Trabzon, Türkiye"],   # Çukurçayır, Yedi Kaldırım Sk.
    "H026": ["Çimenli, Ortahisar, Trabzon, Türkiye",
             "Çimenli, Trabzon, Türkiye"],                  # "Çimenli kasabı"
    "H042": ["Kilpa, Trabzon, Türkiye"],                    # "Tanjant, Kilpa üstü" (Kilpa: Beşirli, sahil yolu)
    "H023": KONAKLAR_IMAM_HATIP,                  # "Konaklar, Kanuni imam hatip yanı" (Excel'de Kavaklar)
    "H041": KONAKLAR_IMAM_HATIP,
    "H044": ["Dolaylı, Trabzon, Türkiye"],        # "Dolaylı köyü" (Excel'de Delialtı)
    "H028": ["Köfteci Ali, Söğütlü, Akçaabat, Trabzon, Türkiye",
             "Söğütlü, Trabzon, Türkiye"],        # "Söğütlü, Köfteci Ali civarı"
}


def hasta_sorgulari(hasta_kodu: str, mahalle: str) -> list[str]:
    """Bir hasta için sırayla denenecek adres sorguları."""
    if hasta_kodu in OZEL_SORGULAR:
        return list(OZEL_SORGULAR[hasta_kodu])
    if not isinstance(mahalle, str) or mahalle.strip() in ("", "–"):
        return []
    m = mahalle.replace(" Mahallesi", "").strip()
    if m in ILCELER:
        return [f"{m}, Trabzon, Türkiye"]
    return [f"{m}, Ortahisar, Trabzon, Türkiye", f"{m}, Trabzon, Türkiye"]


def onbellegi_oku() -> pd.DataFrame:
    if not ayarlar.KONUM_ONBELLEK_CSV.exists():
        return pd.DataFrame(columns=["sorgu", "enlem", "boylam", "kaynak", "bulunan_ad"])
    return pd.read_csv(ayarlar.KONUM_ONBELLEK_CSV)


def _sorgudan_koordinat(sorgular: list[str], onbellek: pd.DataFrame):
    """Önbellekte bulunan ilk sorgunun (enlem, boylam, sorgu) değerini döndürür."""
    bulunan = onbellek.dropna(subset=["enlem", "boylam"]).set_index("sorgu")
    for s in sorgular:
        if s in bulunan.index:
            satir = bulunan.loc[s]
            return float(satir["enlem"]), float(satir["boylam"]), s
    return None


def _kaydirma(hasta_kodu: str) -> tuple[float, float]:
    """Hasta koduna göre sabit, küçük bir kaydırma (±0.002° ≈ ±200 m)."""
    h = int(hashlib.md5(hasta_kodu.encode()).hexdigest(), 16)
    return ((h % 1000) / 1000 - 0.5) * 0.004, (((h // 1000) % 1000) / 1000 - 0.5) * 0.004


def hasta_konumlari(hastalar: pd.DataFrame) -> pd.DataFrame:
    """hasta_kodu, enlem, boylam, konum_kaynagi sütunlarını döndürür."""
    onbellek = onbellegi_oku()
    satirlar = []
    for _, h in hastalar.iterrows():
        sonuc = _sorgudan_koordinat(hasta_sorgulari(h["hasta_kodu"], h["mahalle"]), onbellek)
        if sonuc is None:
            satirlar.append({"hasta_kodu": h["hasta_kodu"], "enlem": None, "boylam": None,
                             "konum_kaynagi": "Konum yok"})
            continue
        enlem, boylam, sorgu = sonuc
        de, db = _kaydirma(h["hasta_kodu"])
        satirlar.append({"hasta_kodu": h["hasta_kodu"], "enlem": enlem + de, "boylam": boylam + db,
                         "konum_kaynagi": f"Yaklaşık: {sorgu.split(',')[0]}"})
    return pd.DataFrame(satirlar)


def canli_ara(sorgu: str) -> tuple[float, float] | None:
    """
    Tek bir adres sorgusunu OpenStreetMap'te arar ve sonucu önbelleğe ekler.
    Gizlilik: yalnızca yer adı gönderilir, hasta bilgisi gönderilmez.
    """
    from geopy.geocoders import Nominatim

    try:
        sonuc = Nominatim(user_agent="evde-saglik-rota-prototip", timeout=15).geocode(
            sorgu, country_codes="tr", viewbox=[(40.45, 39.05), (41.20, 40.60)], bounded=True)
    except Exception:
        return None  # ağ hatası: önbelleğe yazma, sonra tekrar denenebilir
    satir = {"sorgu": sorgu, "enlem": None, "boylam": None, "kaynak": "bulunamadı", "bulunan_ad": ""}
    if sonuc is not None:
        satir.update(enlem=sonuc.latitude, boylam=sonuc.longitude, kaynak="nominatim", bulunan_ad=sonuc.address)
    onbellek = pd.concat([onbellegi_oku(), pd.DataFrame([satir])], ignore_index=True)
    onbellek.to_csv(ayarlar.KONUM_ONBELLEK_CSV, index=False, encoding="utf-8-sig")
    return None if sonuc is None else (sonuc.latitude, sonuc.longitude)


def hasta_konumu_bul(hasta_kodu: str, mahalle: str):
    """
    Yeni / güncellenen bir hasta için temsili konum: önce önbellek, yoksa canlı arama.
    (enlem, boylam, kaynak) ya da bulunamazsa None döndürür.
    """
    sorgular = hasta_sorgulari(hasta_kodu, mahalle)
    sonuc = _sorgudan_koordinat(sorgular, onbellegi_oku())
    if sonuc is None:
        bilinen = set(onbellegi_oku()["sorgu"])
        for s in sorgular:
            if s not in bilinen and canli_ara(s) is not None:
                break
        sonuc = _sorgudan_koordinat(sorgular, onbellegi_oku())
    if sonuc is None:
        return None
    enlem, boylam, sorgu = sonuc
    de, db = _kaydirma(hasta_kodu)
    return enlem + de, boylam + db, f"Yaklaşık: {sorgu.split(',')[0]}"


def sabit_konum(yer: dict) -> tuple[float, float] | None:
    """MERKEZ veya KAN_TESLIM_YERI için (enlem, boylam)."""
    sonuc = _sorgudan_koordinat(yer["sorgular"], onbellegi_oku())
    return None if sonuc is None else (sonuc[0], sonuc[1])
