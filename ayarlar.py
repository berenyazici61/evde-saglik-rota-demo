"""
Uygulamanın genel ayarları.

Bu dosyadaki değerleri değiştirerek rota kurallarını güncelleyebilirsiniz.
İleride bu ayarlar yönetici ekranından da değiştirilebilecek.
"""

import os
import time
from pathlib import Path

# Saat dilimi: bulut sunucuları UTC çalışır; "bugün" Türkiye saatine göre olsun (Windows'ta gerek yok).
if hasattr(time, "tzset"):
    os.environ.setdefault("TZ", "Europe/Istanbul")
    time.tzset()

# ---------------------------------------------------------------------------
# Dosya yolları
# ---------------------------------------------------------------------------
PROJE_KLASORU = Path(__file__).parent

# DEMO MODU: proje klasöründe "DEMO_MODU" dosyası varsa (ya da EVDE_SAGLIK_DEMO=1 ise)
# uygulama gerçek veri yerine veri_demo/ klasöründeki UYDURMA verilerle çalışır.
DEMO = (PROJE_KLASORU / "DEMO_MODU").exists() or os.environ.get("EVDE_SAGLIK_DEMO") == "1"
DEMO_PAROLASI = "demo1234"  # demo hesaplarının herkese açık parolası (yalnızca uydurma veride!)

VERI_KLASORU = PROJE_KLASORU / ("veri_demo" if DEMO else "veri")
HASTA_EXCEL = VERI_KLASORU / "hasta_plani.xlsx"
ISLEM_SURELERI_CSV = VERI_KLASORU / "islem_sureleri.csv"
# SENTETİK: tanıya göre rastgele üretilmiş işlemler (gerçek rapor gelince değişecek)
ORNEK_ISLEMLER_CSV = VERI_KLASORU / "ornek_haftalik_islemler.csv"
# Adres sorgusu -> koordinat. Elle düzeltilebilir (kaynak sütununa "elle" yazın).
KONUM_ONBELLEK_CSV = VERI_KLASORU / "konum_onbellek.csv"
# Uygulamanın asıl veritabanı (SQLite, tek dosya). Hasta verisi içerir: paylaşmayın!
VERITABANI = VERI_KLASORU / "evde_saglik.db"
# SADECE DENEME: ilk kurulumda oluşturulan kullanıcılar ve geçici parolaları
ORNEK_KULLANICILAR_CSV = VERI_KLASORU / "ornek_kullanicilar.csv"
# Veritabanı yedekleri (hasta verisi içerir: paylaşmayın). En yeni YEDEK_SAKLAMA_SAYISI yedek tutulur.
YEDEK_KLASORU = VERI_KLASORU / "yedekler"
YEDEK_SAKLAMA_SAYISI = 30

ROL_ADLARI = {"yonetici": "Yönetici", "doktor": "Doktor", "hemsire": "Hemşire"}

# ---------------------------------------------------------------------------
# Önemli konumlar
# "sorgular": koordinat aramasında sırayla denenecek adresler.
# Koordinatlar yaklaşıktır; kesin nokta haritada işaretlenince güncellenecek.
# ---------------------------------------------------------------------------
MERKEZ = {
    "ad": "ARSEV Evde Sağlık Hizmetleri",
    "adres": "Çukurçayır, Ortahisar/Trabzon",
    "sorgular": ["Çukurçayır, Ortahisar, Trabzon, Türkiye"],
}

KAN_TESLIM_YERI = {
    "ad": "7M Hastanesi (anlaşmalı)",
    "adres": "Kavaklı, Samsun Caddesi No: 5, 61300 Akçaabat/Trabzon",
    "sorgular": [
        "Samsun Caddesi, Akçaabat, Trabzon, Türkiye",
        "Akçaabat, Trabzon, Türkiye",
    ],
}

