"""
Gün içi değişiklik (Yönetici): acil hasta, uzayan ziyaret veya iptal olduğunda kayıtlı rota,
ekiplerin o anki durumundan başlayarak yeniden hesaplanır.
  1. Tarih ve olay saati seçilir; ekiplerin o andaki durumu gösterilir.
  2. Olaylar listeye eklenir (birden fazla olabilir).
  3. "Rotayı yeniden hesapla" -> eski ve yeni plan karşılaştırılır.
  4. "Onayla ve ekiplere gönder" -> yeni plan kaydedilir, hemşire ekranları güncellenir.
"""

import datetime as dt

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import ayarlar
import harita
import oturum
import planlama
import revizyon
import rota_kayit
import veri_yukle
import veritabani
from ayarlar import saat

kullanici = oturum.rol_gerekli("yonetici")
st.title("🚨 Gün İçi Değişiklik")
st.caption("Acil hasta, uzayan ziyaret veya iptal olduğunda rotayı ekiplerin **o anki durumundan** başlayarak "
           "yeniden hesaplar. Tamamlanan ve devam eden ziyaretler değişmez; araçtaki kan örnekleri aynı ekip "
           "tarafından teslim edilir.")

try:
    merkez, lab = planlama.sabit_noktalar()
except RuntimeError as hata:
    st.error(str(hata))
    st.stop()

# ---------------------------------------------------------------------------
# Tarih, saat, kayıtlı plan
# ---------------------------------------------------------------------------
bugun = dt.date.today()
c1, c2, c3 = st.columns([2, 2, 3])
tarih = c1.date_input("Tarih", value=bugun, format="DD.MM.YYYY")
simdi = dt.datetime.now()
varsayilan = (dt.time(simdi.hour, simdi.minute - simdi.minute % 5) if tarih == bugun and 9 <= simdi.hour < 18
              else dt.time(10, 30))
olay_saati = c2.time_input("Olay saati", value=varsayilan, step=300)
sure = c3.slider("Çözüm süresi (saniye)", 4, 30, 8)
an_dk = olay_saati.hour * 60 + olay_saati.minute
tarih_str = tarih.isoformat()
gun = ayarlar.GUNLER[tarih.weekday()]

kayit = rota_kayit.yukle(tarih_str)
if kayit is None:
    st.info(f"{tarih.strftime('%d.%m.%Y')} için kayıtlı rota yok. Önce **Rota Planlama** sayfasından rotayı kaydedin.")
    st.stop()
bilgi, plan = kayit

anahtar = (tarih_str, an_dk)
if st.session_state.get("rev_anahtar_tarih") != tarih_str:  # tarih değişince olay listesi sıfırlansın
    st.session_state["rev_olaylar"] = []
    st.session_state.pop("rev_sonuc", None)
    st.session_state["rev_anahtar_tarih"] = tarih_str
olaylar: list[revizyon.Olay] = st.session_state.setdefault("rev_olaylar", [])

tamamlanan = set(veritabani.ziyaret_kayitlari(tarih=tarih_str)["hasta_kodu"])
durumlar, _ = revizyon.durum_cikar(plan, an_dk, tamamlanan, [])

st.subheader(f"Ekiplerin {saat(an_dk)} itibarıyla durumu")
st.dataframe(revizyon.durum_tablosu(durumlar, an_dk), hide_index=True, width="stretch")
st.caption("Durum, kayıtlı plandaki saatlerden ve hemşirelerin girdiği ziyaret kayıtlarından çıkarılır. "
           "Yoldaki ekibin konumu iki durak arasında tahmin edilir.")

# ---------------------------------------------------------------------------
# Olay ekleme
# ---------------------------------------------------------------------------
st.subheader("Olay ekle")
plandaki_kalan = [d.ad for e in durumlar for d in e.kalan if d.tur == "Hasta"]
devam_eden = [e.sabit[-1].ad for e in durumlar
              if e.sabit[-1].tur == "Hasta" and e.sabit[-1].ayrilis_dk > an_dk and e.sabit[-1].ad not in tamamlanan]
ekibi = {d.ad: e.ekip_no for e in durumlar for d in e.sabit + e.kalan if d.tur == "Hasta"}
hastalar = veri_yukle.hastalari_yukle().dropna(subset=["enlem"]).set_index("hasta_kodu")

tur = st.radio("Olay türü", list(revizyon.OLAY_TURLERI), format_func=revizyon.OLAY_TURLERI.get, horizontal=True)

