"""
Rota planlama (Yönetici):
  1. Tarih seçilir; o günün kayıtlı rotası varsa gösterilir.
  2. "Rotaları oluştur" ile optimize rota hesaplanır ve mevcut bölge sistemiyle karşılaştırılır.
  3. "Rotayı kaydet" ile plan veritabanına yazılır; hemşireler kendi ekip rotalarını görür.
"""

import datetime as dt

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import ayarlar
import harita
import optimizasyon
import oturum
import planlama
import rota_kayit
import veritabani
from ayarlar import saat

kullanici = oturum.rol_gerekli("yonetici")

st.title("🗺️ Rota Planlama")
st.warning(
    "**Deneme verisi.** İşlemler tanıya göre rastgele üretildi (sentetik). Hastalar, gizlilik gereği tarif "
    "edilen yerin ~200 m çevresinde temsili bir noktaya yerleştirildi. Yol süreleri kuş uçuşu mesafeden "
    "tahmin ediliyor (Of→7M ölçümüyle kalibre)."
)


def teslim_yazisi(dk: int) -> str:
    """12:05 -> '12:05 (+5 dk)' ; zamanında ise yalnızca saat."""
    return saat(dk) + (f" (+{dk - harita.HEDEF_TESLIM} dk)" if dk > harita.HEDEF_TESLIM else "")


def ozet(s: optimizasyon.Sonuc) -> dict:
    dolu = [r for r in s.rotalar if r.hasta_sayisi]
    return {
        "En geç bitiş": saat(s.en_gec_bitis),
        "Ekip bitişleri": " / ".join(f"{r.ekip}: {saat(r.bitis_dk)}" for r in dolu),
        "Ekip başına hasta": " / ".join(str(r.hasta_sayisi) for r in dolu),
        "Toplam yol (km)": f"{s.toplam_km:.1f}",
        "Toplam çalışma (saat)": f"{s.toplam_calisma_dk / 60:.1f}",
        "Kan teslimi bitişi": ", ".join(teslim_yazisi(r.kan_teslim_dk) for r in dolu if r.kan_teslim_dk) or "–",
        "Rotaya sığmayan": ", ".join(s.atlanan) or "–",
    }


def rotalari_goster(sonuc: optimizasyon.Sonuc):
    components.html(harita.rota_haritasi(sonuc, merkez, lab).get_root().render(), height=520)
    kolonlar = st.columns(len(sonuc.rotalar))
    for k, (kol, r) in enumerate(zip(kolonlar, sonuc.rotalar)):
        with kol:
            st.markdown(harita.ekip_basligi(k, r), unsafe_allow_html=True)
            st.dataframe(harita.rota_tablosu(r), hide_index=True, width="stretch")


# ---------------------------------------------------------------------------
# Sol menü
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Planlama")
    tarih = st.date_input("Tarih", value=dt.date.today() + dt.timedelta(days=1), format="DD.MM.YYYY")
    varsay = st.checkbox(
        "Konumu olmayan hastaları merkez yakınında varsay", value=True,
        help="Deneme amaçlı: konumu bilinmeyen hastaların ziyaret süreleri hesaba katılsın diye "
             "merkezin 1–2 km çevresine yerleştirilir.")
    sure = st.slider("Çözüm süresi (saniye)", 5, 60, 10, help="Daha uzun süre genelde daha iyi rota demektir.")
    calistir = st.button("Rotaları oluştur", type="primary", width="stretch")

gun = ayarlar.GUNLER[tarih.weekday()]
tarih_str = tarih.isoformat()
gun_adi = ayarlar.GUN_TAM_ADLARI[gun]
tarih_yazi = f"{tarih.strftime('%d.%m.%Y')} {gun_adi}"

# ---------------------------------------------------------------------------
# Veriyi hazırla
# ---------------------------------------------------------------------------
try:
    merkez, lab = planlama.sabit_noktalar()
except RuntimeError as hata:
    st.error(str(hata))
    st.stop()

_, tum, z = planlama.gunun_verisi(tarih, konumsuzlari_varsay=varsay)
konumsuz = tum[tum["enlem"].isna()]

st.subheader(tarih_yazi)
c1, c2, c3, c4 = st.columns(4)
c1.metric("Ziyaret", len(tum))
c2.metric("Kan alınacak hasta", int(tum["kan_alimi"].sum()))
c3.metric("Toplam ziyaret süresi", f"{tum['sure_dk'].sum() / 60:.1f} saat")
c4.metric("Konumu olmayan", len(konumsuz))

if len(konumsuz):
    kodlar = ", ".join(konumsuz["hasta_kodu"])
    st.info(f"Konumu olmayan hastalar {'merkez yakınında varsayıldı' if varsay else 'rotaya alınmadı'}: {kodlar}")

with st.expander("Günün ziyaret listesi"):
    st.dataframe(
        z[["hasta_kodu", "tani", "mahalle", "islemler", "sure_dk", "kan_alimi", "konum_kaynagi"]],
        column_config={"hasta_kodu": "Hasta", "tani": "Tanı", "mahalle": "Mahalle",
                       "islemler": "İşlemler (sentetik)", "sure_dk": "Süre (dk)", "kan_alimi": "Kan alımı",
                       "konum_kaynagi": "Konum"},
        hide_index=True, width="stretch")

