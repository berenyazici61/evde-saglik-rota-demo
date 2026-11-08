"""Veritabanı yedekleri: yedek al, indir, yedekten geri dön. (Yönetici)"""

import streamlit as st

import ayarlar
import oturum
import veritabani
import yedekleme

kullanici = oturum.rol_gerekli("yonetici")
st.title("💾 Yedekler")
st.caption(f"Her akşam zamanlanmış görev otomatik yedek alır. En yeni {ayarlar.YEDEK_SAKLAMA_SAYISI} yedek tutulur.")
st.warning("Yedekler hasta verisi içerir ve bu bilgisayarda durur. Bilgisayar arızasına karşı haftada bir, "
           "kurumun onayladığı güvenli bir yere (şifreli harici disk / kurum sunucusu) kopyalayın.")

if st.button("Şimdi yedek al", type="primary", icon=":material/backup:"):
    yol = yedekleme.yedek_al("elle")
    veritabani.iz_kaydi(kullanici["id"], "Yedek alındı", yol.name)
    st.success(f"Yedek alındı: {yol.name}")

liste = yedekleme.yedekler()
if liste.empty:
    st.info("Henüz yedek yok.")
    st.stop()

ETIKETLER = {"elle": "Elle", "otomatik": "Otomatik", "geri_donus_oncesi": "Geri dönüş öncesi"}
st.dataframe(
    liste.assign(etiket=liste["etiket"].map(lambda e: ETIKETLER.get(e, e)),
                 zaman=liste["zaman"].dt.strftime("%d.%m.%Y %H:%M:%S")),
    column_config={"dosya": "Dosya", "zaman": "Zaman", "etiket": "Tür", "boyut_kb": "Boyut (KB)"},
    hide_index=True, width="stretch")

secilen = st.selectbox("Yedek seçin", liste["dosya"],
                       format_func=lambda d: f"{liste.set_index('dosya').loc[d, 'zaman']:%d.%m.%Y %H:%M:%S} · {d}")

with st.expander("Seçilen yedeği indir"):
    st.caption("İndirilen dosya hasta verisi içerir; yalnızca güvenli bir yere kaydedin.")
    if st.download_button("İndir", yedekleme.yedek_yolu(secilen).read_bytes(), file_name=secilen,
                          mime="application/octet-stream"):
        veritabani.iz_kaydi(kullanici["id"], "Yedek indirildi", secilen)

with st.expander("Bu yedeğe geri dön"):
    st.error("Veritabanı seçilen yedekteki haline döner. Yedekten sonra girilen bütün kayıtlar "
             "(ziyaretler, notlar, rotalar, kullanıcılar) bu ekrandan kaybolur. Geri dönmeden önce mevcut "
             "durumun yedeği otomatik alınır; gerekirse ona geri dönebilirsiniz.")
    eminim = st.checkbox(f"Anladım, {secilen} yedeğine geri dönmek istiyorum")
    if st.button("Geri dön", disabled=not eminim):
        try:
            guvenlik = yedekleme.geri_don(secilen)
        except (ValueError, FileNotFoundError) as hata:
            st.error(f"Geri dönülemedi: {hata}")
        else:
            veritabani.kur()  # eski yedekte olmayan tablo / sütunları tamamla
            veritabani.iz_kaydi(kullanici["id"], "Yedekten geri dönüldü",
                                f"{secilen} (öncesi yedek: {guvenlik.name})")
            st.session_state.clear()  # kullanıcı listesi değişmiş olabilir: yeniden giriş
            st.success("Geri dönüldü. Lütfen yeniden giriş yapın.")
            st.rerun()
