"""
Veritabanı katmanı (SQLite).

Tüm okuma/yazma işlemleri bu dosyadaki fonksiyonlardan geçer. SQL sorgularında
değerler her zaman "?" yer tutucularıyla verilir (SQL enjeksiyonuna karşı).

Tablolar:
  kullanicilar       yönetici / doktor / hemşire hesapları (parolalar hash'li)
  hastalar           hasta bilgileri ve temsili konum
  ziyaret_plani      hangi hastaya haftanın hangi günü gidilir
  islem_turleri      işlem süreleri (min / max)
  hasta_islemleri    planlanan ziyarette yapılacak işlemler (şimdilik sentetik)
  ziyaret_kayitlari  hemşirelerin girdiği ziyaret kayıtları (vital bulgular, notlar)
  doktor_notlari     doktorların muayene notları ve hemşire talimatları
  islem_kaydi        kim, ne zaman, ne yaptı (KVKK için iz kaydı)
  rotalar            kaydedilen günlük rota planı (tarih başına bir tane)
  rota_ekipleri      plandaki her ekibin km'si ve bitiş saati
  rota_duraklari     her ekibin sıralı durakları (merkez, hastalar, 7M)
"""

import hashlib
import secrets
import sqlite3
from contextlib import contextmanager

import pandas as pd

import ayarlar

SEMA = """
CREATE TABLE IF NOT EXISTS kullanicilar (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    kullanici_adi   TEXT NOT NULL UNIQUE,
    ad_soyad        TEXT NOT NULL,
    rol             TEXT NOT NULL CHECK (rol IN ('yonetici', 'doktor', 'hemsire')),
    ekip_no         INTEGER,
    parola_hash     TEXT NOT NULL,
    aktif           INTEGER NOT NULL DEFAULT 1,
    olusturma       TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS hastalar (
    hasta_kodu      TEXT PRIMARY KEY,
    tani            TEXT,
    mahalle         TEXT,
    konum_tarifi    TEXT,
    enlem           REAL,
    boylam          REAL,
    konum_kaynagi   TEXT,
    notlar          TEXT,
    aktif           INTEGER NOT NULL DEFAULT 1,
    guncelleme      TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS ziyaret_plani (
    hasta_kodu      TEXT NOT NULL REFERENCES hastalar(hasta_kodu) ON DELETE CASCADE,
    gun             TEXT NOT NULL CHECK (gun IN ('Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cts', 'Paz')),
    PRIMARY KEY (hasta_kodu, gun)
);

CREATE TABLE IF NOT EXISTS islem_turleri (
    islem           TEXT PRIMARY KEY,
    min_dk          INTEGER NOT NULL,
    max_dk          INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS hasta_islemleri (
    hasta_kodu      TEXT NOT NULL REFERENCES hastalar(hasta_kodu) ON DELETE CASCADE,
    gun             TEXT NOT NULL,
    islem           TEXT NOT NULL REFERENCES islem_turleri(islem),
    sentetik        INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (hasta_kodu, gun, islem)
);

CREATE TABLE IF NOT EXISTS ziyaret_kayitlari (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    hasta_kodu        TEXT NOT NULL REFERENCES hastalar(hasta_kodu),
    tarih             TEXT NOT NULL,
    kullanici_id      INTEGER NOT NULL REFERENCES kullanicilar(id),
    yapilan_islemler  TEXT,
    tansiyon          TEXT,
    nabiz             INTEGER,
    ates              REAL,
    seker             INTEGER,
    spo2              INTEGER,
    notlar            TEXT,
    kayit_zamani      TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS doktor_notlari (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    hasta_kodu        TEXT NOT NULL REFERENCES hastalar(hasta_kodu),
    kullanici_id      INTEGER NOT NULL REFERENCES kullanicilar(id),
    tarih             TEXT NOT NULL,
    muayene_notu      TEXT,
    hemsire_talimati  TEXT,
    kayit_zamani      TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS islem_kaydi (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    zaman           TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    kullanici_id    INTEGER,
    eylem           TEXT NOT NULL,
    ayrinti         TEXT
);

-- Kaydedilen (onaylanan) günlük rotalar: her tarih için bir plan
CREATE TABLE IF NOT EXISTS rotalar (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    tarih             TEXT NOT NULL UNIQUE,
    gun               TEXT NOT NULL,
    olusturan_id      INTEGER REFERENCES kullanicilar(id),
    olusturma         TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    en_gec_bitis_dk   INTEGER,
    toplam_km         REAL,
    kan_gecikmesi_dk  INTEGER,
    atlanan           TEXT
);

CREATE TABLE IF NOT EXISTS rota_ekipleri (
    rota_id     INTEGER NOT NULL REFERENCES rotalar(id) ON DELETE CASCADE,
    ekip_no     INTEGER NOT NULL,
    km          REAL,
    bitis_dk    INTEGER,
    PRIMARY KEY (rota_id, ekip_no)
);

CREATE TABLE IF NOT EXISTS rota_duraklari (
    rota_id     INTEGER NOT NULL REFERENCES rotalar(id) ON DELETE CASCADE,
    ekip_no     INTEGER NOT NULL,
    sira        INTEGER NOT NULL,
    tur         TEXT NOT NULL,
    ad          TEXT NOT NULL,
    hasta_kodu  TEXT REFERENCES hastalar(hasta_kodu),
    enlem       REAL,
    boylam      REAL,
    varis_dk    INTEGER,
    ayrilis_dk  INTEGER,
    islemler    TEXT,
    kan_alimi   INTEGER NOT NULL DEFAULT 0,
    tup_sayisi  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (rota_id, ekip_no, sira)
);
"""


