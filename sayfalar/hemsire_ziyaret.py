"""
Hemşire ziyaret kaydı: günün hastaları, doktor talimatları, vital bulgu girişi. (Hemşire)
Telefonda rahat kullanılsın diye tek sütunlu tasarlandı.
"""

import datetime as dt
import re

import pandas as pd
import streamlit as st

import ayarlar
import oturum
import rota_kayit
import veri_yukle
import veritabani

kullanici = oturum.rol_gerekli("hemsire")
st.title("🩺 Ziyaret Kaydı")

tarih = st.date_input("Tarih", value=dt.date.today(), format="DD.MM.YYYY")
gun = ayarlar.GUNLER[tarih.weekday()]
tarih_str = tarih.isoformat()

ziyaretler = veri_yukle.gunun_ziyaretleri(gun)

# Kayıtlı rota varsa: ekibimin hastaları rota sırasıyla en üstte
kayit = rota_kayit.yukle(tarih_str)
ekip_no = kullanici.get("ekip_no")
ekip_sirasi = []
if kayit and ekip_no and ekip_no <= len(kayit[1].rotalar):
    ekip_sirasi = [d.ad for d in kayit[1].rotalar[ekip_no - 1].duraklar if d.tur == "Hasta"]
    st.caption(f"Ekip {ekip_no} rotasında {len(ekip_sirasi)} hasta var (rota sırasıyla listelenir). "
               f"Günün toplam ziyareti: {len(ziyaretler)}.")
else:
    st.caption(f"{ayarlar.GUN_TAM_ADLARI[gun]} günü planlanan ziyaret: {len(ziyaretler)} · "
               "Bu tarih için kayıtlı rota yok, günün tüm hastaları listeleniyor.")

# Son doktor talimatı (hasta başına en yeni)
notlar = veritabani.doktor_notlari()
talimatlar = (notlar.dropna(subset=["hemsire_talimati"])
              .loc[lambda d: d["hemsire_talimati"].str.strip() != ""]
              .drop_duplicates("hasta_kodu").set_index("hasta_kodu")["hemsire_talimati"])
bugun_kaydedilen = set(veritabani.ziyaret_kayitlari(tarih=tarih_str)["hasta_kodu"])

liste = ziyaretler.assign(
    talimat=ziyaretler["hasta_kodu"].map(lambda k: talimatlar.get(k, "")),
    durum=ziyaretler["hasta_kodu"].map(lambda k: "✅" if k in bugun_kaydedilen else ""),
    islemler=ziyaretler["islemler"].str.replace(";", ", "),
)
with st.expander("Günün hasta listesi", expanded=False):
    st.dataframe(liste[["durum", "hasta_kodu", "mahalle", "islemler", "talimat"]],
                 column_config={"durum": "Kayıt", "hasta_kodu": "Hasta", "mahalle": "Mahalle",
                                "islemler": "Planlanan işlemler", "talimat": "Doktor talimatı"},
                 hide_index=True, width="stretch")

# ---------------------------------------------------------------------------
# Kayıt formu
# ---------------------------------------------------------------------------
st.subheader("Yeni ziyaret kaydı")
tum_hastalar = veri_yukle.hastalari_yukle()
planli = list(ziyaretler["hasta_kodu"])
gunun_digerleri = [k for k in planli if k not in ekip_sirasi]
digerleri = [k for k in tum_hastalar["hasta_kodu"] if k not in planli]
mahalleler = tum_hastalar.set_index("hasta_kodu")["mahalle"]


def hasta_etiketi(k: str) -> str:
    if k in ekip_sirasi:
        on = f"{ekip_sirasi.index(k) + 1}. "
    elif k in planli:
        on = "(başka ekip) " if ekip_sirasi else ""
    else:
        on = "(bugün planlı değil) "
    return f"{on}{k} · {mahalleler.get(k, '')}" + (" ✅" if k in bugun_kaydedilen else "")


# İlk kaydı girilmemiş hasta seçili gelsin
secenekler = ekip_sirasi + gunun_digerleri + digerleri
ilk = next((i for i, k in enumerate(secenekler) if k not in bugun_kaydedilen), 0)
hasta = st.selectbox("Hasta", secenekler, index=ilk, format_func=hasta_etiketi)

plan = ziyaretler.set_index("hasta_kodu")["islemler"].get(hasta, veri_yukle.VARSAYILAN_ISLEM).split(";")
if hasta in talimatlar.index:
    st.info(f"**Doktor talimatı:** {talimatlar[hasta]}")

tum_islemler = list(veritabani.islem_turleri()["islem"])
with st.form(f"ziyaret_{hasta}_{tarih_str}", clear_on_submit=True):
    yapilan = st.multiselect("Yapılan işlemler", tum_islemler, default=[i for i in plan if i in tum_islemler])
    a, b = st.columns(2)
    tansiyon = a.text_input("Tansiyon (büyük/küçük)", placeholder="120/80")
    nabiz = b.number_input("Nabız (/dk)", min_value=20, max_value=250, value=None, step=1)
    ates = a.number_input("Ateş (°C)", min_value=30.0, max_value=45.0, value=None, step=0.1, format="%.1f")
    seker = b.number_input("Kan şekeri (mg/dL)", min_value=20, max_value=800, value=None, step=1)
    spo2 = a.number_input("SpO₂ (%)", min_value=50, max_value=100, value=None, step=1)
    not_ = st.text_area("Notlar", height=90)
    kaydet = st.form_submit_button("Kaydet", type="primary", width="stretch")

if kaydet:
    if tansiyon and not re.fullmatch(r"\s*\d{2,3}\s*/\s*\d{2,3}\s*", tansiyon):
        st.error("Tansiyonu 120/80 biçiminde yazın.")
    elif not yapilan:
        st.error("En az bir yapılan işlem seçin.")
    else:
        veritabani.ziyaret_kaydi_ekle({
            "hasta_kodu": hasta, "tarih": tarih_str, "kullanici_id": kullanici["id"],
            "yapilan_islemler": ";".join(yapilan), "tansiyon": tansiyon.replace(" ", "") or None,
            "nabiz": nabiz, "ates": ates, "seker": seker, "spo2": spo2, "notlar": not_.strip() or None,
        })
        veritabani.iz_kaydi(kullanici["id"], "Ziyaret kaydı eklendi", f"{hasta} · {tarih_str}")
        st.success(f"{hasta} için ziyaret kaydedildi.")
        st.rerun()

# ---------------------------------------------------------------------------
# Bugün girdiğim kayıtlar
# ---------------------------------------------------------------------------
st.subheader("Bu tarihte girdiğim kayıtlar")
benim = veritabani.ziyaret_kayitlari(tarih=tarih_str, kullanici_id=kullanici["id"])
if benim.empty:
    st.caption("Henüz kayıt yok.")
else:
    st.dataframe(
        benim.assign(yapilan_islemler=benim["yapilan_islemler"].str.replace(";", ", ")),
        column_config={"id": None, "tarih": None, "kaydeden": None, "hasta_kodu": "Hasta",
                       "yapilan_islemler": "İşlemler", "tansiyon": "TA", "nabiz": "Nabız", "ates": "Ateş",
                       "seker": "Şeker", "spo2": "SpO₂", "notlar": "Not", "kayit_zamani": "Saat"},
        hide_index=True, width="stretch",
    )
