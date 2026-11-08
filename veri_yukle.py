"""
Uygulamanın kullandığı veri okuma fonksiyonları.

Veriler veritabanından (veritabani.py) okunur. Excel yalnızca ilk aktarımda
(araclar/veritabani_kur.py) kullanılır: excelden_hastalari_oku().
"""

import pandas as pd

import ayarlar
import veritabani


# ---------------------------------------------------------------------------
# İlk aktarım: Excel
# ---------------------------------------------------------------------------
def excelden_hastalari_oku() -> pd.DataFrame:
    """Haftalık hasta planını Excel'den okur (yalnızca ilk aktarımda kullanılır)."""
    df = pd.read_excel(ayarlar.HASTA_EXCEL, sheet_name="47 Hasta Haftalık Plan")
    df = df.rename(columns={
        "Hasta kodu": "hasta_kodu",
        "Tanı (verilen liste)": "tani",
        "Mahalle / genel konum": "mahalle",
        "Konum tarifi": "konum_tarifi",
    })
    # Gün sütunlarındaki "X" işaretlerini True/False'a çeviriyoruz.
    for gun in ayarlar.GUNLER:
        df[gun] = df[gun].astype(str).str.strip().str.upper().eq("X")

    # Excel'deki eksik/yanlış tanıları düzeltme dosyasından güncelle (orijinal Excel'e dokunmuyoruz).
    duzeltme_dosyasi = ayarlar.VERI_KLASORU / "tani_duzeltmeleri.csv"
    if duzeltme_dosyasi.exists():
        duzeltmeler = pd.read_csv(duzeltme_dosyasi).set_index("hasta_kodu")["tani"]
        df["tani"] = df["hasta_kodu"].map(duzeltmeler).fillna(df["tani"])

    # Kullanıcının bildirdiği mahalle / tarif düzeltmeleri
    konum_dosyasi = ayarlar.VERI_KLASORU / "konum_duzeltmeleri.csv"
    if konum_dosyasi.exists():
        kd = pd.read_csv(konum_dosyasi).set_index("hasta_kodu")
        for sutun in ["mahalle", "konum_tarifi"]:
            df[sutun] = df["hasta_kodu"].map(kd[sutun]).fillna(df[sutun])
    return df


# ---------------------------------------------------------------------------
# Uygulama içi okuma: veritabanı
# ---------------------------------------------------------------------------
def hastalari_yukle(sadece_aktif: bool = True) -> pd.DataFrame:
    """Hastalar + gün sütunları (Pzt ... Paz True/False) + haftalık ziyaret sayısı."""
    df = veritabani.hastalar(sadece_aktif=sadece_aktif)
    # Boş metin hücreleri ekranda "None" yerine "–" olarak görünsün.
    for sutun in ["mahalle", "konum_tarifi"]:
        df[sutun] = df[sutun].fillna("–")
    return df


def gunun_hastalari(df: pd.DataFrame, gun: str) -> pd.DataFrame:
    """Seçilen günde ziyaret edilecek hastaları döndürür."""
    return df[df[gun]].copy()


def islem_surelerini_yukle() -> pd.DataFrame:
    """İşlem sürelerini okur ve planlamada kullanılacak ortalama süreyi ekler."""
    df = veritabani.islem_turleri()
    # Buçuklu süreler yukarı yuvarlanır (12,5 -> 13): planlamada güvenli taraf.
    df["ortalama_dk"] = ((df["min_dk"] + df["max_dk"] + 1) // 2).astype(int)
    return df


def islem_sureleri_sozlugu() -> dict:
    """{'Kan alımı': 25, ...} biçiminde planlama süreleri."""
    df = islem_surelerini_yukle()
    return dict(zip(df["islem"], df["ortalama_dk"]))


VARSAYILAN_ISLEM = "Vital bulgu / sosyal ziyaret"


def gunun_ziyaretleri(gun: str) -> pd.DataFrame:
    """
    Seçilen günün ziyaretlerini rota hesabına hazır hale getirir:
    hasta bilgisi + o gün yapılacak işlemler + ziyaret süresi + kan alımı + konum.
    """
    hastalar = gunun_hastalari(hastalari_yukle(), gun)

    islemler = veritabani.hasta_islemleri(gun)
    if not islemler.empty:
        islemler = (islemler.groupby("hasta_kodu")["islem"]
                    .apply(lambda s: ";".join(s)).rename("islemler").reset_index())
    else:
        islemler = pd.DataFrame(columns=["hasta_kodu", "islemler"])

    df = hastalar.merge(islemler, on="hasta_kodu", how="left")
    df["islemler"] = df["islemler"].fillna(VARSAYILAN_ISLEM)

    sureler = islem_sureleri_sozlugu()
    df["sure_dk"] = df["islemler"].map(lambda s: sum(sureler.get(i, 0) for i in s.split(";")))
    df["kan_alimi"] = df["islemler"].str.contains("Kan alımı", regex=False)
    df["konum_kaynagi"] = df["konum_kaynagi"].fillna("Konum yok")
    return df[
        ["hasta_kodu", "tani", "mahalle", "konum_tarifi", "islemler", "sure_dk",
         "kan_alimi", "enlem", "boylam", "konum_kaynagi"]
    ].reset_index(drop=True)


def konumsuzlari_merkeze_yerlestir(df: pd.DataFrame, merkez: tuple[float, float]) -> pd.DataFrame:
    """
    DENEME AMAÇLI: Konumu olmayan hastaları merkezin ~1-2 km çevresine yerleştirir.
    Böylece iş yükleri (ziyaret süreleri) hesaba katılır. Gerçek planlamada kullanılmamalı.
    """
    import konum

    df = df.copy()
    eksik = df["enlem"].isna()
    for i in df.index[eksik]:
        de, db = konum._kaydirma(df.at[i, "hasta_kodu"])
        df.at[i, "enlem"] = merkez[0] + de * 4
        df.at[i, "boylam"] = merkez[1] + db * 4
        df.at[i, "konum_kaynagi"] = "VARSAYIM: merkez yakını (konum yok)"
    return df