# ---------------------------------------------------------------------------
# Yol süresi tahmini (gerçek yol ağı verisi gelene kadar)
# yol mesafesi = kuş uçuşu × YOL_KATSAYISI
# süre: ilk SEHIR_ICI_KM şehir içi hızla, kalanı ana yol (sahil yolu) hızıyla
#   örn. Çukurçayır -> Of ≈ 60 dk, Çukurçayır -> Akçaabat ≈ 20 dk
# ---------------------------------------------------------------------------
# Hızlar trafik kurallarına uygun ORTALAMA değerlerdir (yasal sınırın altında;
# ışık, kavşak, yokuş ve yavaşlamalar dahil). Yerleşim yeri içi sınır 50 km/sa,
# Karadeniz sahil yolu bölünmüş yol olduğu için sınırı daha yüksektir.
# Kalibrasyon: ekiplerin ölçümü Of -> 7M ≈ 45 dk. Bu ayarlarla model 50 dk veriyor (5 dk trafik payı).
YOL_KATSAYISI_YAKIN = 1.3   # kuş uçuşunun ilk YAKIN_KM'si: yokuşlu/virajlı şehir içi yollar
YAKIN_KM = 4
YOL_KATSAYISI_UZAK = 1.1    # sonrası: sahil yolu kıyıya paralel, kuş uçuşuna yakın
SEHIR_ICI_KM = 5            # her yolculuğun ilk 5 yol-km'si şehir içi kabul edilir
SEHIR_ICI_HIZ_KMSA = 30     # şehir içi ortalama (sınır 50)
ANA_YOL_HIZ_KMSA = 85       # bölünmüş sahil yolu ortalaması (yasal sınırın altında)

# ---------------------------------------------------------------------------
# Ekipler
# ---------------------------------------------------------------------------
EKIP_SAYISI = 3            # günde çıkan araç / ekip sayısı
HEMSIRE_PER_EKIP = 3       # 3 hemşire aynı eve birlikte giriyor
TOPLAM_HEMSIRE = 9
TOPLAM_DOKTOR = 2          # doktorlar ayda 1 rutin kontrol + acil durumlar

# ---------------------------------------------------------------------------
# Zaman kuralları
# ---------------------------------------------------------------------------
CIKIS_SAATI = "09:00"               # toplantı bitince merkezden çıkış
MERKEZ_DONUS_SURESI_DK = 30         # dönüşte ekipman teslimi

# Kan teslimi
KAN_TESLIM_SON_SAAT = "12:00"       # teyit edildi: teslimin BİTMESİ gereken hedef saat
KAN_TESLIM_ESNEKLIK_DK = 15         # 10-15 dk esneyebilir -> teslim en geç 12:15'te bitmeli (kesin sınır)
KAN_GECIKME_CEZASI = 10             # 12:00'yi geçen her dakika amaçta 10 dk sayılır (kullanıcı onayladı)
KAN_TESLIM_SURESI_MIN_DK = 15       # hastaneye vardıktan sonra 15-20 dk
KAN_TESLIM_SURESI_MAX_DK = 20
KAN_TESLIM_SURESI_DK = (KAN_TESLIM_SURESI_MIN_DK + KAN_TESLIM_SURESI_MAX_DK + 1) // 2  # = 18
# Her ekip kendi aldığı kanı teslim eder. Kan alım günleri değiştirilemez.

# Amaç fonksiyonu ağırlıkları (ikisi eşit önemde)
AGIRLIK_EN_GEC_BITIS = 1            # en geç biten ekibin bitiş süresi (dk)
AGIRLIK_TOPLAM_YOL = 1              # tüm ekiplerin toplam yol süresi (dk)
# Öğle arası ve sabit bir bitiş saati yok.

# --- Gün içi dinamik rota revizyonu (acil hasta, ziyaret uzaması, iptal) --- VARSAYIM, teyit edilecek
ACIL_HEDEF_DK = 30                 # acil hastaya olaydan sonra en geç bu sürede ulaşılması hedeflenir (aşılırsa uyarı)
ACIL_BEKLEME_AGIRLIGI = 20          # acil hastanın olaydan varışa kadar beklediği her dakika amaçta 20 dk sayılır
DEGISIKLIK_CEZASI_DK = 15           # bir hastanın sabah planındaki ekibinden başka ekibe geçmesi amaçta 15 dk sayılır


def dakika(saat: str) -> int:
    """'09:00' -> 540 (gece yarısından itibaren dakika)."""
    s, d = saat.split(":")
    return int(s) * 60 + int(d)


def saat(dk: int) -> str:
    """540 -> '09:00'."""
    dk = int(round(dk))
    return f"{dk // 60:02d}:{dk % 60:02d}"

# ---------------------------------------------------------------------------
# Gün adları (Excel'deki sütun adlarıyla aynı)
# ---------------------------------------------------------------------------
GUNLER = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cts", "Paz"]
GUN_TAM_ADLARI = {
    "Pzt": "Pazartesi",
    "Sal": "Salı",
    "Çar": "Çarşamba",
    "Per": "Perşembe",
    "Cum": "Cuma",
    "Cts": "Cumartesi",
    "Paz": "Pazar",
}
