"""
Evde Sağlık Rota Uygulaması - giriş noktası.

Çalıştırmak için terminalde (proje klasöründe):
    py -m streamlit run app.py

Giriş yapmamış kullanıcı yalnızca giriş ekranını görür. Giriş yapan kullanıcı
rolüne göre (yönetici / doktor / hemşire) yalnızca kendi sayfalarını görür.
"""

import streamlit as st

import ayarlar
import oturum
import veritabani

st.set_page_config(page_title="Evde Sağlık Rota" + (" (Demo)" if ayarlar.DEMO else ""), page_icon="🚑",
                   layout="wide")
veritabani.kur()  # tablolar yoksa oluştur
if ayarlar.DEMO:
    import demo

    demo.tarihleri_guncelle()  # demo verisini bu haftaya taşı

S = "sayfalar/"
SAYFALAR = {
    "genel": st.Page(S + "genel_bakis.py", title="Genel Bakış", icon=":material/dashboard:"),
    "rota": st.Page(S + "rota_planlama.py", title="Rota Planlama", icon=":material/route:"),
    "rapor": st.Page(S + "raporlar.py", title="Raporlar", icon=":material/bar_chart:"),
    "hastalar": st.Page(S + "hastalar.py", title="Hastalar", icon=":material/patient_list:"),
    "personel": st.Page(S + "personel.py", title="Personel", icon=":material/badge:"),
    "iz": st.Page(S + "islem_kaydi.py", title="İşlem Kaydı", icon=":material/history:"),
    "yedek": st.Page(S + "yedekler.py", title="Yedekler", icon=":material/backup:"),
    "hrota": st.Page(S + "hemsire_rota.py", title="Bugünkü Rotam", icon=":material/directions_car:"),
    "ziyaret": st.Page(S + "hemsire_ziyaret.py", title="Ziyaret Kaydı", icon=":material/medical_services:"),
    "doktor": st.Page(S + "doktor_hasta.py", title="Hasta Takibi", icon=":material/stethoscope:"),
    "hesabim": st.Page(S + "hesabim.py", title="Hesabım", icon=":material/person:"),
}

# Hangi rol hangi sayfaları görür
ROL_MENUSU = {
    "yonetici": {
        "Planlama": ["genel", "rota", "rapor"],
        "Kayıtlar": ["hastalar", "personel", "iz", "yedek"],
        "Hesap": ["hesabim"],
    },
    "doktor": {
        "Hastalar": ["doktor", "genel"],
        "Hesap": ["hesabim"],
    },
    "hemsire": {
        "Saha": ["hrota", "ziyaret"],
        "Hesap": ["hesabim"],
    },
}

kullanici = oturum.aktif_kullanici()
if kullanici is None:
    sayfa = st.navigation([st.Page(oturum.giris_ekrani, title="Giriş", icon=":material/login:")])
else:
    menu = {bolum: [SAYFALAR[a] for a in anahtarlar]
            for bolum, anahtarlar in ROL_MENUSU[kullanici["rol"]].items()}
    sayfa = st.navigation(menu)
    with st.sidebar:
        if ayarlar.DEMO:
            st.warning("**DEMO** · Tüm hasta ve personel bilgileri uydurmadır.", icon=":material/science:")
        ekip = f" · Ekip {kullanici['ekip_no']}" if kullanici.get("ekip_no") else ""
        st.markdown(f"**{kullanici['ad_soyad']}**  \n{oturum.rol_adi(kullanici['rol'])}{ekip}")
        st.button("Çıkış yap", on_click=oturum.cikis, icon=":material/logout:", width="stretch")

sayfa.run()