# ---------------------------------------------------------------------------
# Bağlantı
# ---------------------------------------------------------------------------
@contextmanager
def baglanti():
    """Veritabanı bağlantısı açar; hata olursa değişiklikleri geri alır."""
    con = sqlite3.connect(ayarlar.VERITABANI)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _sutun_ekle(con, tablo_adi: str, sutun: str, tip: str):
    """Eski veritabanlarına sonradan eklenen sütunu ekler (yoksa)."""
    mevcut = {r[1] for r in con.execute(f"PRAGMA table_info({tablo_adi})")}
    if sutun not in mevcut:
        con.execute(f"ALTER TABLE {tablo_adi} ADD COLUMN {sutun} {tip}")


def kur():
    """Tablolar yoksa oluşturur, eksik sütunları ekler (her açılışta güvenle çağrılabilir)."""
    with baglanti() as con:
        con.executescript(SEMA)
        # Sürüm 2: rotaya mevcut bölge sistemiyle karşılaştırma ve kaynak bilgisi
        _sutun_ekle(con, "rotalar", "mevcut_en_gec_bitis_dk", "INTEGER")
        _sutun_ekle(con, "rotalar", "mevcut_toplam_km", "REAL")
        _sutun_ekle(con, "rotalar", "kaynak", "TEXT")  # 'elle' veya 'otomatik'
        con.execute("UPDATE rotalar SET kaynak = 'elle' WHERE kaynak IS NULL")  # sütundan önceki kayıtlar


def tablo(sql: str, parametreler=()) -> pd.DataFrame:
    with baglanti() as con:
        return pd.read_sql_query(sql, con, params=parametreler)


# ---------------------------------------------------------------------------
# Parolalar (PBKDF2-SHA256, rastgele tuz)
# ---------------------------------------------------------------------------
TEKRAR = 200_000


def parola_hash(parola: str) -> str:
    tuz = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", parola.encode(), bytes.fromhex(tuz), TEKRAR).hex()
    return f"pbkdf2_sha256${TEKRAR}${tuz}${h}"


def parola_dogru_mu(parola: str, kayitli: str) -> bool:
    try:
        _, tekrar, tuz, h = kayitli.split("$")
        hesap = hashlib.pbkdf2_hmac("sha256", parola.encode(), bytes.fromhex(tuz), int(tekrar)).hex()
        return secrets.compare_digest(hesap, h)
    except (ValueError, AttributeError):
        return False


# ---------------------------------------------------------------------------
# İz kaydı (KVKK)
# ---------------------------------------------------------------------------
def iz_kaydi(kullanici_id, eylem: str, ayrinti: str = ""):
    with baglanti() as con:
        con.execute("INSERT INTO islem_kaydi (kullanici_id, eylem, ayrinti) VALUES (?, ?, ?)",
                    (kullanici_id, eylem, ayrinti))


def iz_kayitlari(limit: int = 300) -> pd.DataFrame:
    return tablo(
        """SELECT i.zaman, COALESCE(k.ad_soyad, '-') AS kullanici, i.eylem, i.ayrinti
           FROM islem_kaydi i LEFT JOIN kullanicilar k ON k.id = i.kullanici_id
           ORDER BY i.id DESC LIMIT ?""", (limit,))


# ---------------------------------------------------------------------------
# Kullanıcılar
# ---------------------------------------------------------------------------
def kullanici_dogrula(kullanici_adi: str, parola: str) -> dict | None:
    """Giriş bilgileri doğruysa kullanıcıyı (parola hash'i olmadan) döndürür."""
    with baglanti() as con:
        satir = con.execute("SELECT * FROM kullanicilar WHERE kullanici_adi = ? AND aktif = 1",
                            (kullanici_adi.strip(),)).fetchone()
    if satir is None or not parola_dogru_mu(parola, satir["parola_hash"]):
        return None
    k = dict(satir)
    k.pop("parola_hash")
    return k


