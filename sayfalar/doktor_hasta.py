"""Doktor hasta takibi: hasta özeti, ziyaret geçmişi, muayene notu ve hemşire talimatı. (Doktor)"""

import datetime as dt

import pandas as pd
import streamlit as st

import ayarlar
import oturum
import veri_yukle
import veritabani

kullanici = oturum.rol_gerekli("doktor")
st.title("🩻 Hasta Takibi")

hastalar = veri_yukle.hastalari_yukle().set_index("hasta_kodu")
hasta = st.selectbox("Hasta", list(hastalar.index),
                     format_func=lambda k: f"{k} · {hastalar.loc[k, 'tani'] or '-'} · {hastalar.loc[k, 'mahalle']}")
h = hastalar.loc[hasta]

# ---------------------------------------------------------------------------
# Özet
# ---------------------------------------------------------------------------
c1, c2, c3 = st.columns(3)
c1.metric("Tanı", h["tani"] or "-")
c2.metric("Haftalık ziyaret", int(h["haftalik_ziyaret"]))
c3.metric("Mahalle", h["mahalle"])
st.caption("Ziyaret günleri: " + ", ".join(ayarlar.GUN_TAM_ADLARI[g] for g in ayarlar.GUNLER if h[g]))

ziyaretler = veritabani.ziyaret_kayitlari(hasta_kodu=hasta)
st.subheader("Son ziyaretler (hemşire kayıtları)")
if ziyaretler.empty:
    st.caption("Bu hasta için henüz ziyaret kaydı yok.")
else:
    st.dataframe(
        ziyaretler.assign(yapilan_islemler=ziyaretler["yapilan_islemler"].str.replace(";", ", ")).head(30),
        column_config={"id": None, "hasta_kodu": None, "tarih": "Tarih", "kaydeden": "Hemşire",
                       "yapilan_islemler": "İşlemler", "tansiyon": "TA", "nabiz": "Nabız", "ates": "Ateş",
                       "seker": "Şeker", "spo2": "SpO₂", "notlar": "Not", "kayit_zamani": None},
        hide_index=True, width="stretch",
    )
    vital = ziyaretler.dropna(subset=["nabiz", "spo2", "seker"], how="all")
    if len(vital) >= 2:
        with st.expander("Vital bulgu grafiği"):
            g = vital.assign(tarih=pd.to_datetime(vital["tarih"])).set_index("tarih")
            st.line_chart(g[["nabiz", "spo2", "seker"]].rename(columns={"nabiz": "Nabız", "spo2": "SpO₂",
                                                                         "seker": "Şeker"}))

# ---------------------------------------------------------------------------
# Not / talimat
# ---------------------------------------------------------------------------
st.subheader("Muayene notu ve hemşire talimatı")
with st.form(f"doktor_notu_{hasta}", clear_on_submit=True):
    tarih = st.date_input("Tarih", value=dt.date.today(), format="DD.MM.YYYY")
    muayene = st.text_area("Muayene notu", height=100)
    talimat = st.text_area("Hemşirelere talimat", height=80,
                           help="Hemşirenin ziyaret kaydı ekranında bu hasta için görünür.")
    kaydet = st.form_submit_button("Kaydet", type="primary")
if kaydet:
    if not muayene.strip() and not talimat.strip():
        st.error("Not veya talimattan en az birini yazın.")
    else:
        veritabani.doktor_notu_ekle({"hasta_kodu": hasta, "kullanici_id": kullanici["id"],
                                     "tarih": tarih.isoformat(), "muayene_notu": muayene.strip() or None,
                                     "hemsire_talimati": talimat.strip() or None})
        veritabani.iz_kaydi(kullanici["id"], "Doktor notu eklendi", f"{hasta} · {tarih.isoformat()}")
        st.success("Kaydedildi.")
        st.rerun()

notlar = veritabani.doktor_notlari(hasta)
if not notlar.empty:
    st.dataframe(notlar, column_config={"id": None, "hasta_kodu": None, "tarih": "Tarih", "doktor": "Doktor",
                                        "muayene_notu": "Muayene notu", "hemsire_talimati": "Talimat",
                                        "kayit_zamani": None},
                 hide_index=True, width="stretch")
