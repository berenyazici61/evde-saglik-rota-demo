"""
Hemşirenin kendi ekibinin günlük rotası: sıralı duraklar, tahmini saatler, ilerleme. (Hemşire)
Telefonda rahat kullanılsın diye tek sütunlu tasarlandı.
"""

import datetime as dt

import streamlit as st
import streamlit.components.v1 as components

import ayarlar
import harita
import konum
import oturum
import rota_kayit
import veri_yukle
import veritabani
from ayarlar import saat

kullanici = oturum.rol_gerekli("hemsire")
st.title("🚐 Bugünkü Rotam")

ekip_no = kullanici.get("ekip_no")
if not ekip_no:
    st.warning("Bir ekibe atanmamışsınız. Lütfen yöneticinizle görüşün.")
    st.stop()

tarih = st.date_input("Tarih", value=dt.date.today(), format="DD.MM.YYYY")
tarih_str = tarih.isoformat()
kayit = rota_kayit.yukle(tarih_str)
if kayit is None:
    st.info(f"{tarih.strftime('%d.%m.%Y')} için henüz onaylanmış rota yok. Yönetici rotayı kaydettiğinde burada görünecek.")
    st.stop()

bilgi, sonuc = kayit
if ekip_no > len(sonuc.rotalar):
    st.warning(f"Kayıtlı planda Ekip {ekip_no} yok.")
    st.stop()
rota = sonuc.rotalar[ekip_no - 1]

if rota.hasta_sayisi == 0:
    st.info(f"Ekip {ekip_no} için bu tarihte ziyaret yok.")
    st.stop()

# Ziyaret kaydı girilen hastalar = tamamlandı
tamamlanan = set(veritabani.ziyaret_kayitlari(tarih=tarih_str)["hasta_kodu"])
hastalar = veri_yukle.hastalari_yukle(sadece_aktif=False).set_index("hasta_kodu")
notlar = veritabani.doktor_notlari()
talimatlar = (notlar.dropna(subset=["hemsire_talimati"]).drop_duplicates("hasta_kodu")
              .set_index("hasta_kodu")["hemsire_talimati"])

hasta_duraklari = [d for d in rota.duraklar if d.tur == "Hasta"]
biten = sum(d.ad in tamamlanan for d in hasta_duraklari)

c1, c2, c3 = st.columns(3)
c1.metric("Ziyaret", f"{biten} / {len(hasta_duraklari)}")
c2.metric("Yol", f"{rota.km:.0f} km")
c3.metric("Tahmini bitiş", saat(rota.bitis_dk))
st.progress(biten / len(hasta_duraklari), text=f"Ekip {ekip_no} · {biten} ziyaret tamamlandı")
if rota.kan_teslim_dk:
    st.info(f"🩸 Kan teslimi: 7M Hastanesi, teslimin bitişi en geç **{ayarlar.KAN_TESLIM_SON_SAAT}** "
            f"(planlanan bitiş {saat(rota.kan_teslim_dk)})")

st.subheader("Duraklar")
sira = 0
for i, d in enumerate(rota.duraklar):
    if d.tur == "Merkez":
        if i == 0:
            st.markdown(f"🏠 **{saat(d.varis_dk)}** · Merkezden çıkış")
        else:
            st.markdown(f"🏠 **{saat(d.varis_dk)}** · Merkeze dönüş, "
                        f"{ayarlar.MERKEZ_DONUS_SURESI_DK} dk ekipman teslimi · iş biter **{saat(d.ayrilis_dk)}**")
    elif d.tur == "7M Hastanesi":
        st.markdown(f"🏥 **{saat(d.varis_dk)}–{saat(d.ayrilis_dk)}** · 7M Hastanesi · "
                    f"kan teslimi ({d.tup_sayisi} hasta)")
    else:
        sira += 1
        h = hastalar.loc[d.ad] if d.ad in hastalar.index else None
        bitti = d.ad in tamamlanan
        with st.container(border=True):
            st.markdown(f"{'✅' if bitti else '⬜'} **{sira}. {d.ad}** · {saat(d.varis_dk)}–{saat(d.ayrilis_dk)}"
                        + (" · 🩸 kan alımı" if d.kan_alimi else ""))
            if h is not None:
                st.caption(f"📍 {h['mahalle']} · {h['konum_tarifi']}")
            st.write("İşlemler: " + d.islemler.replace(";", ", "))
            if d.ad in talimatlar.index:
                st.info(f"Doktor talimatı: {talimatlar[d.ad]}")

with st.expander("Haritada göster"):
    merkez = konum.sabit_konum(ayarlar.MERKEZ)
    lab = konum.sabit_konum(ayarlar.KAN_TESLIM_YERI)
    components.html(harita.rota_haritasi(sonuc, merkez, lab, sadece_ekip=ekip_no - 1).get_root().render(),
                    height=420)
    st.caption("Noktalar gizlilik gereği temsilidir (gerçek evin ~200 m çevresi). Evi tarife göre bulun.")

st.caption("Ziyaret bittiğinde **Ziyaret Kaydı** sayfasından kaydedin; burada ✅ olarak görünür. "
           f"Rota kaydı: {bilgi['olusturan']} · {bilgi['olusturma']}")
