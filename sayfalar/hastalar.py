"""Hasta listesi, yeni hasta ekleme ve düzenleme. (Yönetici)"""

import pandas as pd
import streamlit as st

import ayarlar
import konum
import oturum
import veri_yukle
import veritabani

kullanici = oturum.rol_gerekli("yonetici")
st.title("🧑‍⚕️ Hastalar")

hastalar = veri_yukle.hastalari_yukle(sadece_aktif=False)

# ---------------------------------------------------------------------------
# Liste
# ---------------------------------------------------------------------------
c1, c2 = st.columns([3, 1])
arama = c1.text_input("Ara (hasta kodu, tanı veya mahalle)", placeholder="örn. H012, Alzheimer, Pelitli")
pasifleri_goster = c2.toggle("Pasif hastaları da göster", value=False)

liste = hastalar.copy()
if not pasifleri_goster:
    liste = liste[liste["aktif"]]
if arama:
    a = arama.strip().lower()
    liste = liste[liste[["hasta_kodu", "tani", "mahalle"]].astype(str)
                  .apply(lambda s: s.str.lower().str.contains(a, regex=False)).any(axis=1)]
liste["gunler"] = liste.apply(lambda r: ", ".join(g for g in ayarlar.GUNLER if r[g]), axis=1)

st.caption(f"{len(liste)} hasta gösteriliyor · toplam aktif hasta: {int(hastalar['aktif'].sum())}")
st.dataframe(
    liste[["hasta_kodu", "tani", "mahalle", "konum_tarifi", "gunler", "haftalik_ziyaret", "konum_kaynagi", "aktif"]],
    column_config={
        "hasta_kodu": "Kod", "tani": "Tanı", "mahalle": "Mahalle", "konum_tarifi": "Konum tarifi",
        "gunler": "Ziyaret günleri", "haftalik_ziyaret": st.column_config.NumberColumn("Haftalık", format="%d"),
        "konum_kaynagi": "Temsili konum", "aktif": "Aktif",
    },
    hide_index=True, width="stretch", height=320,
)

# ---------------------------------------------------------------------------
# Ekle / düzenle
# ---------------------------------------------------------------------------
st.subheader("Hasta ekle / düzenle")
YENI = "➕ Yeni hasta"
secim = st.selectbox("Hasta seçin", [YENI] + list(hastalar["hasta_kodu"]))

if secim == YENI:
    mevcut = {"hasta_kodu": veritabani.yeni_hasta_kodu(), "tani": "", "mahalle": "", "konum_tarifi": "",
              "notlar": "", "aktif": True, "enlem": None, "boylam": None}
    mevcut_gunler = []
else:
    satir = hastalar[hastalar["hasta_kodu"] == secim].iloc[0]
    mevcut = {k: (None if pd.isna(satir[k]) else satir[k])
              for k in ["hasta_kodu", "tani", "mahalle", "konum_tarifi", "notlar", "aktif", "enlem", "boylam"]}
    mevcut_gunler = [g for g in ayarlar.GUNLER if satir[g]]

with st.form(f"hasta_formu_{mevcut['hasta_kodu']}"):
    a, b = st.columns(2)
    a.text_input("Hasta kodu", value=mevcut["hasta_kodu"], disabled=True)
    tani = b.text_input("Tanı", value=mevcut["tani"] or "")
    mahalle = a.text_input("Mahalle / genel konum", value="" if mevcut["mahalle"] in (None, "–") else mevcut["mahalle"],
                           help="Temsili konum bu bilgiden bulunur. Örn. Pelitli, Çukurçayır, Akçaabat")
    tarif = b.text_input("Konum tarifi", value="" if mevcut["konum_tarifi"] in (None, "–") else mevcut["konum_tarifi"],
                         help="Ekibin evi bulması için tarif. Kesin adres yazmayın.")
    gunler = st.multiselect("Ziyaret günleri", ayarlar.GUNLER, default=mevcut_gunler,
                            format_func=lambda g: ayarlar.GUN_TAM_ADLARI[g])
    notlar = st.text_area("Notlar", value=mevcut["notlar"] or "", height=80)
    aktif = st.checkbox("Aktif (rotalara dahil)", value=bool(mevcut["aktif"]))
    with st.expander("Temsili konumu elle gir (isteğe bağlı)"):
        elle = st.checkbox("Koordinatı elle gireceğim")
        e1, e2 = st.columns(2)
        enlem = e1.number_input("Enlem", value=mevcut["enlem"], format="%.5f", min_value=40.4, max_value=41.3)
        boylam = e2.number_input("Boylam", value=mevcut["boylam"], format="%.5f", min_value=39.0, max_value=40.7)
    kaydet = st.form_submit_button("Kaydet", type="primary")

if kaydet:
    kod = mevcut["hasta_kodu"]
    eski_mahalle = "" if mevcut["mahalle"] in (None, "–") else mevcut["mahalle"]
    yeni = {"hasta_kodu": kod, "tani": tani.strip() or None, "mahalle": mahalle.strip() or None,
            "konum_tarifi": tarif.strip() or None, "notlar": notlar.strip() or None, "aktif": aktif,
            "enlem": mevcut["enlem"], "boylam": mevcut["boylam"],
            "konum_kaynagi": None if secim == YENI else satir["konum_kaynagi"]}

    if elle and enlem is not None and boylam is not None:
        yeni.update(enlem=enlem, boylam=boylam, konum_kaynagi="Elle girildi")
    elif secim == YENI or mahalle.strip() != eski_mahalle or mevcut["enlem"] is None:
        with st.spinner("Temsili konum aranıyor..."):
            bulunan = konum.hasta_konumu_bul(kod, mahalle.strip())
        if bulunan:
            yeni.update(enlem=bulunan[0], boylam=bulunan[1], konum_kaynagi=bulunan[2])
        else:
            yeni.update(enlem=None, boylam=None, konum_kaynagi="Konum yok")
            st.warning("Bu mahalle haritada bulunamadı. Koordinatı elle girebilirsiniz.")

    veritabani.hasta_kaydet(yeni, gunler)
    veritabani.iz_kaydi(kullanici["id"], "Hasta eklendi" if secim == YENI else "Hasta güncellendi", kod)
    st.success(f"{kod} kaydedildi.")
    st.rerun()

# Planlanan işlemler (salt okunur)
if secim != YENI:
    with st.expander(f"{secim} için planlanan haftalık işlemler"):
        hi = veritabani.hasta_islemleri()
        hi = hi[hi["hasta_kodu"] == secim]
        if hi.empty:
            st.write("Kayıt yok.")
        else:
            if hi["sentetik"].any():
                st.caption("⚠️ Bu işlemler SENTETİK (deneme) veridir.")
            tablo = hi.groupby("gun", sort=False)["islem"].apply(", ".join).reindex(ayarlar.GUNLER).dropna()
            st.table(tablo.rename(index=ayarlar.GUN_TAM_ADLARI).rename("İşlemler"))