with st.container(border=True):
    if tur == "acil":
        secenek = list(hastalar.index)
        hasta = st.selectbox(
            "Hasta", secenek,
            format_func=lambda k: f"{k} · {hastalar.at[k, 'mahalle']}"
                                  + (f" · bugün Ekip {ekibi[k]} planında" if k in ekibi else ""))
        gunun = veri_yukle.gunun_ziyaretleri(gun).set_index("hasta_kodu")["islemler"]
        varsayilan_islem = gunun.get(hasta, veri_yukle.VARSAYILAN_ISLEM).split(";")
        sureler = veri_yukle.islem_sureleri_sozlugu()
        islemler = st.multiselect("Yapılacak işlemler", list(sureler),
                                  default=[i for i in varsayilan_islem if i in sureler])
        ziyaret_suresi = sum(sureler[i] for i in islemler)
        st.caption(f"Planlanan ziyaret süresi: **{ziyaret_suresi} dk**. Hasta listede yoksa önce **Hastalar** "
                   "sayfasından eklenmeli (konumu gerekli).")
        if hasta in tamamlanan:
            st.info(f"{hasta} için bugün ziyaret kaydı var; acil olarak yeniden ziyaret edilecek.")
        if st.button("Olayı ekle", type="primary", disabled=not islemler):
            olaylar[:] = [o for o in olaylar if o.hasta_kodu != hasta]
            olaylar.append(revizyon.Olay("acil", hasta, islemler=";".join(islemler), sure_dk=ziyaret_suresi,
                                         kan_alimi="Kan alımı" in islemler,
                                         enlem=float(hastalar.at[hasta, "enlem"]),
                                         boylam=float(hastalar.at[hasta, "boylam"])))
            st.session_state.pop("rev_sonuc", None)
            st.rerun()
    else:
        aday = devam_eden + [k for k in plandaki_kalan if k not in devam_eden]
        if tur == "iptal":
            st.caption("Henüz yapılmamış veya ekibin şu an bulunduğu (devam eden) ziyaret iptal edilebilir.")
        else:
            st.caption("Devam eden ziyaret uzarsa sonraki duraklar kayar; ileride uzaması beklenen bir ziyaret de "
                       "seçilebilir.")
        if not aday:
            st.info("Değiştirilebilecek ziyaret kalmadı.")
        else:
            hasta = st.selectbox("Hasta", aday, format_func=lambda k: f"{k} · Ekip {ekibi.get(k, '?')}"
                                 + (" · şu an ziyarette" if k in devam_eden else ""))
            ek = st.number_input("Ek süre (dk)", 5, 180, 20, step=5) if tur == "uzama" else 0
            if st.button("Olayı ekle", type="primary"):
                olaylar.append(revizyon.Olay(tur, hasta, ek_dk=int(ek)))
                st.session_state.pop("rev_sonuc", None)
                st.rerun()

if olaylar:
    st.markdown("**Eklenen olaylar**")
    for i, o in enumerate(olaylar):
        a, b = st.columns([6, 1])
        a.write(f"{revizyon.OLAY_TURLERI[o.tur].split()[0]} {o.aciklama()}")
        if b.button("Sil", key=f"sil_{i}"):
            olaylar.pop(i)
            st.session_state.pop("rev_sonuc", None)
            st.rerun()
    if st.button("🔄 Rotayı yeniden hesapla", type="primary", width="stretch"):
        with st.spinner("Rota yeniden hesaplanıyor..."):
            try:
                rs = revizyon.revize_et(plan, an_dk, tamamlanan, olaylar, merkez, lab, sure_limiti_sn=sure)
                st.session_state["rev_sonuc"] = (anahtar, [*olaylar], rs)
            except RuntimeError as hata:
                st.error(str(hata))
else:
    st.caption("Henüz olay eklenmedi.")

