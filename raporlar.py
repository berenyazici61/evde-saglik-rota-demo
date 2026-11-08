"""
Rapor hesapları: kaydedilen rotalar (plan) ile hemşire ziyaret kayıtlarını (gerçekleşen) karşılaştırır.

Bir planlı ziyaret "yapıldı" sayılır: aynı tarihte o hasta için ziyaret kaydı girilmişse.
Geçmiş bir tarihte kaydı olmayan planlı ziyaret "kaçırıldı", bugün ve sonrası "bekliyor" sayılır.
"""

import datetime as dt

import pandas as pd

import veritabani


def rapor_verisi(baslangic: str, bitis: str, bugun: str | None = None) -> dict:
    bugun = bugun or dt.date.today().isoformat()
    p = (baslangic, bitis)

    rotalar = veritabani.tablo(
        """SELECT tarih, gun, en_gec_bitis_dk, toplam_km, kan_gecikmesi_dk, atlanan,
                  mevcut_en_gec_bitis_dk, mevcut_toplam_km, COALESCE(kaynak, 'elle') AS kaynak
           FROM rotalar WHERE tarih BETWEEN ? AND ? ORDER BY tarih""", p)
    ekipler = veritabani.tablo(
        """SELECT r.tarih, e.ekip_no, e.km, e.bitis_dk FROM rota_ekipleri e
           JOIN rotalar r ON r.id = e.rota_id WHERE r.tarih BETWEEN ? AND ?""", p)
    plan = veritabani.tablo(
        """SELECT r.tarih, d.ekip_no, d.sira, d.hasta_kodu, d.kan_alimi, d.varis_dk FROM rota_duraklari d
           JOIN rotalar r ON r.id = d.rota_id
           WHERE d.tur = 'Hasta' AND r.tarih BETWEEN ? AND ? ORDER BY r.tarih, d.ekip_no, d.sira""", p)
    kayit = veritabani.ziyaret_kayitlari_aralik(baslangic, bitis)

    # Plan durumu
    yapilan = set(zip(kayit["tarih"], kayit["hasta_kodu"]))
    plan["durum"] = [
        "Yapıldı" if (t, h) in yapilan else ("Kaçırıldı" if t < bugun else "Bekliyor")
        for t, h in zip(plan["tarih"], plan["hasta_kodu"])
    ]
    planli = set(zip(plan["tarih"], plan["hasta_kodu"]))
    plan_disi = kayit[[(t, h) not in planli for t, h in zip(kayit["tarih"], kayit["hasta_kodu"])]]

    # Günlük özet
    sayim = plan.pivot_table(index="tarih", columns="durum", values="hasta_kodu", aggfunc="count", fill_value=0)
    for d in ["Yapıldı", "Kaçırıldı", "Bekliyor"]:
        if d not in sayim.columns:
            sayim[d] = 0
    gunluk = rotalar.set_index("tarih").join(sayim, how="left").fillna({"Yapıldı": 0, "Kaçırıldı": 0, "Bekliyor": 0})
    gunluk["planlanan"] = (gunluk["Yapıldı"] + gunluk["Kaçırıldı"] + gunluk["Bekliyor"]).astype(int)
    gunluk["kazanc_dk"] = gunluk["mevcut_en_gec_bitis_dk"] - gunluk["en_gec_bitis_dk"]
    gunluk["km_farki"] = gunluk["toplam_km"] - gunluk["mevcut_toplam_km"]
    gunluk = gunluk.reset_index()

    # Ekip özeti
    ekip_hasta = plan.groupby("ekip_no").agg(planlanan=("hasta_kodu", "count"),
                                             yapilan=("durum", lambda s: int((s == "Yapıldı").sum())),
                                             kan_alimi=("kan_alimi", "sum"))
    ekip_yol = ekipler[ekipler["bitis_dk"] > 0].groupby("ekip_no").agg(
        gun=("tarih", "nunique"), toplam_km=("km", "sum"),
        ort_bitis_dk=("bitis_dk", "mean"), en_gec_bitis_dk=("bitis_dk", "max"))
    ekip = ekip_yol.join(ekip_hasta, how="outer").fillna(0).reset_index()

    return {"rotalar": rotalar, "gunluk": gunluk, "plan": plan, "plan_disi": plan_disi,
            "ekip": ekip, "kayit": kayit}
