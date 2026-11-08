"""Raporlar: planlanan / gerçekleşen ziyaretler, km, ekip iş yükü, mevcut sisteme göre kazanç. (Yönetici)"""

import datetime as dt

import altair as alt
import pandas as pd
import streamlit as st

import ayarlar
import harita
import oturum
import raporlar
import veritabani
from ayarlar import saat

kullanici = oturum.rol_gerekli("yonetici")
st.title("📊 Raporlar")

bugun = dt.date.today()
aralik = st.date_input("Tarih aralığı (varsayılan: son 7 gün + gelecek 7 gün)",
                       value=(bugun - dt.timedelta(days=7), bugun + dt.timedelta(days=7)), format="DD.MM.YYYY")
if not isinstance(aralik, tuple) or len(aralik) != 2:
    st.info("Bitiş tarihini de seçin.")
    st.stop()
bas, bit = aralik
v = raporlar.rapor_verisi(bas.isoformat(), bit.isoformat())
gunluk, plan, ekip = v["gunluk"], v["plan"], v["ekip"]

if gunluk.empty:
    st.info("Bu aralıkta kayıtlı rota yok. Rota Planlama sayfasından ya da otomatik betikle rota oluşturun.")
    st.stop()


def tr_tarih(t: str) -> str:
    d = dt.date.fromisoformat(t)
    return f"{d.strftime('%d.%m')} {ayarlar.GUNLER[d.weekday()]}"  # Pzt, Sal, ... (ilk 3 harf Paz/Pzt karışır)


# ---------------------------------------------------------------------------
# Özet
# ---------------------------------------------------------------------------
planlanan = len(plan)
yapilan = int((plan["durum"] == "Yapıldı").sum())
kacirilan = int((plan["durum"] == "Kaçırıldı").sum())
gecmis = yapilan + kacirilan
c1, c2, c3, c4 = st.columns(4)
c1.metric("Planlanan ziyaret", planlanan, help=f"{len(gunluk)} günlük kayıtlı rota")
c2.metric("Yapılan", yapilan, help="Ziyaret kaydı girilen planlı ziyaretler")
c3.metric("Kaçırılan", kacirilan, help="Geçmiş günlerde planlı olup kaydı girilmeyen ziyaretler")
c4.metric("Tamamlanma (geçmiş günler)", f"%{100 * yapilan / gecmis:.0f}" if gecmis else "–")

karsi = gunluk.dropna(subset=["mevcut_en_gec_bitis_dk"])
d1, d2, d3 = st.columns(3)
d1.metric("Toplam yol (plan)", f"{gunluk['toplam_km'].sum():.0f} km")
if not karsi.empty:
    d2.metric("Erken bitiş kazancı", f"{int(karsi['kazanc_dk'].sum())} dk",
              help="Her gün en geç biten ekibin, mevcut bölge sistemine göre kaç dakika erken bittiği (toplam)")
    d3.metric("Yol farkı", f"{karsi['km_farki'].sum():+.0f} km", delta_color="inverse",
              help="Optimize rota − mevcut bölge sistemi (eksi: daha az yol)")
st.caption("Kazanç ve yol farkı, rota kaydedilirken aynı gün için hesaplanan mevcut bölge sistemine göredir.")

# ---------------------------------------------------------------------------
# Günlük grafik ve tablo
# ---------------------------------------------------------------------------
st.subheader("Günlük ziyaretler")
gun_sira = [tr_tarih(t) for t in gunluk["tarih"]]
uzun = (plan.assign(gun=plan["tarih"].map(tr_tarih))
        .groupby(["gun", "durum"]).size().rename("ziyaret").reset_index())
renk = alt.Scale(domain=["Yapıldı", "Kaçırıldı", "Bekliyor"], range=["#16a34a", "#dc2626", "#94a3b8"])
st.altair_chart(
    alt.Chart(uzun).mark_bar().encode(
        x=alt.X("gun:N", sort=gun_sira, title=None),
        y=alt.Y("ziyaret:Q", title="Ziyaret"),
        color=alt.Color("durum:N", scale=renk, title="Durum"),
        tooltip=["gun", "durum", "ziyaret"]),
    width="stretch")

tablo = pd.DataFrame({
    "Tarih": gunluk["tarih"].map(tr_tarih),
    "Planlanan": gunluk["planlanan"],
    "Yapılan": gunluk["Yapıldı"].astype(int),
    "Kaçırılan": gunluk["Kaçırıldı"].astype(int),
    "En geç bitiş": gunluk["en_gec_bitis_dk"].map(lambda x: saat(x) if pd.notna(x) else "–"),
    "Mevcut sistem bitiş": gunluk["mevcut_en_gec_bitis_dk"].map(lambda x: saat(x) if pd.notna(x) else "–"),
    "Kazanç (dk)": gunluk["kazanc_dk"].map(lambda x: f"{int(x)}" if pd.notna(x) else "–"),
    "Yol (km)": gunluk["toplam_km"].round(0),
    "Kan gecikmesi (dk)": gunluk["kan_gecikmesi_dk"],
    "Rota": gunluk["kaynak"].map({"elle": "Yönetici", "otomatik": "Otomatik"}),
})
st.dataframe(tablo, hide_index=True, width="stretch")