# ---------------------------------------------------------------------------
# Kayıtlı plan
# ---------------------------------------------------------------------------
kayitli = rota_kayit.yukle(tarih_str)
if kayitli:
    bilgi, kayitli_sonuc = kayitli
    st.success(f"✅ **{tarih_yazi} için kayıtlı rota var.** Kaydeden: {bilgi['olusturan']} · "
               f"{bilgi['olusturma']} · en geç bitiş {saat(bilgi['en_gec_bitis_dk'])} · "
               f"{bilgi['toplam_km']:.0f} km. Hemşireler bu rotayı görüyor.")
    with st.expander("Kayıtlı rotayı göster", expanded=not st.session_state.get("rota")):
        rotalari_goster(kayitli_sonuc)
else:
    st.info(f"{tarih_yazi} için henüz kayıtlı rota yok.")

# ---------------------------------------------------------------------------
# Optimizasyonu çalıştır
# ---------------------------------------------------------------------------
if calistir:
    with st.spinner("Rotalar hesaplanıyor..."):
        # Mevcut sistemin çözümü başlangıç olarak da kullanılır: optimize sonuç ondan kötü olamaz.
        yeni, eski = planlama.hesapla(z, sure_limiti_sn=sure)
    st.session_state["rota"] = {"anahtar": (tarih_str, varsay), "yeni": yeni, "eski": eski, "z": z}

hesap = st.session_state.get("rota")
if not hesap or hesap["anahtar"] != (tarih_str, varsay):
    st.caption("Yeni rota hesaplamak için soldaki **Rotaları oluştur** düğmesine basın.")
    st.stop()

yeni, eski, z = hesap["yeni"], hesap["eski"], hesap["z"]

st.divider()
st.subheader("Yeni hesaplanan rota")

# Kaydet
with st.container(border=True):
    if kayitli:
        uzerine = st.checkbox("Kayıtlı rotanın üzerine yazmak istiyorum")
    else:
        uzerine = True
    if st.button("💾 Rotayı kaydet ve ekiplere gönder", type="primary", disabled=not uzerine):
        rota_kayit.kaydet(tarih_str, gun, yeni, kullanici["id"], karsilastirma=eski, kaynak="elle")
        veritabani.iz_kaydi(kullanici["id"], "Rota kaydedildi",
                            f"{tarih_str} · {sum(r.hasta_sayisi for r in yeni.rotalar)} hasta")
        st.session_state.pop("rota", None)
        st.success("Rota kaydedildi.")
        st.rerun()
    st.caption("Ekip 1, 2, 3 rotaları; Personel sayfasında o ekibe atanmış hemşirelerin ekranına gider.")

# Karşılaştırma
fark_bitis = eski.en_gec_bitis - yeni.en_gec_bitis
fark_km = eski.toplam_km - yeni.toplam_km
m1, m2, m3 = st.columns(3)
m1.metric("En geç biten ekip", saat(yeni.en_gec_bitis),
          delta=f"{fark_bitis} dk daha erken" if fark_bitis >= 0 else f"{-fark_bitis} dk daha geç",
          delta_color="normal" if fark_bitis >= 0 else "inverse")
m2.metric("Toplam yol", f"{yeni.toplam_km:.0f} km", delta=f"{-fark_km:+.0f} km", delta_color="inverse")
m3.metric("Toplam çalışma süresi", f"{yeni.toplam_calisma_dk / 60:.1f} saat",
          delta=f"{(yeni.toplam_calisma_dk - eski.toplam_calisma_dk) / 60:+.1f} saat", delta_color="inverse")
st.caption("Değişimler mevcut bölge sistemine göredir.")

st.table(pd.DataFrame({"Optimize (yeni)": ozet(yeni), "Sabit bölgeler (mevcut)": ozet(eski)}))
st.caption("Mevcut bölgeler boylama göre ayrıldı "
           f"(batı < {optimizasyon.BATI_SINIRI}°, doğu > {optimizasyon.DOGU_SINIRI}°); gerçek sınırlara çok yakın.")

for kod in yeni.atlanan:
    satir = z[z["hasta_kodu"] == kod].iloc[0]
    st.error(f"**{kod} rotaya alınamadı.** {optimizasyon.atlama_nedeni(satir, merkez, lab)}")

if yeni.kan_gecikmesi_dk:
    st.warning(f"Kan teslimi {ayarlar.KAN_TESLIM_SON_SAAT}'den sonra bitiyor (toplam {yeni.kan_gecikmesi_dk} dk) "
               f"(izin verilen esneklik: en fazla {ayarlar.KAN_TESLIM_ESNEKLIK_DK} dk).")

sekme_yeni, sekme_eski = st.tabs(["Optimize rota", "Mevcut bölge sistemi"])
with sekme_yeni:
    rotalari_goster(yeni)
with sekme_eski:
    rotalari_goster(eski)