# ---------------------------------------------------------------------------
# Sonuç ve onay
# ---------------------------------------------------------------------------
hesap = st.session_state.get("rev_sonuc")
if hesap and hesap[0] == anahtar:
    _, hesap_olaylari, rs = hesap
    yeni = rs.sonuc
    st.divider()
    st.subheader("Önerilen yeni rota")

    for u in rs.uyarilar:
        st.warning(u)
    for kod, neden in rs.atlanan_nedenleri.items():
        st.error(f"**{kod} yeni rotaya alınamadı.** {neden}")

    m = st.columns(4)
    for kod, varis in rs.acil_varis.items():
        ekip = next(k for k, r in enumerate(yeni.rotalar, start=1) if any(d.ad == kod for d in r.duraklar
                                                                        if d.varis_dk == varis))
        m[0].metric(f"Acil {kod}", saat(varis), delta=f"Ekip {ekip} · {varis - an_dk} dk sonra",
                    delta_color="off")
    fark = yeni.en_gec_bitis - plan.en_gec_bitis
    m[1].metric("En geç bitiş", saat(yeni.en_gec_bitis), delta=f"{fark:+d} dk", delta_color="inverse")
    m[2].metric("Toplam yol", f"{yeni.toplam_km:.0f} km", delta=f"{yeni.toplam_km - plan.toplam_km:+.0f} km",
                delta_color="inverse")
    m[3].metric("Ekip değiştiren hasta", sum(e is not None for _, e, _y in rs.degisen))

    karsilastirma = pd.DataFrame({
        "Ekip": [r.ekip for r in yeni.rotalar],
        "Önceki bitiş": [saat(r.bitis_dk) for r in plan.rotalar],
        "Yeni bitiş": [saat(r.bitis_dk) for r in yeni.rotalar],
        "Önceki hasta": [r.hasta_sayisi for r in plan.rotalar],
        "Yeni hasta": [r.hasta_sayisi for r in yeni.rotalar],
        "Kan teslimi (yeni)": [saat(r.kan_teslim_dk) if r.kan_teslim_dk else "–" for r in yeni.rotalar],
    })
    st.dataframe(karsilastirma, hide_index=True, width="stretch")
    if rs.degisen:
        st.markdown("**Ekip değişiklikleri:** " + "; ".join(
            f"{h}: {'yeni (acil)' if e is None else f'Ekip {e}'} → **Ekip {y}**" for h, e, y in rs.degisen))
    st.caption(f"Amaç: en geç bitiş + toplam yol + kan gecikmesi cezası + acil hastanın her bekleme dakikası "
               f"×{ayarlar.ACIL_BEKLEME_AGIRLIGI} + ekip değiştiren her hasta {ayarlar.DEGISIKLIK_CEZASI_DK} dk. "
               "Sabah planının kalanı başlangıç çözümü olarak da denenir.")

    with st.container(border=True):
        if st.button("✅ Onayla ve ekiplere gönder", type="primary"):
            rota_kayit.revizyon_kaydet(tarih_str, gun, bilgi, plan, rs, an_dk, hesap_olaylari, kullanici["id"])
            veritabani.iz_kaydi(kullanici["id"], "Rota revize edildi",
                                f"{tarih_str} {saat(an_dk)} · " + " | ".join(o.aciklama() for o in hesap_olaylari))
            st.session_state["rev_olaylar"] = []
            st.session_state.pop("rev_sonuc", None)
            st.success("Yeni rota kaydedildi; hemşire ekranlarında güncellendi.")
            st.rerun()
        st.caption("Onaylanınca kayıtlı rota bununla değişir ve ilgili ekiplere 'rotanız güncellendi' notu gider.")

    sekme_yeni, sekme_eski = st.tabs(["Yeni rota", "Önceki rota"])
    for sekme, s in ((sekme_yeni, yeni), (sekme_eski, plan)):
        with sekme:
            components.html(harita.rota_haritasi(s, merkez, lab).get_root().render(), height=480)
            kolonlar = st.columns(len(s.rotalar))
            for k, (kol, r) in enumerate(zip(kolonlar, s.rotalar)):
                with kol:
                    st.markdown(harita.ekip_basligi(k, r), unsafe_allow_html=True)
                    st.dataframe(harita.rota_tablosu(r), hide_index=True, width="stretch")

# ---------------------------------------------------------------------------
# Bugünün revizyon geçmişi
# ---------------------------------------------------------------------------
gecmis = rota_kayit.revizyonlar(tarih_str)
if not gecmis.empty:
    st.divider()
    st.subheader("Bu tarihte onaylanan revizyonlar")
    st.dataframe(
        gecmis.assign(olay_saati=gecmis["olay_saati_dk"].map(saat),
                      bitis=gecmis["onceki_bitis_dk"].map(saat) + " → " + gecmis["yeni_bitis_dk"].map(saat)),
        column_order=["olay_saati", "olaylar", "degisiklikler", "etkilenen_ekipler", "bitis", "kaydeden",
                      "kayit_zamani"],
        column_config={"olay_saati": "Olay saati", "olaylar": "Olaylar", "degisiklikler": "Ekip değişiklikleri",
                       "etkilenen_ekipler": "Etkilenen ekipler", "bitis": "En geç bitiş", "kaydeden": "Onaylayan",
                       "kayit_zamani": "Kayıt"},
        hide_index=True, width="stretch")