# ---------------------------------------------------------------------------
# Ekip iş yükü
# ---------------------------------------------------------------------------
st.subheader("Ekip iş yükü")
if not ekip.empty:
    ekip_g = ekip.assign(ekip=ekip["ekip_no"].map(lambda e: f"Ekip {int(e)}"))
    renkler = alt.Scale(domain=[f"Ekip {i}" for i in range(1, ayarlar.EKIP_SAYISI + 1)], range=harita.RENKLER)
    s1, s2 = st.columns(2)
    for kol, alan, baslik in ((s1, "planlanan", "Planlanan ziyaret"), (s2, "toplam_km", "Toplam yol (km)")):
        kol.altair_chart(
            alt.Chart(ekip_g).mark_bar().encode(
                x=alt.X("ekip:N", title=None), y=alt.Y(f"{alan}:Q", title=baslik),
                color=alt.Color("ekip:N", scale=renkler, legend=None), tooltip=["ekip", alan]),
            width="stretch")
    st.dataframe(pd.DataFrame({
        "Ekip": ekip_g["ekip"],
        "Gün": ekip_g["gun"].astype(int),
        "Planlanan": ekip_g["planlanan"].astype(int),
        "Yapılan": ekip_g["yapilan"].astype(int),
        "Kan alımı": ekip_g["kan_alimi"].astype(int),
        "Toplam km": ekip_g["toplam_km"].round(0),
        "Ort. bitiş": ekip_g["ort_bitis_dk"].map(lambda x: saat(x) if x else "–"),
        "En geç bitiş": ekip_g["en_gec_bitis_dk"].map(lambda x: saat(x) if x else "–"),
    }), hide_index=True, width="stretch")
    st.caption("Ekip numaraları her gün optimizasyonun dağıtımına göredir; sabit bölge anlamına gelmez.")

# ---------------------------------------------------------------------------
# Kaçırılan ve plan dışı ziyaretler
# ---------------------------------------------------------------------------
k1, k2 = st.columns(2)
with k1:
    st.subheader("Kaçırılan ziyaretler")
    kac = plan[plan["durum"] == "Kaçırıldı"]
    if kac.empty:
        st.caption("Yok.")
    else:
        st.dataframe(pd.DataFrame({"Tarih": kac["tarih"].map(tr_tarih), "Ekip": kac["ekip_no"],
                                   "Hasta": kac["hasta_kodu"]}), hide_index=True, width="stretch")
with k2:
    st.subheader("Plan dışı ziyaretler")
    pd_ = v["plan_disi"]
    if pd_.empty:
        st.caption("Yok.")
    else:
        st.dataframe(pd.DataFrame({"Tarih": pd_["tarih"].map(tr_tarih), "Hasta": pd_["hasta_kodu"],
                                   "Kaydeden": pd_["kaydeden"]}), hide_index=True, width="stretch")
    st.caption("Kayıtlı rotada olmayan ama ziyaret kaydı girilen hastalar (ör. acil ziyaret).")

# ---------------------------------------------------------------------------
# İndir
# ---------------------------------------------------------------------------
st.divider()
ad = f"{bas.isoformat()}_{bit.isoformat()}"
i1, i2 = st.columns(2)
if i1.download_button("Günlük özeti indir (CSV)", tablo.to_csv(index=False).encode("utf-8-sig"),
                      file_name=f"rapor_gunluk_{ad}.csv", mime="text/csv"):
    veritabani.iz_kaydi(kullanici["id"], "Rapor indirildi", f"günlük özet {ad}")
detay = plan.assign(tarih=plan["tarih"], kan_alimi=plan["kan_alimi"].astype(bool),
                    planlanan_varis=plan["varis_dk"].map(saat))[
    ["tarih", "ekip_no", "sira", "hasta_kodu", "planlanan_varis", "kan_alimi", "durum"]]
if i2.download_button("Ziyaret ayrıntısını indir (CSV)", detay.to_csv(index=False).encode("utf-8-sig"),
                      file_name=f"rapor_ziyaretler_{ad}.csv", mime="text/csv"):
    veritabani.iz_kaydi(kullanici["id"], "Rapor indirildi", f"ziyaret ayrıntısı {ad}")
