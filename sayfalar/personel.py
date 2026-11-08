"""Kullanıcı (personel) yönetimi: ekle, düzenle, parola sıfırla. (Yönetici)"""

import re
import sqlite3

import streamlit as st

import ayarlar
import oturum
import veritabani

kullanici = oturum.rol_gerekli("yonetici")
st.title("👥 Personel")

ROLLER = list(ayarlar.ROL_ADLARI)
EKIPLER = [None] + list(range(1, ayarlar.EKIP_SAYISI + 1))
ekip_yazisi = lambda e: "—" if e is None else f"Ekip {e}"  # noqa: E731

personel = veritabani.kullanicilar()
st.dataframe(
    personel.assign(rol=personel["rol"].map(ayarlar.ROL_ADLARI), aktif=personel["aktif"].astype(bool)),
    column_config={"id": None, "kullanici_adi": "Kullanıcı adı", "ad_soyad": "Ad soyad", "rol": "Rol",
                   "ekip_no": st.column_config.NumberColumn("Ekip", format="%d"), "aktif": "Aktif",
                   "olusturma": "Oluşturma"},
    hide_index=True, width="stretch",
)


def parola_uygun(p1: str, p2: str) -> str | None:
    if len(p1) < 8:
        return "Parola en az 8 karakter olmalı."
    if p1 != p2:
        return "Parolalar aynı değil."
    return None


sekme_ekle, sekme_duzenle, sekme_parola = st.tabs(["Yeni kullanıcı", "Düzenle", "Parola sıfırla"])

with sekme_ekle:
    with st.form("yeni_kullanici", clear_on_submit=True):
        a, b = st.columns(2)
        kadi = a.text_input("Kullanıcı adı", help="Küçük harf, rakam, nokta veya alt çizgi. Örn. ayse.k")
        ad = b.text_input("Ad soyad")
        rol = a.selectbox("Rol", ROLLER, format_func=oturum.rol_adi)
        ekip = b.selectbox("Ekip (hemşireler için)", EKIPLER, format_func=ekip_yazisi)
        p1 = a.text_input("Geçici parola", type="password")
        p2 = b.text_input("Geçici parola (tekrar)", type="password")
        ekle = st.form_submit_button("Kullanıcı ekle", type="primary")
    if ekle:
        hata = None
        if not re.fullmatch(r"[a-z0-9._]{3,30}", kadi.strip()):
            hata = "Kullanıcı adı 3-30 karakter olmalı; yalnızca küçük harf, rakam, nokta, alt çizgi."
        elif not ad.strip():
            hata = "Ad soyad boş olamaz."
        else:
            hata = parola_uygun(p1, p2)
        if hata:
            st.error(hata)
        else:
            try:
                yeni_id = veritabani.kullanici_ekle(kadi, ad, rol, p1, ekip if rol == "hemsire" else None)
                veritabani.iz_kaydi(kullanici["id"], "Kullanıcı eklendi", f"{kadi} ({oturum.rol_adi(rol)})")
                st.success(f"{kadi} eklendi. Geçici parolayı kişiye güvenli bir yoldan iletin.")
                st.rerun()
            except sqlite3.IntegrityError:
                st.error("Bu kullanıcı adı zaten var.")

with sekme_duzenle:
    secilen = st.selectbox("Kullanıcı", personel["id"], key="duzenle_secim",
                           format_func=lambda i: personel.set_index("id").loc[i, "ad_soyad"])
    s = personel.set_index("id").loc[secilen]
    kendisi = int(secilen) == kullanici["id"]
    with st.form(f"duzenle_{secilen}"):
        ad = st.text_input("Ad soyad", value=s["ad_soyad"])
        rol = st.selectbox("Rol", ROLLER, index=ROLLER.index(s["rol"]), format_func=oturum.rol_adi,
                           disabled=kendisi)
        mevcut_ekip = None if s["ekip_no"] != s["ekip_no"] or s["ekip_no"] is None else int(s["ekip_no"])
        ekip = st.selectbox("Ekip", EKIPLER, index=EKIPLER.index(mevcut_ekip), format_func=ekip_yazisi)
        aktif = st.checkbox("Aktif (giriş yapabilir)", value=bool(s["aktif"]), disabled=kendisi or ayarlar.DEMO,
                            help="Demo modunda hesaplar pasif yapılamaz." if ayarlar.DEMO else None)
        if kendisi:
            st.caption("Kendi rolünüzü değiştiremez, hesabınızı pasif yapamazsınız.")
        kaydet = st.form_submit_button("Kaydet", type="primary")
    if kaydet:
        veritabani.kullanici_guncelle(int(secilen), ad, rol if not kendisi else s["rol"],
                                      ekip if rol == "hemsire" else None, aktif or kendisi)
        veritabani.iz_kaydi(kullanici["id"], "Kullanıcı güncellendi", s["kullanici_adi"])
        st.success("Kaydedildi.")
        st.rerun()

with sekme_parola:
    if ayarlar.DEMO:
        st.info("Demo modunda parolalar sıfırlanamaz (herkes aynı demo hesaplarını kullanıyor).")
        st.stop()
    secilen_p = st.selectbox("Kullanıcı", personel["id"], key="parola_secim",
                             format_func=lambda i: personel.set_index("id").loc[i, "ad_soyad"])
    with st.form("parola_sifirla", clear_on_submit=True):
        p1 = st.text_input("Yeni geçici parola", type="password")
        p2 = st.text_input("Yeni geçici parola (tekrar)", type="password")
        sifirla = st.form_submit_button("Parolayı sıfırla", type="primary")
    if sifirla:
        hata = parola_uygun(p1, p2)
        if hata:
            st.error(hata)
        else:
            veritabani.parola_degistir(int(secilen_p), p1)
            veritabani.iz_kaydi(kullanici["id"], "Parola sıfırlandı",
                                personel.set_index("id").loc[secilen_p, "kullanici_adi"])
            st.success("Parola değiştirildi. Kişiye güvenli bir yoldan iletin.")
