"""Rota haritası ve rota tablosu: yönetici ve hemşire sayfaları ortak kullanır."""

import folium
import pandas as pd

import ayarlar
import optimizasyon
import yol_guzergahi
from ayarlar import saat

RENKLER = ["#2563eb", "#dc2626", "#16a34a"]  # Ekip 1 mavi, Ekip 2 kırmızı, Ekip 3 yeşil
HEDEF_TESLIM = ayarlar.dakika(ayarlar.KAN_TESLIM_SON_SAAT)


def ekip_rengi(ekip_index: int) -> str:
    return RENKLER[ekip_index % len(RENKLER)]


def rota_haritasi(sonuc: optimizasyon.Sonuc, merkez, lab, sadece_ekip: int | None = None) -> folium.Map:
    """sadece_ekip: 0'dan başlayan ekip sırası; verilirse yalnızca o ekibin rotası çizilir."""
    m = folium.Map(location=merkez, zoom_start=10, tiles="OpenStreetMap")
    folium.Marker(merkez, tooltip="Merkez (ARSEV)", icon=folium.Icon(color="black", icon="home")).add_to(m)
    folium.Marker(lab, tooltip="7M Hastanesi (kan teslim)", icon=folium.Icon(color="red", icon="plus")).add_to(m)
    noktalar = [merkez, lab]
    for k, r in enumerate(sonuc.rotalar):
        if sadece_ekip is not None and k != sadece_ekip:
            continue
        renk = ekip_rengi(k)
        yol = [(d.enlem, d.boylam) for d in r.duraklar]
        noktalar += yol
        if r.hasta_sayisi:
            # Gösterim için gerçek yollar üzerinden güzergâh (hesap kuş uçuşu kalır; bkz. yol_guzergahi.py)
            folium.PolyLine(yol_guzergahi.rota_cizgisi(yol), color=renk, weight=4, opacity=0.75,
                            tooltip=r.ekip).add_to(m)
        sira = 0
        for d in r.duraklar:
            if d.tur != "Hasta":
                continue
            sira += 1
            folium.CircleMarker(
                (d.enlem, d.boylam), radius=8, color="white", weight=2, fill=True,
                fill_color=renk, fill_opacity=0.95,
                tooltip=f"{r.ekip} · {sira}. durak · {d.ad} · {saat(d.varis_dk)}–{saat(d.ayrilis_dk)}"
                        + (" · kan alımı" if d.kan_alimi else ""),
            ).add_to(m)
    sinir = [[min(p[0] for p in noktalar), min(p[1] for p in noktalar)],
             [max(p[0] for p in noktalar), max(p[1] for p in noktalar)]]
    # Başlangıç görünümü noktaların ortası (fitBounds çalışmasa bile harita Trabzon'da açılsın)
    m.location = [(sinir[0][0] + sinir[1][0]) / 2, (sinir[0][1] + sinir[1][1]) / 2]
    m.fit_bounds(sinir)
    # Harita gizli bir sekmede / kutuda çizilirken boyutu sıfırdır ve fitBounds boşa gider (bulutta görüldü).
    # Çözüm: sayfa yüklenince VE harita görünür hale geldiği anda (boyutu 0'dan büyüdüğünde)
    # boyutu yenile ve rotaya yeniden yakınlaş.
    ad = m.get_name()
    m.get_root().html.add_child(folium.Element(f"""<script>
(function () {{
  function sigdir() {{ try {{ {ad}.invalidateSize(); {ad}.fitBounds({sinir}); }} catch (e) {{}} }}
  window.addEventListener('load', function () {{ setTimeout(sigdir, 400); }});
  // Ekran çizimine bağlı olmayan yoklama: harita görünür (genişlik VE yükseklik > 0) ama henüz rotaya
  // yakınlaşmamışsa yakınlaş. Gizlenince (boyut 0) bayrak sıfırlanır; sekme tekrar açılınca yine yakınlaşır.
  var yakinlasti = false;
  setInterval(function () {{
    var kutu = document.getElementById('{ad}');
    var gorunur = kutu && kutu.clientWidth > 0 && kutu.clientHeight > 0;
    if (!gorunur) {{ yakinlasti = false; return; }}
    if (!yakinlasti) {{
      sigdir();
      try {{ yakinlasti = {ad}.getZoom() >= 6; }} catch (e) {{}}
    }}
  }}, 500);
}})();
</script>"""))
    return m


def rota_tablosu(r: optimizasyon.EkipRotasi) -> pd.DataFrame:
    satirlar = []
    for d in r.duraklar:
        if d.tur == "Hasta":
            ne = d.islemler.replace(";", ", ")
        elif d.tur == "7M Hastanesi":
            gec = d.ayrilis_dk - HEDEF_TESLIM  # teslimin bitişi 12:00'ye göre
            ne = f"Kan teslimi ({d.tup_sayisi} hasta)" + (f" · {gec} dk geç" if gec > 0 else "")
        else:
            ne = "Çıkış" if not satirlar else f"Dönüş + {ayarlar.MERKEZ_DONUS_SURESI_DK} dk ekipman teslimi"
        satirlar.append({"Varış": saat(d.varis_dk), "Ayrılış": saat(d.ayrilis_dk),
                         "Durak": d.ad, "Yapılacak": ne, "Kan": "🩸" if d.kan_alimi else ""})
    return pd.DataFrame(satirlar)


def ekip_basligi(k: int, r: optimizasyon.EkipRotasi) -> str:
    return (f"<span style='color:{ekip_rengi(k)};font-size:1.2em'>●</span> "
            f"**{r.ekip}** · {r.hasta_sayisi} hasta · {r.km:.0f} km · bitiş **{saat(r.bitis_dk)}**")
