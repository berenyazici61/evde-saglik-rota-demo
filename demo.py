"""
Demo modu yardımcıları.

Demo veritabanı belirli bir tarihe göre üretilir (geçmiş 7 gün ziyaretli, gelecek 7 gün rotalı).
Demo haftalar sonra açılırsa veriler eskimesin diye bütün tarihler TAM HAFTA olarak ileri kaydırılır
(haftanın günü değişmez, böylece rotalar ziyaret planıyla uyumlu kalır).
"""

import datetime as dt
import json
import threading

import ayarlar
import veritabani

BILGI_DOSYASI = ayarlar.VERI_KLASORU / "demo_bilgi.json"
_kilit = threading.Lock()

HESAPLAR = [  # (kullanıcı adı, ad, rol, ekip)
    ("yonetici", "Demo Yönetici", "yonetici", None),
    ("doktor1", "Dr. Demo 1", "doktor", None),
    ("doktor2", "Dr. Demo 2", "doktor", None),
] + [(f"hemsire{i}", f"Hemşire {i}", "hemsire", (i - 1) // 3 + 1) for i in range(1, 10)]


def bilgi_oku() -> dict:
    return json.loads(BILGI_DOSYASI.read_text(encoding="utf-8"))


def bilgi_yaz(bilgi: dict):
    BILGI_DOSYASI.write_text(json.dumps(bilgi, ensure_ascii=False, indent=2), encoding="utf-8")


def tarihleri_guncelle():
    """Demo verisini bugüne yaklaştırmak için tarihleri tam hafta olarak ileri kaydırır."""
    if not ayarlar.DEMO or not BILGI_DOSYASI.exists():
        return
    with _kilit:
        bilgi = bilgi_oku()
        referans = dt.date.fromisoformat(bilgi["referans_tarih"])
        hafta = (dt.date.today() - referans).days // 7
        if hafta <= 0:
            return
        kaydir = f"+{7 * hafta} days"
        with veritabani.baglanti() as con:
            # rotalar.tarih benzersiz: çakışma olmasın diye en yeniden başlayarak tek tek kaydır
            for (rid,) in con.execute("SELECT id FROM rotalar ORDER BY tarih DESC").fetchall():
                con.execute("UPDATE rotalar SET tarih = date(tarih, ?) WHERE id = ?", (kaydir, rid))
            con.execute("UPDATE ziyaret_kayitlari SET tarih = date(tarih, ?)", (kaydir,))
            con.execute("UPDATE doktor_notlari SET tarih = date(tarih, ?)", (kaydir,))
            con.execute("UPDATE rota_revizyonlari SET tarih = date(tarih, ?)", (kaydir,))
        bilgi["referans_tarih"] = (referans + dt.timedelta(days=7 * hafta)).isoformat()
        bilgi_yaz(bilgi)