def kullanici_ekle(kullanici_adi, ad_soyad, rol, parola, ekip_no=None) -> int:
    with baglanti() as con:
        cur = con.execute(
            "INSERT INTO kullanicilar (kullanici_adi, ad_soyad, rol, ekip_no, parola_hash) VALUES (?, ?, ?, ?, ?)",
            (kullanici_adi.strip(), ad_soyad.strip(), rol, ekip_no, parola_hash(parola)))
        return cur.lastrowid


def kullanicilar() -> pd.DataFrame:
    return tablo("SELECT id, kullanici_adi, ad_soyad, rol, ekip_no, aktif, olusturma FROM kullanicilar ORDER BY rol, ad_soyad")


def kullanici_sayisi() -> int:
    with baglanti() as con:
        return con.execute("SELECT COUNT(*) FROM kullanicilar").fetchone()[0]


def kullanici_guncelle(kullanici_id: int, ad_soyad: str, rol: str, ekip_no, aktif: bool):
    with baglanti() as con:
        con.execute("UPDATE kullanicilar SET ad_soyad = ?, rol = ?, ekip_no = ?, aktif = ? WHERE id = ?",
                    (ad_soyad.strip(), rol, ekip_no, int(aktif), kullanici_id))


def parola_degistir(kullanici_id: int, yeni_parola: str):
    with baglanti() as con:
        con.execute("UPDATE kullanicilar SET parola_hash = ? WHERE id = ?", (parola_hash(yeni_parola), kullanici_id))


def parola_kontrol(kullanici_id: int, parola: str) -> bool:
    with baglanti() as con:
        satir = con.execute("SELECT parola_hash FROM kullanicilar WHERE id = ?", (kullanici_id,)).fetchone()
    return satir is not None and parola_dogru_mu(parola, satir["parola_hash"])


# ---------------------------------------------------------------------------
# Hastalar ve ziyaret planı
# ---------------------------------------------------------------------------
def hastalar(sadece_aktif: bool = False) -> pd.DataFrame:
    """Hasta tablosu + her gün için True/False sütunları (Pzt ... Paz)."""
    df = tablo("SELECT * FROM hastalar" + (" WHERE aktif = 1" if sadece_aktif else "") + " ORDER BY hasta_kodu")
    plan = tablo("SELECT hasta_kodu, gun FROM ziyaret_plani")
    for gun in ayarlar.GUNLER:
        kodlar = set(plan.loc[plan["gun"] == gun, "hasta_kodu"])
        df[gun] = df["hasta_kodu"].isin(kodlar)
    df["haftalik_ziyaret"] = df[ayarlar.GUNLER].sum(axis=1).astype(int)
    df["aktif"] = df["aktif"].astype(bool)
    return df


def hasta_kaydet(hasta: dict, gunler: list[str]):
    """Hastayı ekler ya da günceller (hasta_kodu'na göre) ve ziyaret günlerini yazar."""
    degerler = {"tani": None, "mahalle": None, "konum_tarifi": None, "enlem": None, "boylam": None,
                "konum_kaynagi": None, "notlar": None, **hasta}
    degerler["aktif"] = int(bool(hasta.get("aktif", True)))
    with baglanti() as con:
        con.execute(
            """INSERT INTO hastalar (hasta_kodu, tani, mahalle, konum_tarifi, enlem, boylam, konum_kaynagi, notlar, aktif)
               VALUES (:hasta_kodu, :tani, :mahalle, :konum_tarifi, :enlem, :boylam, :konum_kaynagi, :notlar, :aktif)
               ON CONFLICT(hasta_kodu) DO UPDATE SET
                 tani = excluded.tani, mahalle = excluded.mahalle, konum_tarifi = excluded.konum_tarifi,
                 enlem = excluded.enlem, boylam = excluded.boylam, konum_kaynagi = excluded.konum_kaynagi,
                 notlar = excluded.notlar, aktif = excluded.aktif,
                 guncelleme = datetime('now', 'localtime')""",
            degerler)
        con.execute("DELETE FROM ziyaret_plani WHERE hasta_kodu = ?", (hasta["hasta_kodu"],))
        con.executemany("INSERT INTO ziyaret_plani (hasta_kodu, gun) VALUES (?, ?)",
                        [(hasta["hasta_kodu"], g) for g in gunler])


def yeni_hasta_kodu() -> str:
    """H001, H002 ... sırasındaki bir sonraki boş kod."""
    with baglanti() as con:
        kodlar = [r[0] for r in con.execute("SELECT hasta_kodu FROM hastalar WHERE hasta_kodu LIKE 'H%'")]
    sayilar = [int(k[1:]) for k in kodlar if k[1:].isdigit()]
    return f"H{(max(sayilar) + 1) if sayilar else 1:03d}"


