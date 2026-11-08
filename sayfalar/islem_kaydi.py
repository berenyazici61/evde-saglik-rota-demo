"""İz kaydı: kim, ne zaman, ne yaptı (KVKK). (Yönetici)"""

import streamlit as st

import oturum
import veritabani

oturum.rol_gerekli("yonetici")
st.title("🕓 İşlem Kaydı")
st.caption("Girişler, hatalı giriş denemeleri ve tüm kayıt değişiklikleri burada tutulur.")

limit = st.select_slider("Gösterilecek kayıt", options=[100, 300, 1000, 5000], value=300)
kayitlar = veritabani.iz_kayitlari(limit)
ara = st.text_input("Ara (kullanıcı, eylem veya ayrıntı)")
if ara:
    a = ara.lower()
    kayitlar = kayitlar[kayitlar.astype(str).apply(lambda s: s.str.lower().str.contains(a, regex=False)).any(axis=1)]

st.dataframe(kayitlar, column_config={"zaman": "Zaman", "kullanici": "Kullanıcı", "eylem": "Eylem",
                                      "ayrinti": "Ayrıntı"}, hide_index=True, width="stretch", height=500)
