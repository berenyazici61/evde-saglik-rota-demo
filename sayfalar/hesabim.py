"""Kullanıcının kendi hesabı: bilgiler ve parola değiştirme. (Herkes)"""

import streamlit as st

import ayarlar
import oturum
import veritabani

kullanici = oturum.rol_gerekli("yonetici", "doktor", "hemsire")
st.title("👤 Hesabım")
st.write(f"**{kullanici['ad_soyad']}** · {oturum.rol_adi(kullanici['rol'])} · kullanıcı adı: `{kullanici['kullanici_adi']}`")

st.subheader("Parolamı değiştir")
if ayarlar.DEMO:
    st.info("Demo modunda parolalar değiştirilemez (herkes aynı demo hesaplarını kullanıyor).")
    st.stop()
with st.form("parola", clear_on_submit=True):
    eski = st.text_input("Mevcut parola", type="password")
    p1 = st.text_input("Yeni parola (en az 8 karakter)", type="password")
    p2 = st.text_input("Yeni parola (tekrar)", type="password")
    degistir = st.form_submit_button("Değiştir", type="primary")
if degistir:
    if not veritabani.parola_kontrol(kullanici["id"], eski):
        st.error("Mevcut parola hatalı.")
    elif len(p1) < 8:
        st.error("Yeni parola en az 8 karakter olmalı.")
    elif p1 != p2:
        st.error("Yeni parolalar aynı değil.")
    else:
        veritabani.parola_degistir(kullanici["id"], p1)
        veritabani.iz_kaydi(kullanici["id"], "Kendi parolasını değiştirdi")
        st.success("Parolanız değiştirildi.")