# ---------------------------------------------------------------------------
# İşlemler
# ---------------------------------------------------------------------------
def islem_turleri() -> pd.DataFrame:
    return tablo("SELECT islem, min_dk, max_dk FROM islem_turleri ORDER BY rowid")


def islem_turu_kaydet(islem: str, min_dk: int, max_dk: int):
    with baglanti() as con:
        con.execute("""INSERT INTO islem_turleri (islem, min_dk, max_dk) VALUES (?, ?, ?)
                       ON CONFLICT(islem) DO UPDATE SET min_dk = excluded.min_dk, max_dk = excluded.max_dk""",
                    (islem, int(min_dk), int(max_dk)))


def hasta_islemleri(gun: str | None = None) -> pd.DataFrame:
    if gun is None:
        return tablo("SELECT * FROM hasta_islemleri")
    return tablo("SELECT * FROM hasta_islemleri WHERE gun = ?", (gun,))


def hasta_islemlerini_yaz(satirlar: list[tuple], sentetik: bool):
    """satirlar: [(hasta_kodu, gun, islem), ...]. Aynı türdeki (sentetik/gerçek) eski kayıtları değiştirir."""
    with baglanti() as con:
        con.execute("DELETE FROM hasta_islemleri WHERE sentetik = ?", (int(sentetik),))
        con.executemany("INSERT OR IGNORE INTO hasta_islemleri (hasta_kodu, gun, islem, sentetik) VALUES (?, ?, ?, ?)",
                        [(h, g, i, int(sentetik)) for h, g, i in satirlar])


# ---------------------------------------------------------------------------
# Ziyaret kayıtları (hemşire) ve doktor notları
# ---------------------------------------------------------------------------
def ziyaret_kaydi_ekle(kayit: dict) -> int:
    with baglanti() as con:
        cur = con.execute(
            """INSERT INTO ziyaret_kayitlari
               (hasta_kodu, tarih, kullanici_id, yapilan_islemler, tansiyon, nabiz, ates, seker, spo2, notlar)
               VALUES (:hasta_kodu, :tarih, :kullanici_id, :yapilan_islemler, :tansiyon, :nabiz, :ates,
                       :seker, :spo2, :notlar)""", kayit)
        return cur.lastrowid


def ziyaret_kayitlari(hasta_kodu: str | None = None, tarih: str | None = None,
                      kullanici_id: int | None = None) -> pd.DataFrame:
    sql = """SELECT z.id, z.tarih, z.hasta_kodu, k.ad_soyad AS kaydeden, z.yapilan_islemler, z.tansiyon,
                    z.nabiz, z.ates, z.seker, z.spo2, z.notlar, z.kayit_zamani
             FROM ziyaret_kayitlari z JOIN kullanicilar k ON k.id = z.kullanici_id WHERE 1 = 1"""
    p = []
    if hasta_kodu:
        sql += " AND z.hasta_kodu = ?"
        p.append(hasta_kodu)
    if tarih:
        sql += " AND z.tarih = ?"
        p.append(tarih)
    if kullanici_id:
        sql += " AND z.kullanici_id = ?"
        p.append(kullanici_id)
    return tablo(sql + " ORDER BY z.tarih DESC, z.id DESC", p)


def ziyaret_kayitlari_aralik(baslangic: str, bitis: str) -> pd.DataFrame:
    """İki tarih arasındaki (dahil) tüm ziyaret kayıtları."""
    return tablo("""SELECT z.tarih, z.hasta_kodu, z.kullanici_id, k.ad_soyad AS kaydeden, k.ekip_no,
                           z.yapilan_islemler
                    FROM ziyaret_kayitlari z JOIN kullanicilar k ON k.id = z.kullanici_id
                    WHERE z.tarih BETWEEN ? AND ?""", (baslangic, bitis))


def doktor_notu_ekle(kayit: dict) -> int:
    with baglanti() as con:
        cur = con.execute(
            """INSERT INTO doktor_notlari (hasta_kodu, kullanici_id, tarih, muayene_notu, hemsire_talimati)
               VALUES (:hasta_kodu, :kullanici_id, :tarih, :muayene_notu, :hemsire_talimati)""", kayit)
        return cur.lastrowid


def doktor_notlari(hasta_kodu: str | None = None) -> pd.DataFrame:
    sql = """SELECT d.id, d.tarih, d.hasta_kodu, k.ad_soyad AS doktor, d.muayene_notu, d.hemsire_talimati, d.kayit_zamani
             FROM doktor_notlari d JOIN kullanicilar k ON k.id = d.kullanici_id"""
    if hasta_kodu:
        return tablo(sql + " WHERE d.hasta_kodu = ? ORDER BY d.tarih DESC, d.id DESC", (hasta_kodu,))
    return tablo(sql + " ORDER BY d.tarih DESC, d.id DESC")
