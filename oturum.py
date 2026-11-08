"""
Giriş / çıkış ve yetki kontrolü.

Oturumdaki kullanıcı st.session_state["kullanici"] içinde tutulur.
Her sayfa en başta rol_gerekli(...) çağırır: yetkisi olmayan kullanıcı sayfayı göremez.
"""

import time

import streamlit as st

import ayarlar
import veritabani

AZAMI_DENEME = 5          # bu kadar hatalı denemeden sonra
BEKLEME_SN = 60           # giriş bu kadar saniye kilitlenir


def aktif_kullanici() -> dict | None:
    return st.session_state.get("kullanici")


def giris_ekrani():
    st.title("🚑 Evde Sağlık Rota")
    st.caption("ARSEV Evde Sağlık Hizmetleri")

    kilit = st.session_state.get("giris_kilit_bitis", 0)
    if time.time() < kilit:
        st.error(f"Çok fazla hatalı deneme. Lütfen {int(kilit - time.time())} saniye sonra tekrar deneyin.")
        st.stop()

    if ayarlar.DEMO:
        st.info(
            "**Bu bir demodur; bütün hasta ve personel bilgileri uydurmadır.**\n\n"
            f"Aşağıdaki hesaplarla girebilirsiniz (parola hepsi için: `{ayarlar.DEMO_PAROLASI}`):\n"
            "- `yonetici`: rota planlama, raporlar, hastalar, personel\n"
            "- `doktor1`: hasta takibi, not ve talimat\n"
            "- `hemsire1` (Ekip 1), `hemsire4` (Ekip 2), `hemsire7` (Ekip 3): günlük rota ve ziyaret kaydı",
            icon=":material/science:")

    with st.form("giris"):
        kullanici_adi = st.text_input("Kullanıcı adı")
        parola = st.text_input("Parola", type="password")
        gonder = st.form_submit_button("Giriş yap", type="primary", width="stretch")

    if gonder:
        k = veritabani.kullanici_dogrula(kullanici_adi, parola)
        if k is None:
            deneme = st.session_state.get("giris_deneme", 0) + 1
            st.session_state["giris_deneme"] = deneme
            veritabani.iz_kaydi(None, "Hatalı giriş denemesi", f"kullanıcı adı: {kullanici_adi[:40]}")
            if deneme >= AZAMI_DENEME:
                st.session_state["giris_kilit_bitis"] = time.time() + BEKLEME_SN
                st.session_state["giris_deneme"] = 0
            st.error("Kullanıcı adı veya parola hatalı.")
        else:
            st.session_state["kullanici"] = k
            st.session_state["giris_deneme"] = 0
            veritabani.iz_kaydi(k["id"], "Giriş")
            st.rerun()


def cikis():
    k = aktif_kullanici()
    if k:
        veritabani.iz_kaydi(k["id"], "Çıkış")
    st.session_state.clear()


def rol_gerekli(*roller: str) -> dict:
    """Sayfanın başında çağrılır. Kullanıcı bu rollerden birinde değilse sayfayı durdurur."""
    k = aktif_kullanici()
    if k is None or k["rol"] not in roller:
        st.error("Bu sayfayı görüntüleme yetkiniz yok.")
        st.stop()
    return k


def rol_adi(rol: str) -> str:
    return ayarlar.ROL_ADLARI.get(rol, rol)
