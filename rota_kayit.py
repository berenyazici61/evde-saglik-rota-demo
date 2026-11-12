"""
Günlük rota planını veritabanına kaydetme ve geri yükleme.

Plan tarih başına tektir: aynı tarihe yeniden kaydedilen plan eskisinin yerini alır.
Ekip numarası = optimizasyondaki sıra (Ekip 1, 2, 3) = hemşirelerin ekip_no değeri.
"""

import optimizasyon
import veritabani


def kaydet(tarih: str, gun: str, sonuc: optimizasyon.Sonuc, kullanici_id: int | None,
           karsilastirma: optimizasyon.Sonuc | None = None, kaynak: str = "elle",
           mevcut_degerler: tuple | None = None) -> int:
    """
    karsilastirma: aynı günün mevcut bölge sistemi çözümü (raporlardaki kazanç hesabı için).
    kaynak: 'elle' (yönetici kaydetti), 'otomatik' (zamanlanmış betik) veya 'revizyon' (gün içi değişiklik).
    mevcut_degerler: (en_gec_bitis_dk, toplam_km) karşılaştırma yerine doğrudan verilir (revizyonda
                     sabah planının bölge sistemi değerleri korunur).
    """
    if karsilastirma is not None:
        mevcut_degerler = (karsilastirma.en_gec_bitis, round(karsilastirma.toplam_km, 2))
    mevcut_degerler = mevcut_degerler or (None, None)
    with veritabani.baglanti() as con:
        con.execute("DELETE FROM rotalar WHERE tarih = ?", (tarih,))  # eski plan + durakları (CASCADE)
        rota_id = con.execute(
            """INSERT INTO rotalar (tarih, gun, olusturan_id, en_gec_bitis_dk, toplam_km, kan_gecikmesi_dk, atlanan,
                                    mevcut_en_gec_bitis_dk, mevcut_toplam_km, kaynak)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (tarih, gun, kullanici_id, sonuc.en_gec_bitis, round(sonuc.toplam_km, 2),
             sonuc.kan_gecikmesi_dk, ",".join(sonuc.atlanan), *mevcut_degerler, kaynak)).lastrowid
        for ekip_no, r in enumerate(sonuc.rotalar, start=1):
            con.execute("INSERT INTO rota_ekipleri (rota_id, ekip_no, km, bitis_dk) VALUES (?, ?, ?, ?)",
                        (rota_id, ekip_no, round(r.km, 2), r.bitis_dk))
            con.executemany(
                """INSERT INTO rota_duraklari (rota_id, ekip_no, sira, tur, ad, hasta_kodu, enlem, boylam,
                                               varis_dk, ayrilis_dk, islemler, kan_alimi, tup_sayisi)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [(rota_id, ekip_no, sira, d.tur, d.ad, d.ad if d.tur == "Hasta" else None, d.enlem, d.boylam,
                  d.varis_dk, d.ayrilis_dk, d.islemler, int(d.kan_alimi), d.tup_sayisi)
                 for sira, d in enumerate(r.duraklar)])
    return rota_id


def yukle(tarih: str):
    """Kayıtlı planı (bilgi sözlüğü, Sonuc) olarak döndürür; yoksa None."""
    bilgi = veritabani.tablo(
        """SELECT r.*, COALESCE(k.ad_soyad, '-') AS olusturan
           FROM rotalar r LEFT JOIN kullanicilar k ON k.id = r.olusturan_id WHERE r.tarih = ?""", (tarih,))
    if bilgi.empty:
        return None
    bilgi = bilgi.iloc[0].to_dict()
    if bilgi.get("kaynak") == "otomatik":
        bilgi["olusturan"] = "Otomatik (zamanlanmış)"
    elif bilgi.get("kaynak") == "revizyon":
        bilgi["olusturan"] += " (gün içi revizyon)"
    ekipler = veritabani.tablo("SELECT * FROM rota_ekipleri WHERE rota_id = ? ORDER BY ekip_no", (bilgi["id"],))
    duraklar = veritabani.tablo("SELECT * FROM rota_duraklari WHERE rota_id = ? ORDER BY ekip_no, sira",
                                (bilgi["id"],))
    rotalar = []
    for e in ekipler.itertuples():
        rota = optimizasyon.EkipRotasi(f"Ekip {e.ekip_no}", km=float(e.km or 0), bitis_dk=int(e.bitis_dk or 0))
        for d in duraklar[duraklar["ekip_no"] == e.ekip_no].itertuples():
            rota.duraklar.append(optimizasyon.Durak(
                d.tur, d.ad, d.enlem, d.boylam, int(d.varis_dk), int(d.ayrilis_dk),
                d.islemler or "", bool(d.kan_alimi), int(d.tup_sayisi)))
        rotalar.append(rota)
    atlanan = [k for k in (bilgi["atlanan"] or "").split(",") if k]
    return bilgi, optimizasyon.Sonuc(rotalar, atlanan, True)


def revizyon_kaydet(tarih: str, gun: str, eski_bilgi: dict, eski: optimizasyon.Sonuc, rs, olay_saati_dk: int,
                    olaylar: list, kullanici_id: int | None) -> int:
    """Gün içi revizyonu onaylar: planı yenisiyle değiştirir ve revizyon geçmişine yazar."""
    etkilenen = sorted({k for k, (a, b) in enumerate(zip(eski.rotalar, rs.sonuc.rotalar), start=1)
                        if [d.ad for d in a.duraklar] != [d.ad for d in b.duraklar]
                        or a.bitis_dk != b.bitis_dk})
    degisiklik = "; ".join(f"{h}: {'yeni' if e is None else f'Ekip {e}'} → Ekip {y}" for h, e, y in rs.degisen)
    kaydet(tarih, gun, rs.sonuc, kullanici_id, kaynak="revizyon",
           mevcut_degerler=(eski_bilgi.get("mevcut_en_gec_bitis_dk"), eski_bilgi.get("mevcut_toplam_km")))
    with veritabani.baglanti() as con:
        return con.execute(
            """INSERT INTO rota_revizyonlari (tarih, olay_saati_dk, olaylar, etkilenen_ekipler, degisiklikler,
                                              onceki_bitis_dk, yeni_bitis_dk, kullanici_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (tarih, olay_saati_dk, " | ".join(o.aciklama() for o in olaylar), ",".join(map(str, etkilenen)),
             degisiklik, eski.en_gec_bitis, rs.sonuc.en_gec_bitis, kullanici_id)).lastrowid


def revizyonlar(tarih: str):
    return veritabani.tablo(
        """SELECT r.*, COALESCE(k.ad_soyad, '-') AS kaydeden FROM rota_revizyonlari r
           LEFT JOIN kullanicilar k ON k.id = r.kullanici_id WHERE r.tarih = ? ORDER BY r.id""", (tarih,))
