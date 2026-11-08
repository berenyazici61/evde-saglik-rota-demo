"""Genel bakış: günlük hasta listesi, haftalık dağılım, kurallar. (Yönetici, doktor)"""

import altair as alt
import pandas as pd
import streamlit as st

import ayarlar
import oturum
import veri_yukle

oturum.rol_gerekli("yonetici", "doktor")

st.title("📋 Genel Bakış")

# ---------------------------------------------------------------------------
# Verileri oku
# ---------------------------------------------------------------------------
hastalar = veri_yukle.hastalari_yukle()
islemler = veri_yukle.islem_surelerini_yukle()

# ---------------------------------------------------------------------------
# Sol menü: gün seçimi
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Gün seçimi")
    secilen_gun = st.radio(
        "Hangi günün planını görmek istiyorsunuz?",
        options=ayarlar.GUNLER,
        format_func=lambda g: ayarlar.GUN_TAM_ADLARI[g],
    )

gunun_hastalari = veri_yukle.gunun_hastalari(hastalar, secilen_gun)

# ---------------------------------------------------------------------------
# Özet kutuları
# ---------------------------------------------------------------------------
gun_adi = ayarlar.GUN_TAM_ADLARI[secilen_gun]
st.subheader(f"{gun_adi} özeti")

k1, k2, k3, k4 = st.columns(4)
k1.metric("Toplam hasta", len(hastalar))
k2.metric(f"{gun_adi} ziyareti", len(gunun_hastalari))
k3.metric("Ekip sayısı", ayarlar.EKIP_SAYISI)
k4.metric("Ekip başına ortalama", f"{len(gunun_hastalari) / ayarlar.EKIP_SAYISI:.1f}")

# ---------------------------------------------------------------------------
# Günün hasta listesi
# ---------------------------------------------------------------------------
st.subheader(f"{gun_adi} günü ziyaret edilecek hastalar")
st.dataframe(
    gunun_hastalari[["hasta_kodu", "tani", "haftalik_ziyaret", "mahalle", "konum_tarifi", "konum_kaynagi"]],
    column_config={
        "hasta_kodu": "Hasta kodu",
        "tani": "Tanı",
        "haftalik_ziyaret": "Haftalık ziyaret",
        "mahalle": "Mahalle",
        "konum_tarifi": "Konum tarifi",
        "konum_kaynagi": "Temsili konum",
    },
    hide_index=True,
    width="stretch",
)

# ---------------------------------------------------------------------------
# Haftalık dağılım grafiği
# ---------------------------------------------------------------------------
st.subheader("Haftalık ziyaret dağılımı")
gun_sirasi = [ayarlar.GUN_TAM_ADLARI[g] for g in ayarlar.GUNLER]
gunluk_sayilar = pd.DataFrame(
    {"Gün": gun_sirasi, "Ziyaret sayısı": [int(hastalar[g].sum()) for g in ayarlar.GUNLER]}
)
# Altair grafiği: günler alfabetik değil, Pazartesi'den Pazar'a sıralı görünsün.
grafik = (
    alt.Chart(gunluk_sayilar)
    .mark_bar()
    .encode(
        x=alt.X("Gün", sort=gun_sirasi),
        y="Ziyaret sayısı",
        tooltip=["Gün", "Ziyaret sayısı"],
    )
)
st.altair_chart(grafik, width="stretch")

# ---------------------------------------------------------------------------
# Ayarlar ve işlem süreleri
# ---------------------------------------------------------------------------
sol, sag = st.columns(2)

with sol:
    st.subheader("Rota kuralları")
    st.markdown(
        f"""
- **Merkez:** {ayarlar.MERKEZ['ad']} ({ayarlar.MERKEZ['adres']})
- **Çıkış saati:** {ayarlar.CIKIS_SAATI}
- **Ekip:** {ayarlar.EKIP_SAYISI} araç × {ayarlar.HEMSIRE_PER_EKIP} hemşire
- **Kan teslim yeri:** {ayarlar.KAN_TESLIM_YERI['ad']}
- **Kan teslim saati:** {ayarlar.KAN_TESLIM_SON_SAAT} (en fazla {ayarlar.KAN_TESLIM_ESNEKLIK_DK} dk esneyebilir)
- **Hastanede kan teslimi:** {ayarlar.KAN_TESLIM_SURESI_MIN_DK}–{ayarlar.KAN_TESLIM_SURESI_MAX_DK} dk · her ekip kendi kanını teslim eder
- **Dönüşte merkezde geçen süre:** {ayarlar.MERKEZ_DONUS_SURESI_DK} dk
"""
    )

with sag:
    st.subheader("İşlem süreleri")
    st.dataframe(
        islemler,
        column_config={
            "islem": "İşlem",
            "min_dk": "Min (dk)",
            "max_dk": "Max (dk)",
            "ortalama_dk": "Planlama (dk)",
        },
        hide_index=True,
        width="stretch",
    )
